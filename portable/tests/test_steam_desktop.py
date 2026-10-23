"""Steam host sharing reuses the existing desktop LAN transaction."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from portalproxy.desktop import DesktopApp


class Variable:
    def __init__(self, value): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class SteamDesktopTests(unittest.TestCase):
    def app(self, folder):
        app = object.__new__(DesktopApp)
        app.path = Path(folder) / 'config.json'
        app.root = object()
        app.raw = {'extra': {'preserved': True}}
        app.closing = app.importing = app.setting_up = app.dirty = app.loading = False
        app.backend = SimpleNamespace(process=None, log=Mock())
        app.view = SimpleNamespace(preview=None, subscription_info=None,
            setup_network='192.168.1.0/24', refresh=Mock(), show=Mock())
        app.vars = {key: Variable(value) for key, value in dict(product_mode='mixed',
            engine_mode='external', profile_file='', subscription_file='',
            subscription_url='https://fixture.invalid/source', selection_mode='auto',
            preferred_node='', listen_host='192.168.1.20', allowed_clients='192.168.1.30',
            listen_port='10081').items()}
        app._configure_lan = Mock(return_value=({'listen_host': '192.168.2.20'}, '192.168.2.0/24'))
        app.start = Mock(return_value=True)
        app.engine_controls = Mock()
        app._discard_import = Mock()
        app._t = lambda value: value
        app._selected_product_mode = 'mixed'
        return app

    def test_button_selects_host_network_without_subscription_or_proxy(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.app(folder)
            with patch('portalproxy.desktop.sys.platform', 'win32'):
                app.use_steam_host()
            self.assertEqual(app.raw['host_relay'], 'steam')
            self.assertNotIn('existing_proxy_port', app.raw)
            self.assertEqual(app.vars['subscription_url'].get(), '')
            self.assertEqual(app.vars['product_mode'].get(), 'accelerator')
            self.assertFalse(app.raw['live_node_controls'])
            self.assertEqual(app.raw['accelerator_previous_config']['values']['subscription_url'], 'https://fixture.invalid/source')
            app.start.assert_called_once()
            app.view.show.assert_called_once_with('LAN sharing')

    def test_switching_from_xianniu_keeps_original_independent_source(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.app(folder)
            original = {'subscription_url': 'https://fixture.invalid/original'}
            app.raw.update(existing_proxy_port=12345, existing_proxy_provider='xianniu',
                           linked_previous_source=copy.deepcopy(original))
            with patch('portalproxy.desktop.sys.platform', 'win32'):
                app.use_steam_host()
            self.assertEqual(app.raw['accelerator_previous_config']['raw']['linked_previous_source'], original)
            self.assertNotIn('existing_proxy_provider', app.raw)
            self.assertNotIn('existing_proxy_port', app.raw)

    def test_failed_lan_discovery_preserves_source_and_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.app(folder)
            before = copy.deepcopy(app.raw)
            app._configure_lan.return_value = False
            with patch('portalproxy.desktop.sys.platform', 'win32'):
                app.use_steam_host()
            self.assertEqual(app.raw, before)
            self.assertEqual(app.vars['product_mode'].get(), 'mixed')
            self.assertEqual(app.vars['subscription_url'].get(), 'https://fixture.invalid/source')
            app.start.assert_not_called()

    def test_failed_start_restores_disk_and_original_upstream(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.app(folder)
            app.raw.update(existing_proxy_port=12345, existing_proxy_provider='system')
            before = copy.deepcopy(app.raw)
            original = b'{"previous":true}\n'
            app.path.write_bytes(original)
            def fail():
                written = b'{"host_relay":"steam"}\n'
                app.path.write_bytes(written)
                app._quick_rollback['written'] = written
                return False
            app.start.side_effect = fail
            with patch('portalproxy.desktop.sys.platform', 'win32'):
                app.use_steam_host()
            self.assertEqual(app.path.read_bytes(), original)
            self.assertEqual(app.raw, before)
            self.assertEqual(app.vars['product_mode'].get(), 'mixed')
            app.view.show.assert_not_called()

    def test_saved_host_mode_uses_host_action_instead_of_proxy_discovery(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.app(folder)
            app.raw['host_relay'] = 'steam'
            app.vars['subscription_url'].set('')
            app.use_steam_host = Mock()
            app.use_existing_proxy = Mock()
            app.quick_start()
            app.use_steam_host.assert_called_once()
            app.use_existing_proxy.assert_not_called()

    def test_button_does_nothing_while_listener_or_check_is_active(self):
        with tempfile.TemporaryDirectory() as folder:
            for checking, process in ((True, None), (False, object())):
                app = self.app(folder)
                app.xianniu_checking = checking
                app.backend.process = process
                app.use_steam_host()
                app.start.assert_not_called()
                app._configure_lan.assert_not_called()

    def test_accelerator_selection_is_separate_and_never_starts_on_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.app(folder)
            with patch('portalproxy.desktop.sys.platform', 'win32'):
                app.set_product_mode('accelerator')
            self.assertEqual(app.raw['host_relay'], 'steam')
            self.assertEqual(app.vars['subscription_url'].get(), '')
            app.start.assert_not_called()
            app._configure_lan.assert_not_called()
            self.assertIsNone(app.view.preview)

    def test_switching_modes_restores_normal_source_and_separate_lan_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.app(folder)
            before = copy.deepcopy(app.raw)
            with patch('portalproxy.desktop.sys.platform', 'win32'):
                app.set_product_mode('accelerator')
                app.vars['listen_host'].set('192.168.2.20')
                app.vars['listen_port'].set('10181')
                app.set_product_mode('mixed')
                self.assertEqual(app.vars['subscription_url'].get(), 'https://fixture.invalid/source')
                self.assertEqual(app.vars['listen_host'].get(), '192.168.1.20')
                self.assertEqual(app.vars['listen_port'].get(), '10081')
                self.assertNotIn('host_relay', app.raw)
                self.assertEqual(app.raw['extra'], before['extra'])
                app.set_product_mode('accelerator')
                self.assertEqual(app.vars['listen_host'].get(), '192.168.2.20')
                self.assertEqual(app.vars['listen_port'].get(), '10181')
                self.assertEqual(app.vars['subscription_url'].get(), '')

    def test_saved_accelerator_state_retains_normal_configuration_for_later(self):
        from portalproxy.desktop import _write_config, read_config
        with tempfile.TemporaryDirectory() as folder:
            app = self.app(folder)
            with patch('portalproxy.desktop.sys.platform', 'win32'):
                app.set_product_mode('accelerator')
                _write_config(app.path, dict(app.raw, product_mode='accelerator'))
                app.raw = read_config(app.path)
                app.set_product_mode('mixed')
            self.assertEqual(app.vars['subscription_url'].get(), 'https://fixture.invalid/source')
            self.assertEqual(app.vars['allowed_clients'].get(), '192.168.1.30')
            self.assertNotIn('host_relay', app.raw)

    def test_failed_xianniu_lan_plan_restores_normal_mode_and_source(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.app(folder)
            original = copy.deepcopy(app.raw)
            app._configure_lan.return_value = False
            with patch('portalproxy.desktop.sys.platform', 'win32'):
                app._link_existing_proxy({'host': '127.0.0.1', 'port': 12345}, provider='xianniu')
            self.assertEqual(app.raw, original)
            self.assertEqual(app.vars['product_mode'].get(), 'mixed')
            self.assertEqual(app.vars['subscription_url'].get(), 'https://fixture.invalid/source')
            self.assertEqual(app._selected_product_mode, 'mixed')
            app.start.assert_not_called()

    def test_failed_system_link_restores_accelerator_source_and_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.app(folder)
            with patch('portalproxy.desktop.sys.platform', 'win32'):
                app.set_product_mode('accelerator')
                original = copy.deepcopy(app.raw)
                app._configure_lan.return_value = False
                app._link_existing_proxy({'host': '127.0.0.1', 'port': 12345}, provider='system')
            self.assertEqual(app.raw, original)
            self.assertEqual(app.vars['product_mode'].get(), 'accelerator')
            self.assertEqual(app._selected_product_mode, 'accelerator')
            app.start.assert_not_called()

    def test_accelerator_blocks_normal_imports_without_losing_its_source(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.app(folder)
            with patch('portalproxy.desktop.sys.platform', 'win32'):
                app.set_product_mode('accelerator')
            before = copy.deepcopy(app.raw)
            with patch('portalproxy.profiles.inspect_profile') as inspect:
                self.assertFalse(app._use_imported_file(Path(folder) / 'fixture.yaml'))
                app.import_subscription()
            inspect.assert_not_called()
            self.assertEqual(app.raw, before)

    def test_cached_normal_source_tokens_are_also_redacted(self):
        from portalproxy.desktop import secret_values, redact_log
        raw = {'accelerator_previous_config': {'raw': {'subscription_url':
            'https://fixture.invalid/provider?token=private-fixture-token'}}}
        self.assertNotIn('private-fixture-token', redact_log('error private-fixture-token', secret_values(raw)))
