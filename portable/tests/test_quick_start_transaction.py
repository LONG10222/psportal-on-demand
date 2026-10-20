"""Failed one-click preparation must leave the previous sharing setup intact."""
import copy
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from portalproxy.desktop import DesktopApp


class Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class QuickStartTransactionTests(unittest.TestCase):
    def app(self):
        app = object.__new__(DesktopApp)
        app.root = object()
        app.closing = app.importing = app.quick_start_pending = False
        app.raw = {'existing_proxy_port': 7897, 'extra': {'preserved': True}}
        app.backend = SimpleNamespace(process=None, log=Mock())
        app.view = SimpleNamespace(setup_network='192.168.1.0/24', refresh=Mock(),
                                   navigation_generation=0, show=Mock(), language='en', theme='dark')
        app.vars = {key: Variable(value) for key, value in dict(
            listen_host='192.168.1.20', allowed_clients='192.168.1.30',
            listen_port='10081', backend_port='10082', api_port='10090',
            subscription_url='not a URL').items()}
        app._t = lambda key: key
        return app

    def snapshot(self, app):
        return copy.deepcopy((app.raw, {key: var.get() for key, var in app.vars.items()},
                              app.view.setup_network))

    def network(self):
        return dict(host='192.168.2.20', clients=['192.168.2.30'], subnet='192.168.2.0/24')

    def test_failed_network_detection_keeps_linked_proxy_and_all_settings(self):
        app = self.app()
        before = self.snapshot(app)
        app.import_subscription = Mock()
        with patch('portalproxy.setup.discover_lan', side_effect=ValueError('Use Advanced settings.')), \
             patch('tkinter.messagebox.showerror'):
            app.quick_start()
        self.assertEqual(self.snapshot(app), before)
        app.import_subscription.assert_not_called()

    def test_invalid_subscription_url_keeps_linked_proxy_and_manual_allowlist(self):
        app = self.app()
        before = self.snapshot(app)
        with patch('portalproxy.setup.discover_lan', return_value=self.network()), \
             patch('portalproxy.setup.available_port', side_effect=[10101, 10102, 10103]), \
             patch('tkinter.messagebox.showerror') as error:
            app.quick_start()
        error.assert_not_called()
        self.assertIn('Paste a subscription', app.subscription_message)
        self.assertEqual(self.snapshot(app), before)
        self.assertFalse(app.importing)
        self.assertFalse(app.quick_start_pending)

    def test_port_failure_does_not_apply_half_of_new_network_configuration(self):
        app = self.app()
        before = self.snapshot(app)
        with patch('portalproxy.setup.discover_lan', return_value=self.network()), \
             patch('portalproxy.setup.available_port', side_effect=[10101, ValueError('No available proxy port.')]), \
             patch('tkinter.messagebox.showerror'):
            self.assertFalse(app._configure_lan())
        self.assertEqual(self.snapshot(app), before)
        app.view.refresh.assert_not_called()

    def test_import_is_pending_without_applying_new_network_or_losing_linked_mode(self):
        app = self.app()
        before = self.snapshot(app)
        app.import_subscription = Mock(side_effect=lambda: setattr(app, 'importing', True))
        with patch('portalproxy.setup.discover_lan', return_value=self.network()), \
             patch('portalproxy.setup.available_port', side_effect=[10101, 10102, 10103]):
            app.quick_start()
        self.assertFalse(app.quick_start_pending)
        app.import_subscription.assert_not_called()
        self.assertEqual(self.snapshot(app), before)

    def pending_import(self, app, path):
        app.path = path
        app.importing = app.quick_start_pending = True
        app.import_events = queue.Queue()
        app._import_generation = 1
        app._import_lock = threading.Lock()
        app._active_import = (1, threading.Event(), path, 0)
        app.running_controls = Mock()
        app._set_status = Mock()

    def test_failed_download_keeps_previous_linked_configuration(self):
        app = self.app()
        before = self.snapshot(app)
        self.pending_import(app, Path('/unused/config.json'))
        app.import_events.put((1, None, 'Subscription import failed.'))
        with patch('tkinter.messagebox.showerror'):
            app._poll_import()
        self.assertEqual(self.snapshot(app), before)
        self.assertFalse(app.importing)

    def test_cancelled_preparation_keeps_previous_linked_configuration(self):
        app = self.app()
        before = self.snapshot(app)
        self.pending_import(app, Path('/unused/config.json'))
        app.cancel_preparation()
        self.assertEqual(self.snapshot(app), before)
        self.assertFalse(app.importing)

    def test_import_ignores_network_changes_and_keeps_lan_fields(self):
        app = self.app()
        app.vars.update(engine_mode=Variable('external'), profile_file=Variable(''), subscription_file=Variable(''))
        app.start = Mock()
        old_lan = app.vars['listen_host'].get(), app.vars['allowed_clients'].get()
        with tempfile.TemporaryDirectory() as folder:
            self.pending_import(app, Path(folder) / 'config.json')
            provider = Path(folder) / 'import.json'
            provider.write_text('{"proxies": []}', encoding='utf-8')
            app.import_events.put((1, provider, None))
            with patch('portalproxy.setup.discover_lan', side_effect=AssertionError('Import must not inspect LAN')):
                app._poll_import()
            self.assertTrue(provider.exists())
            self.assertEqual((app.vars['listen_host'].get(), app.vars['allowed_clients'].get()), old_lan)
            self.assertEqual(app.vars['subscription_file'].get(), str(provider))
            self.assertNotIn('existing_proxy_port', app.raw)
        app.start.assert_not_called()

    def test_validated_provider_import_can_switch_from_linked_to_owned_mode(self):
        app = self.app()
        app.vars.update(engine_mode=Variable('external'), profile_file=Variable(''),
                        subscription_file=Variable(''))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'provider.json'
            path.write_text('{"proxies": []}', encoding='utf-8')
            self.assertTrue(app._use_imported_file(path))
            self.assertEqual(app.vars['subscription_file'].get(), str(path))
        self.assertNotIn('existing_proxy_port', app.raw)
        self.assertEqual(app.raw['extra'], {'preserved': True})

    def test_final_provider_validation_failure_does_not_apply_staged_network(self):
        app = self.app()
        app.vars.update(engine_mode=Variable('embedded'), profile_file=Variable(''),
                        subscription_file=Variable(''))
        app.start = Mock()
        before = self.snapshot(app)
        with tempfile.TemporaryDirectory() as folder:
            self.pending_import(app, Path(folder) / 'config.json')
            provider = Path(folder) / 'import.json'
            provider.write_text('{"proxies": [], "rules": []}', encoding='utf-8')
            app.import_events.put((1, provider, None))
            with patch('portalproxy.setup.discover_lan', return_value=self.network()), \
                 patch('portalproxy.setup.available_port', side_effect=[10101, 10102, 10103]), \
                 patch('tkinter.messagebox.showerror') as error:
                app._poll_import()
            self.assertEqual(self.snapshot(app), before)
            self.assertFalse(provider.exists())
            error.assert_called_once()
        app.start.assert_not_called()

    def test_valid_import_saves_source_without_network_or_start(self):
        app = self.app()
        app.vars.update(engine_mode=Variable('external'), profile_file=Variable(''), subscription_file=Variable(''))
        app.start = Mock()
        with tempfile.TemporaryDirectory() as folder:
            self.pending_import(app, Path(folder) / 'config.json')
            provider = Path(folder) / 'import.json'
            provider.write_text('{"proxies": []}', encoding='utf-8')
            app.import_events.put((1, provider, None))
            with patch('portalproxy.setup.discover_lan') as network, patch('portalproxy.setup.available_port') as ports:
                app._poll_import()
            network.assert_not_called(); ports.assert_not_called()
            self.assertTrue(provider.exists())
            self.assertTrue(app.path.exists())
            self.assertEqual(app.raw['subscription_file'], str(provider))
        app.start.assert_not_called()
        app.view.show.assert_not_called()

    def test_successful_configuration_applies_complete_network_once(self):
        app = self.app()
        with patch('portalproxy.setup.discover_lan', return_value=self.network()), \
             patch('portalproxy.setup.available_port', side_effect=[10101, 10102, 10103]):
            self.assertTrue(app._configure_lan())
        self.assertEqual(app.vars['listen_host'].get(), '192.168.2.20')
        self.assertEqual(app.vars['allowed_clients'].get(), '192.168.2.30')
        self.assertEqual([app.vars[key].get() for key in ('listen_port', 'backend_port', 'api_port')],
                         ['10101', '10102', '10103'])
        self.assertEqual(app.raw['existing_proxy_port'], 7897)
        app.view.refresh.assert_called_once()


if __name__ == '__main__':
    unittest.main()
