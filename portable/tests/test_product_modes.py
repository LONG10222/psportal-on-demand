"""Actual listener-policy/config coverage, with no system networking changes."""
import asyncio
import copy
from contextlib import contextmanager
import errno
import ipaddress
import json
import os
import socket
import time
from pathlib import Path
import queue
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from portalproxy import backend, config, product_modes
from portalproxy.desktop import BackendProcess, DesktopApp, FIELDS, reusable_source, save_config
from portalproxy.proxy import ProxyServer


class Variable:
    def __init__(self, value): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


def sample():
    return dict(config.DEFAULTS, product_mode='game', listen_host='192.168.50.2',
                allowed_clients=['192.168.50.30', '192.168.50.2', '192.168.50.31'],
                subscription_url='https://example.com/provider', core_path=sys.executable,
                preferred_node='Tokyo fixture', selection_mode='fixed',
                node_policies={'PORTAL': {'mode': 'manual', 'name': 'Tokyo fixture'}},
                extra={'retain': ['user preference']})


class ProductModePolicyTests(unittest.TestCase):
    def test_distinct_bind_and_allowlists_without_mutating_inputs(self):
        values = sample()
        original = copy.deepcopy(values)
        expected = {'game': ('192.168.50.2', ['192.168.50.30', '192.168.50.31']),
                    'mixed': ('192.168.50.2', ['192.168.50.30', '192.168.50.31', '192.168.50.2']),
                    'clash': ('127.0.0.1', ['127.0.0.1'])}
        for mode, (host, clients) in expected.items():
            with self.subTest(mode=mode):
                effective = product_modes.effective_config(dict(values, product_mode=mode))
                checked = config.validate(effective, '/unused/config.json')
                proxy = ProxyServer(checked, None)
                self.assertEqual(checked['listen_host'], host)
                self.assertEqual(checked['allowed_clients'], clients)
                self.assertEqual(proxy.allowed_clients, {ipaddress.ip_address(client) for client in clients})
                with patch('portalproxy.proxy.asyncio.start_server', new_callable=AsyncMock) as listen:
                    asyncio.run(proxy.start())
                self.assertEqual(listen.call_args.args[1:3], (host, values['listen_port']))
                self.assertEqual(backend.native_values(checked)['allowed_clients'], clients)
                for key in ('subscription_url', 'node_policies', 'preferred_node', 'selection_mode', 'extra'):
                    self.assertEqual(effective[key], original[key])
                # Product choice must not stand in for a Clash routing policy.
                self.assertEqual(config.render(checked, 'fixture')['mode'], 'rule')
        self.assertEqual(values, original)

    def test_old_configs_migrate_without_widening_access(self):
        self.assertEqual(product_modes.infer_mode({}), 'game')
        self.assertEqual(product_modes.infer_mode(dict(listen_host='127.0.0.1', allowed_clients=['127.0.0.1'])), 'clash')
        self.assertEqual(product_modes.infer_mode(dict(listen_host='192.168.1.2', allowed_clients=['192.168.1.3'])), 'game')
        self.assertEqual(product_modes.infer_mode(dict(listen_host='192.168.1.2', allowed_clients=['192.168.1.2'])), 'mixed')
        with self.assertRaises(ValueError):
            product_modes.infer_mode({'product_mode': 'global'})

    def test_legacy_allowlists_are_never_guessed_to_be_automatic(self):
        for clients in (['192.168.1.1'], [{}], [['192.168.1.1']]):
            self.assertFalse(product_modes.infer_automatic(dict(listen_host='192.168.1.2', allowed_clients=clients)))
        self.assertTrue(product_modes.infer_automatic({'product_lan_automatic': True}))
        self.assertFalse(product_modes.infer_automatic({'product_lan_automatic': 'true'}))

    def test_runtime_config_rejects_mode_acl_mismatch_and_unknown_modes(self):
        valid = product_modes.effective_config(sample())
        invalid = [dict(valid, product_mode='global'),
                   dict(valid, product_mode='clash'),
                   dict(valid, product_mode='mixed'),
                   dict(valid, allowed_clients=valid['allowed_clients'] + [valid['listen_host']]),
                   dict(valid, product_mode='game', listen_host='127.0.0.1', allowed_clients=['127.0.0.1'])]
        for values in invalid:
            with self.subTest(mode=values['product_mode']), self.assertRaises(ValueError):
                config.validate(values, '/unused/config.json')
        legacy = dict(valid, allowed_clients=valid['allowed_clients'] + [valid['listen_host']])
        legacy.pop('product_mode')
        self.assertIn(legacy['listen_host'], config.validate(legacy, '/unused/config.json')['allowed_clients'])

    def test_save_reload_restores_lan_preferences_after_clash(self):
        values = sample()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            effective = product_modes.effective_config(dict(values, product_mode='clash'))
            save_config(path, effective)
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved['listen_host'], '127.0.0.1')
            editable = product_modes.editable_config(saved)
            self.assertEqual(editable['listen_host'], values['listen_host'])
            self.assertEqual(editable['allowed_clients'], values['allowed_clients'])
            restored = product_modes.effective_config(dict(editable, product_mode='game'))
            self.assertNotIn(values['listen_host'], restored['allowed_clients'])
            self.assertEqual(restored['node_policies'], values['node_policies'])

    def test_invalid_game_addresses_are_rejected_but_loopback_needs_no_lan(self):
        for host, clients in [('0.0.0.0', ['192.168.1.2']), ('192.168.1.2', ['0.0.0.0/0']),
                              ('192.168.1.2', ['127.0.0.1']), ('192.168.1.2', ['192.168.1.2'])]:
            with self.subTest(host=host, clients=clients), self.assertRaises(ValueError):
                product_modes.listener_policy('game', host, clients)
        self.assertEqual(product_modes.listener_policy('clash', '', []), ('127.0.0.1', ['127.0.0.1']))
        self.assertEqual(product_modes.listener_policy('mixed', '192.168.1.2', []), ('192.168.1.2', ['192.168.1.2']))


class ProductModeDesktopTests(unittest.TestCase):
    def app(self, path):
        app = object.__new__(DesktopApp)
        app.path, app.root = path, object()
        app.raw = sample()
        app.raw['subscription_file'] = str(path.parent / 'old.json')
        app.raw['source_provenance'] = dict(kind='subscription', path=app.raw['subscription_file'], url=app.raw['subscription_url'])
        Path(app.raw['subscription_file']).write_text('{"proxies": []}')
        app.vars = {key: Variable(', '.join(value) if key == 'allowed_clients' else str(value))
                    for key, value in app.raw.items() if key in dict(FIELDS) or key == 'product_mode'}
        app.vars['profile_file'] = Variable('')
        app.closing = app.importing = app.loading = app.dirty = app.quick_start_pending = False
        app.backend = SimpleNamespace(process=None, start=Mock(), log=Mock(), secrets=())
        app.view = SimpleNamespace(refresh=Mock(), preview=None, subscription_info=None, setup_network='',
                                   navigation_generation=0, show=Mock(), node_message='', language='en', theme='dark')
        app._t = lambda key: key
        app.running_controls, app._set_status, app.engine_controls = Mock(), Mock(), Mock()
        return app

    def test_repeated_selector_changes_leave_all_other_fields_and_saved_file_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'config.json')
            save_config(app.path, app.collect())
            old = app.path.read_bytes()
            original = {key: var.get() for key, var in app.vars.items() if key != 'product_mode'}
            raw = copy.deepcopy(app.raw)
            for mode in ('clash', 'mixed', 'game') * 3:
                app.set_product_mode(mode)
                self.assertEqual(app.collect()['product_mode'], mode)
                self.assertEqual({key: var.get() for key, var in app.vars.items() if key != 'product_mode'}, original)
                self.assertEqual(app.raw, raw)
                self.assertEqual(app.path.read_bytes(), old)
            app.backend.start.assert_not_called()

    def test_selector_ignores_switch_during_start_or_running(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'config.json')
            for state in ('importing', 'closing', 'running'):
                app.importing = state == 'importing'
                app.closing = state == 'closing'
                app.backend.process = object() if state == 'running' else None
                app.set_product_mode('clash')
                self.assertEqual(app.vars['product_mode'].get(), 'game')

    def test_actual_start_passes_effective_policy_and_keeps_preferences_on_failed_spawn(self):
        for mode in ('game', 'mixed', 'clash'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                app = self.app(Path(directory) / 'config.json')
                app.set_product_mode(mode)
                previous = copy.deepcopy(app.raw)
                app.backend.start.side_effect = OSError('controlled failure')
                with patch('tkinter.messagebox.showerror'):
                    self.assertFalse(app.start())
                passed = app.backend.start.call_args.args[1]
                self.assertEqual(passed['listen_host'], '127.0.0.1' if mode == 'clash' else previous['listen_host'])
                self.assertEqual(passed['allowed_clients'], app.collect()['allowed_clients'])
                self.assertEqual(app.raw['node_policies'], previous['node_policies'])
                self.assertEqual(app.raw['subscription_file'], previous['subscription_file'])
                self.assertEqual(app.vars['allowed_clients'].get(), ', '.join(previous['allowed_clients']))

    def test_clash_setup_avoids_lan_discovery_and_preserves_lan_form(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'config.json')
            app.set_product_mode('clash')
            old = app.vars['listen_host'].get(), app.vars['allowed_clients'].get()
            with patch('portalproxy.setup.discover_lan') as discover, \
                 patch('portalproxy.setup.available_port', side_effect=[10101, 10102, 10103]) as port:
                self.assertTrue(app._configure_lan())
            discover.assert_not_called()
            self.assertEqual(old, (app.vars['listen_host'].get(), app.vars['allowed_clients'].get()))
            self.assertTrue(all(call.args[0] == '127.0.0.1' for call in port.call_args_list))

    def test_quick_setup_retains_manual_addresses_and_auto_enumerates_new_network(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'config.json')
            old = app.vars['listen_host'].get(), app.vars['allowed_clients'].get()
            with patch('portalproxy.setup.discover_lan', return_value=dict(host='192.168.50.2', clients=['192.168.50.99'], subnet='192.168.50.0/24')) as discover, \
                 patch('portalproxy.setup.available_port', side_effect=[10101, 10102, 10103]):
                self.assertTrue(app._configure_lan())
            discover.assert_called_once()
            self.assertEqual(old, (app.vars['listen_host'].get(), app.vars['allowed_clients'].get()))
            app.vars['listen_host'].set(''); app.vars['allowed_clients'].set('')
            network = dict(host='192.168.10.2', clients=['192.168.10.3', '192.168.10.4'], subnet='192.168.10.0/29')
            with patch('portalproxy.setup.discover_lan', return_value=network), \
                 patch('portalproxy.setup.available_port', side_effect=[10101, 10102, 10103]):
                self.assertTrue(app._configure_lan())
            self.assertEqual(app.collect()['allowed_clients'], network['clients'])

    def test_automatic_allowlist_follows_changed_wifi_but_manual_devices_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'config.json')
            app._lan_automatic = True
            network = dict(host='192.168.10.2', clients=['192.168.10.3', '192.168.10.4'], subnet='192.168.10.0/29')
            with patch('portalproxy.setup.discover_lan', return_value=network) as discover, \
                 patch('portalproxy.setup.available_port', side_effect=[10101, 10102, 10103]):
                self.assertTrue(app._configure_lan())
            discover.assert_called_once()
            self.assertEqual(app.collect()['listen_host'], network['host'])
            self.assertEqual(app.collect()['allowed_clients'], network['clients'])
            self.assertTrue(app.collect()['product_lan_automatic'])
            app._lan_automatic = False
            network2 = dict(host='192.168.20.2', clients=['192.168.20.99'], subnet='192.168.20.0/24')
            with patch('portalproxy.setup.discover_lan', return_value=network2), \
                 patch('portalproxy.setup.available_port', side_effect=[10101, 10102, 10103]):
                self.assertTrue(app._configure_lan())
            self.assertEqual(app.collect()['listen_host'], network2['host'])
            self.assertEqual(app.collect()['allowed_clients'], network['clients'])
            self.assertFalse(app.collect()['product_lan_automatic'])

    def test_quick_mode_switch_reuses_existing_source_without_download(self):
        for mode in ('game', 'mixed', 'clash'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                app = self.app(Path(directory) / 'config.json')
                app.set_product_mode(mode)
                old = copy.deepcopy(app.raw)
                app.start = Mock(return_value=True)
                app.import_subscription = Mock()
                with patch('portalproxy.setup.discover_lan', return_value=dict(host='192.168.50.2', clients=['192.168.50.30'], subnet='192.168.50.0/24')), \
                     patch('portalproxy.setup.available_port', side_effect=[10101, 10102, 10103]):
                    app.quick_start()
                app.start.assert_called_once()
                app.import_subscription.assert_not_called()
                self.assertEqual(app.raw, old)
                self.assertEqual(app.collect()['subscription_file'], old['subscription_file'])
                self.assertEqual(app.collect()['node_policies'], old['node_policies'])
                self.assertEqual(app.collect()['product_mode'], mode)

    def test_quick_reuse_revalidates_malformed_or_changed_provider_without_mutation(self):
        for contents in ('proxies: [', '{"proxies": [], "rules": []}'):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as directory:
                app = self.app(Path(directory) / 'config.json')
                save_config(app.path, app.collect())
                before = app.path.read_bytes(), copy.deepcopy(app.raw), {k: v.get() for k, v in app.vars.items()}
                Path(app.raw['subscription_file']).write_text(contents)
                app.set_product_mode('clash')
                before = app.path.read_bytes(), copy.deepcopy(app.raw), {k: v.get() for k, v in app.vars.items()}
                app.start = Mock()
                with patch('portalproxy.setup.available_port', side_effect=[10101, 10102, 10103]), \
                     patch('tkinter.messagebox.showerror') as error:
                    app.quick_start()
                app.start.assert_not_called()
                error.assert_called_once()
                self.assertEqual((app.path.read_bytes(), app.raw, {k: v.get() for k, v in app.vars.items()}), before)

    def test_url_edit_then_save_cannot_make_old_provider_reusable(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'config.json')
            accepted_url = app.raw['source_provenance']['url']
            app.vars['subscription_url'].set('https://new.example/subscription')
            app.set_product_mode('clash')
            self.assertTrue(app.save())
            self.assertEqual(app.raw['subscription_url'], 'https://new.example/subscription')
            self.assertEqual(app.raw['source_provenance']['url'], accepted_url)
            app.start = Mock()
            app.import_subscription = Mock()
            with patch('portalproxy.setup.available_port', side_effect=[10101, 10102, 10103]):
                app.quick_start()
            app.start.assert_not_called()
            app.import_subscription.assert_not_called()

    def test_unknown_provenance_does_not_reuse_a_provider_with_edited_url(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'config.json')
            app.raw.pop('source_provenance')
            self.assertFalse(reusable_source(app.raw, app.raw['subscription_file'], app.raw['subscription_url']))
            self.assertTrue(reusable_source(app.raw, app.raw['subscription_file'], ''))
            self.assertFalse(reusable_source(dict(app.raw, source_provenance=[]), app.raw['subscription_file'], ''))

    def test_explicit_local_selection_retains_clear_override_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'config.json')
            source = Path(app.raw['subscription_file'])
            self.assertTrue(app._use_imported_file(source))
            self.assertEqual(app.raw['source_provenance'], dict(kind='local', path=str(source)))
            self.assertTrue(reusable_source(app.raw, str(source), 'https://changed.example/provider'))
            self.assertFalse(reusable_source(app.raw, str(source) + '.different', 'https://changed.example/provider'))

    def test_accepted_import_records_source_url_independently_of_saved_form_url(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'config.json')
            imported = app.path.parent / 'new.json'
            imported.write_text('{"proxies": []}')
            accepted = 'https://accepted.example/provider'
            self.assertTrue(app._use_imported_file(imported, origin_url=accepted))
            self.assertEqual(app.raw['source_provenance'], dict(kind='subscription', path=str(imported), url=accepted))
            self.assertTrue(reusable_source(app.raw, str(imported), accepted))
            self.assertFalse(reusable_source(app.raw, str(imported), app.raw['subscription_url']))

    def test_repeated_explicit_same_url_import_preserves_unsaved_accepted_node_policies(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'config.json')
            policies = copy.deepcopy(app.raw['node_policies'])
            saved_source = app.raw['subscription_file']
            accepted_url = app.raw['source_provenance']['url']
            for index in range(2):
                imported = app.path.parent / f'refresh-{index}.json'
                imported.write_text('{"proxies": []}')
                self.prepare_import(app, imported)
                app.quick_start_pending = False
                app._poll_import()
                self.assertEqual(app.vars['subscription_file'].get(), str(imported))
                self.assertEqual(app.raw['subscription_file'], str(imported))
                self.assertEqual(app.raw['source_provenance'],
                                 dict(kind='subscription', path=str(imported), url=accepted_url))
                self.assertEqual(app.raw['node_policies'], policies)
            app.backend.start.assert_not_called()

    def prepare_import(self, app, imported):
        app.importing = app.quick_start_pending = True
        app.import_events = queue.Queue()
        app._import_generation = 1
        app._import_lock = threading.Lock()
        app._active_import = (1, threading.Event(), app.path, 0, app.raw['subscription_url'])
        app.import_events.put((1, imported, None))

    def test_failed_start_restores_network_but_retains_accepted_import(self):
        for failure in ('spawn', 'before-ready'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                app = self.app(Path(directory) / 'config.json')
                provider = app.path.parent / 'accepted.json'
                provider.write_text('{"proxies": []}')
                app._use_imported_file(provider, origin_url=app.vars['subscription_url'].get())
                app._persist_import()
                accepted = app.path.read_bytes()
                before = copy.deepcopy(app.raw)
                original_lan = app.vars['listen_host'].get(), app.vars['allowed_clients'].get()
                if failure == 'spawn':
                    app.backend.start.side_effect = OSError('controlled failure')
                with patch('portalproxy.setup.discover_lan', return_value=dict(host='192.168.60.2', clients=['192.168.60.3'], subnet='192.168.60.0/24')), \
                     patch('portalproxy.setup.available_port', side_effect=[10101, 10102, 10103]), \
                     patch('tkinter.messagebox.showerror'):
                    app.quick_start()
                if failure == 'before-ready':
                    app._rollback_quick_start()
                self.assertEqual(app.path.read_bytes(), accepted)
                self.assertEqual(app.raw, before)
                self.assertTrue(provider.exists())
                self.assertEqual((app.vars['listen_host'].get(), app.vars['allowed_clients'].get()), original_lan)
    def test_failed_start_does_not_overwrite_configuration_edited_outside_app(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'config.json')
            save_config(app.path, app.collect())
            with patch('portalproxy.setup.discover_lan', return_value=dict(host='192.168.60.2', clients=['192.168.60.3'], subnet='192.168.60.0/24')), \
                 patch('portalproxy.setup.available_port', side_effect=[10101, 10102, 10103]):
                app.quick_start()
            changed = b'{"external_edit": true}\n'
            app.path.write_bytes(changed)
            app._rollback_quick_start()
            self.assertEqual(app.path.read_bytes(), changed)
            self.assertTrue(Path(app.raw['subscription_file']).exists())
            self.assertIn('could not be restored', app.backend.log.call_args.args[0])

    def test_close_after_failed_child_exit_finishes_rollback_before_destroy(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'config.json')
            app.root = Mock()
            save_config(app.path, app.collect())
            old = app.path.read_bytes()
            with patch('portalproxy.setup.discover_lan', return_value=dict(host='192.168.60.2', clients=['192.168.60.3'], subnet='192.168.60.0/24')), \
                 patch('portalproxy.setup.available_port', side_effect=[10101, 10102, 10103]):
                app.quick_start()
            self.assertIsNotNone(app._quick_rollback)
            app.backend.process = SimpleNamespace(poll=lambda: 1)
            app.backend.ready = False
            app.backend.poll = Mock()
            with patch('tkinter.messagebox.askyesno', return_value=True):
                app.close()
            self.assertIsNone(app._quick_rollback)
            self.assertEqual(app.path.read_bytes(), old)
            self.assertTrue(Path(app.raw['subscription_file']).exists())
            app.backend.poll.assert_called_once()
            app.root.destroy.assert_called_once()



class ProductModeLoopbackTests(unittest.TestCase):
    @contextmanager
    def owned_listener(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            provider = folder / 'provider.json'
            provider.write_text('{"proxies": []}')
            ports = set()
            while len(ports) < 3:
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0))
                    ports.add(sock.getsockname()[1])
            listen, upstream, api = sorted(ports)
            values = product_modes.effective_config(dict(sample(), product_mode='clash',
                listen_port=listen, backend_port=upstream, api_port=api,
                subscription_file=str(provider), data_dir=str(folder / 'runtime')))
            path = folder / 'config.json'
            save_config(path, values)
            owner = BackendProcess()
            try:
                owner.start(path, values)
                deadline = time.monotonic() + 10
                while not owner.ready and time.monotonic() < deadline:
                    self.assertIsNone(owner.process.poll())
                    time.sleep(.02)
                self.assertTrue(owner.ready)
                yield folder, listen
                self.assertFalse(list((folder / 'runtime').glob('session-*/config.json')),
                                 'No accepted request must wake the upstream core')
            finally:
                owner.stop()
                if owner.process:
                    owner.process.wait(timeout=15)
                    owner.poll()

    def test_clash_owned_child_listens_locally_without_waking_core(self):
        # This positive test runs independently on every platform, even where
        # the OS does not provide an additional configured loopback address.
        with self.owned_listener() as (_folder, listen):
            with socket.create_connection(('127.0.0.1', listen), timeout=2) as client:
                client.sendall(b'invalid request\r\n\r\n')
                self.assertIn(b'400 Bad Request', client.recv(1024))

    def bind_alternate_source(self, client):
        try:
            client.bind(('127.0.0.2', 0))
        except OSError as error:
            if error.errno == errno.EADDRNOTAVAIL:
                self.skipTest('This OS does not provide a bindable 127.0.0.2 source address')
            raise  # Permissions, resource exhaustion and unexpected errors fail.

    def test_clash_owned_child_rejects_available_alternate_loopback_source(self):
        # Capability probe only: never configure a loopback alias or mutate the
        # host network. macOS normally exposes only 127.0.0.1 without an alias.
        with socket.socket() as client:
            client.settimeout(2)
            self.bind_alternate_source(client)
            with self.owned_listener() as (_folder, listen):
                client.connect(('127.0.0.1', listen))
                self.assertIn(b'403 Forbidden', client.recv(1024))

    def test_alternate_source_probe_skips_only_unavailable_address(self):
        with self.assertRaises(unittest.SkipTest):
            self.bind_alternate_source(SimpleNamespace(bind=Mock(
                side_effect=OSError(errno.EADDRNOTAVAIL, 'unavailable fixture'))))
        for number in (errno.EACCES, errno.EADDRINUSE):
            with self.subTest(errno=number), self.assertRaises(OSError):
                self.bind_alternate_source(SimpleNamespace(bind=Mock(
                    side_effect=OSError(number, 'unexpected fixture'))))

    def test_clash_backend_rejects_other_source_ips_without_os_aliases(self):
        # Exercise the actual backend ACL branch everywhere, independently of
        # platform routing or whether any additional IP can be bound locally.
        for source in ('127.0.0.2', '192.168.50.30', '::1'):
            with self.subTest(source=source):
                core = SimpleNamespace(acquire=AsyncMock(), release=AsyncMock())
                proxy = ProxyServer(product_modes.effective_config(dict(sample(), product_mode='clash')), core)
                reader = SimpleNamespace(readuntil=AsyncMock())
                writer = SimpleNamespace(get_extra_info=Mock(return_value=(source, 32100)),
                    write=Mock(), drain=AsyncMock(), close=Mock(), wait_closed=AsyncMock())
                asyncio.run(proxy._handle(reader, writer))
                self.assertIn(b'403 Forbidden', writer.write.call_args.args[0])
                self.assertEqual(proxy.stats['denied_clients'], 1)
                reader.readuntil.assert_not_awaited()
                core.acquire.assert_not_awaited()


@unittest.skipUnless(os.environ.get('PSPORTAL_TK_TEST') == '1', 'Real Tk product-mode UI opt-in')
class ProductModeWindowTests(unittest.TestCase):
    def test_mode_widgets_preserve_source_and_lan_fields_across_hot_translation(self):
        import tkinter as tk
        root = tk.Tk()
        app = None
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'config.json'
                values = product_modes.effective_config(sample())
                save_config(path, values)
                with patch('portalproxy.existing_proxy.detect_system_proxy', return_value=None):
                    app = DesktopApp(root, path)
                root.update()
                old = path.read_bytes()
                preserved = {key: var.get() for key, var in app.vars.items() if key != 'product_mode'}
                self.assertEqual(root.title(), '星渡 StarPass')
                self.assertTrue(all(button.winfo_viewable() for button in app.view.product_mode_buttons.values()))
                self.assertTrue(app.view.quick_button.winfo_viewable())
                for _ in range(3):
                    for index, mode in enumerate(product_modes.MODES):
                        # Accelerator now opens the separately tested game workspace.
                        if mode == 'accelerator':continue
                        app.view.product_mode_buttons[mode].invoke()
                        root.update()
                        self.assertEqual(app.product_mode(), mode)
                        self.assertEqual(app.collect()['listen_host'], '127.0.0.1' if mode == 'clash' else values['listen_host'])
                        for language in ('zh', 'en'):
                            app.set_language(language)
                            root.update()
                            self.assertEqual(app._t(product_modes.LABELS[mode]), app.view.product_mode_buttons[mode].cget('text'))
                        self.assertEqual({key: var.get() for key, var in app.vars.items() if key != 'product_mode'}, preserved)
                        self.assertEqual(path.read_bytes(), old)
                app.dirty = False
                app.close()
        finally:
            if app:
                app.backend.stop()
            try:
                for timer in root.tk.splitlist(root.tk.call('after', 'info')):
                    root.tk.call('after', 'cancel', timer)
                root.destroy()
            except tk.TclError:
                pass


if __name__ == '__main__':
    unittest.main()
