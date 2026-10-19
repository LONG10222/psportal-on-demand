"""Desktop runtime ownership and asynchronous interruption regressions.

These display-free tests use explicit offline fixtures. They do not establish
native GUI appearance, network latency, or physical device acceptance.
"""
import io
import json
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from portalproxy.desktop import BackendProcess, DesktopApp
from portalproxy.desktop_view import DesktopView, probe_note


def status(**changes):
    result = dict(event='status', state='listening', listen_host='192.168.50.2',
                  listen_port=10081, connected_clients=1, active_connections=3,
                  node_management=True, nodes=[], busy=False, last_command_id=0,
                  core_state='stopped', command_error='')
    result.update(changes)
    return result


def process_output(*records):
    return SimpleNamespace(stdout=io.StringIO('\n'.join(
        json.dumps(record) if isinstance(record, dict) else record for record in records) + '\n'))


class RuntimeOwnershipTests(unittest.TestCase):
    def test_real_counts_are_distinct_fields_not_derived_from_connections(self):
        backend = BackendProcess()
        child = process_output(status())
        backend.process = child
        backend._read_output(child, values=dict(listen_host='192.168.50.2', listen_port=10081))
        self.assertEqual(backend.snapshot()['connected_clients'], 1)
        self.assertEqual(backend.snapshot()['active_connections'], 3)
        self.assertTrue(backend.events.empty(), 'Structured runtime records are not raw diagnostics')
        backend.process = None

    def test_stale_child_or_wrong_listener_cannot_overwrite_live_snapshot(self):
        backend = BackendProcess()
        live = status(connected_clients=2)
        backend.runtime = live
        old = process_output(status(), 'Core: running')
        backend.process = object()
        backend._read_output(old, values=dict(listen_host='192.168.50.2', listen_port=10081))
        self.assertIs(backend.snapshot(), live)
        self.assertTrue(backend.events.empty())
        current = process_output(status(listen_port=10082))
        backend.process = current
        backend._read_output(current, values=dict(listen_host='192.168.50.2', listen_port=10081))
        self.assertIs(backend.snapshot(), live)
        backend.process = None

    def test_large_bounded_node_snapshot_is_not_discarded_as_a_log(self):
        backend = BackendProcess()
        nodes = [dict(name='fixture-node-' + str(i), delay_ms=None, healthy=None) for i in range(200)]
        child = process_output(status(nodes=nodes))
        backend.process = child
        backend._read_output(child, values=dict(listen_host='192.168.50.2', listen_port=10081))
        self.assertEqual(len(backend.snapshot()['nodes']), 200)
        self.assertTrue(backend.events.empty())
        backend.process = None

    def test_commands_reject_stopped_and_stopping_child(self):
        backend = BackendProcess()
        with self.assertRaises(RuntimeError):
            backend.command('prepare')
        backend.process = SimpleNamespace(poll=lambda: None)
        backend.stopping_since = 1
        with self.assertRaises(RuntimeError):
            backend.command('prepare')
        backend.process = None

    def test_matching_completed_ack_only_releases_pending_command(self):
        app = object.__new__(DesktopApp)
        child = object()
        app.backend = SimpleNamespace(process=child, snapshot=lambda: status(last_command_id=6),
                                      secrets=(), log=Mock())
        app.view = SimpleNamespace(runtime=None)
        app._pending_node_request = (child, 7)
        app._reported_command = None
        app._poll_runtime()
        self.assertIsNotNone(app._pending_node_request)
        app.backend.snapshot = lambda: status(last_command_id=7, busy=True)
        app._poll_runtime()
        self.assertIsNotNone(app._pending_node_request)
        app.backend.snapshot = lambda: status(last_command_id=7, busy=False)
        app._poll_runtime()
        self.assertIsNone(app._pending_node_request)
        self.assertEqual(app.view.core_state, 'stopped')
        app._pending_node_request = (child, 8)
        app.backend.process = object()
        app._poll_runtime()
        self.assertIsNone(app._pending_node_request)

    def test_linked_proxy_cannot_send_node_commands_even_with_wrong_snapshot(self):
        app = object.__new__(DesktopApp)
        app.closing = app.importing = False
        app._pending_node_request = None
        app.raw = dict(existing_proxy_port=7897)
        app.backend = SimpleNamespace(snapshot=lambda: status(), command=Mock(), stopping_since=None)
        app.node_command('prepare')
        app.backend.command.assert_not_called()

    def test_repeated_manual_command_waits_for_backend_ack(self):
        app = object.__new__(DesktopApp)
        app.closing = app.importing = False
        app._pending_node_request = None
        app._node_request = 0
        app.raw = {}
        app.vars = {}
        app.backend = SimpleNamespace(snapshot=lambda: status(), command=Mock(), stopping_since=None,
                                      process=object())
        app.view = SimpleNamespace(_direct_subscription=lambda: True, refresh=Mock(),
            node_table=SimpleNamespace(selection=lambda: ('item',), item=lambda *args: ('HK fixture',)))
        app.node_command('select')
        app.node_command('select')
        app.backend.command.assert_called_once_with('select', request_id=1,
            selection_mode='fixed', preferred_node='HK fixture')

    def test_profile_controls_require_and_send_explicit_group(self):
        app = object.__new__(DesktopApp)
        app.closing = app.importing = False
        app._pending_node_request = None
        app._node_request = 0
        app.raw = {}
        app.vars = {'profile_file': SimpleNamespace(get=lambda: '/fixture/profile.yaml')}
        app.backend = SimpleNamespace(snapshot=lambda: status(), command=Mock(), stopping_since=None,
                                      process=object())
        group = ['']
        app.view = SimpleNamespace(_direct_subscription=lambda: True, refresh=Mock(),
            selection_group_var=SimpleNamespace(get=lambda: group[0]),
            switch_threshold_var=SimpleNamespace(get=lambda: '75'))
        app.node_command('test')
        app.node_command('fastest')
        app.backend.command.assert_not_called()
        group[0] = 'Video policy'
        app.node_command('fastest')
        app.backend.command.assert_called_once_with('select', request_id=1,
            selection_group='Video policy', selection_mode='fastest', preferred_node='', switch_threshold_ms=75)

    def test_prepare_can_discover_profile_groups_without_selecting_one(self):
        app = object.__new__(DesktopApp)
        app.closing = app.importing = False
        app._pending_node_request = None
        app._node_request = 0
        app.raw = {}
        app.vars = {'profile_file': SimpleNamespace(get=lambda: '/fixture/profile.yaml')}
        app.backend = SimpleNamespace(snapshot=lambda: status(), command=Mock(), stopping_since=None,
                                      process=object())
        app.view = SimpleNamespace(_direct_subscription=lambda: True, refresh=Mock(),
            selection_group_var=SimpleNamespace(get=lambda: ''))
        app.node_command('prepare')
        app.backend.command.assert_called_once_with('prepare', request_id=1)


class ImportInterruptionTests(unittest.TestCase):
    def app(self, path):
        app = object.__new__(DesktopApp)
        app.path = path
        app.import_events = queue.Queue()
        app.importing = True
        app.closing = False
        app.quick_start_pending = True
        app._import_generation = 1
        app._import_lock = threading.Lock()
        app._active_import = (1, threading.Event(), path, 0)
        app.backend = SimpleNamespace(process=None, log=Mock())
        app.view = SimpleNamespace(navigation_generation=0, show=Mock())
        app.running_controls = Mock()
        app._set_status = Mock()
        app._use_imported_file = Mock(return_value=True)
        app._configure_lan = Mock(return_value=True)
        app.start = Mock()
        app._t = lambda key: key
        return app

    def test_cancel_is_immediate_and_stale_completion_cleans_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            app = self.app(path)
            cancel_event = app._active_import[1]
            provider = Path(directory) / 'import.yaml'
            metadata = provider.with_suffix('.yaml.info.json')
            provider.write_text('proxies: []')
            metadata.write_text('{}')
            app.cancel_preparation()
            self.assertTrue(cancel_event.is_set())
            self.assertFalse(app.importing)
            self.assertFalse(app.quick_start_pending)
            app.import_events.put((1, provider, None))
            app._poll_import()
            self.assertFalse(provider.exists())
            self.assertFalse(metadata.exists())
            app.start.assert_not_called()
            app._use_imported_file.assert_not_called()

    def test_cancelled_old_import_does_not_complete_newer_import(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'config.json')
            app._active_import = (2, threading.Event(), app.path, 0)
            old = Path(directory) / 'old.yaml'
            old.write_text('proxies: []')
            app.import_events.put((1, old, None))
            app._poll_import()
            self.assertTrue(app.importing)
            self.assertEqual(app._active_import[0], 2)
            app.running_controls.assert_not_called()

    def test_close_cancellation_cleans_already_queued_result_without_another_poll(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'config.json')
            provider = Path(directory) / 'queued.yaml'
            provider.write_text('proxies: []')
            app.import_events.put((1, provider, None))
            app.cancel_preparation()
            self.assertFalse(provider.exists())
            self.assertTrue(app.import_events.empty())

    def test_newer_navigation_wins_over_quick_start_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'config.json')
            app.view.navigation_generation = 1
            app.import_events.put((1, Path(directory) / 'new.yaml', None))
            app._poll_import()
            app.start.assert_called_once()
            app.view.show.assert_not_called()

    def test_changed_configuration_drops_old_result(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'old.json')
            app.path = Path(directory) / 'new.json'
            app.import_events.put((1, None, 'late error'))
            with patch('tkinter.messagebox.showerror') as error:
                app._poll_import()
            error.assert_not_called()
            app._use_imported_file.assert_not_called()

    def test_dismissed_close_preserves_import_and_confirmed_close_cancels(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.app(Path(directory) / 'config.json')
            app.root = SimpleNamespace(destroy=Mock())
            app.dirty = False
            cancel_event = app._active_import[1]
            with patch('tkinter.messagebox.askyesno', return_value=False):
                app.close()
            self.assertFalse(app.closing)
            self.assertTrue(app.importing)
            self.assertFalse(cancel_event.is_set())
            with patch('tkinter.messagebox.askyesno', return_value=True):
                app.close()
            self.assertTrue(app.closing)
            self.assertTrue(cancel_event.is_set())
            app.root.destroy.assert_called_once()


class ViewNavigationTests(unittest.TestCase):
    def test_partial_probe_warning_uses_actual_counts_and_translates(self):
        partial = dict(probe_complete=False, probe_tested=3, probe_total=10)
        self.assertIn('3/10 nodes tested', probe_note(partial, 'en'))
        self.assertIn('已测试 3/10 个节点', probe_note(partial, 'zh'))
        self.assertEqual(probe_note({}, 'en'), '')
        self.assertEqual(probe_note(dict(probe_complete=False, probe_tested=0, probe_total=0), 'en'), '')
        self.assertEqual(probe_note(dict(probe_complete=True, probe_tested=10, probe_total=10), 'en'), '')

    def test_repeated_navigation_never_recreates_widgets_or_starts_a_backend(self):
        view = object.__new__(DesktopView)
        view.page = 'Overview'
        view.navigation_generation = 0
        view.frames = {name: Mock() for name in ('Overview', 'LAN sharing', 'Proxies')}
        view.nav = {name: Mock() for name in view.frames}
        view.refresh = Mock()
        originals = dict(view.frames)
        for _ in range(5):
            view.show('Proxies')
            view.show('Proxies')
            view.show('LAN sharing')
            view.show('Overview')
        self.assertEqual(view.navigation_generation, 15)
        self.assertEqual(view.frames, originals)
        self.assertEqual(view.page, 'Overview')
        with self.assertRaises(ValueError):
            view.show('invalid')


class DesktopLifecycleTests(unittest.TestCase):
    def app(self):
        app = object.__new__(DesktopApp)
        app.closing = app.importing = False
        app.raw = {}
        app.path = Path('/unused-offline-fixture.json')
        app.backend = SimpleNamespace(process=None, start=Mock(), stop=Mock())
        app.view = SimpleNamespace(runtime=None)
        app.stop_button = Mock()
        app.save = Mock(return_value=True)
        app.running_controls = Mock()
        app._set_status = Mock()
        return app

    def test_repeated_start_owns_exactly_one_process(self):
        app = self.app()
        def start(*args):
            app.backend.process = SimpleNamespace(poll=lambda: None)
        app.backend.start.side_effect = start
        for _ in range(5):
            app.start()
        app.backend.start.assert_called_once()
        app.save.assert_called_once()
        app._set_status.assert_called_once_with('Preparing')

    def test_start_during_import_or_close_cannot_start_a_child(self):
        for flag in ('importing', 'closing'):
            app = self.app()
            setattr(app, flag, True)
            app.start()
            app.save.assert_not_called()
            app.backend.start.assert_not_called()

    def test_stop_while_already_stopped_does_not_claim_stopping(self):
        app = self.app()
        app.stop(); app.stop()
        app.backend.stop.assert_not_called()
        app._set_status.assert_not_called()
