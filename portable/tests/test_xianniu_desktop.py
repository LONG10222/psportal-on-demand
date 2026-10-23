"""Client checks must not turn an unverified local service into a LAN proxy."""
import copy
from pathlib import Path
import queue
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from portalproxy.desktop import DesktopApp


class XianniuDesktopTests(unittest.TestCase):
    def app(self):
        app = object.__new__(DesktopApp)
        app.path = Path('fixture-config.json')
        app.root = object()
        app.raw = {'existing_proxy_port': 7897, 'extra': {'keep': True}}
        app.closing = app.importing = app.setting_up = False
        app.xianniu_checking = True
        app._xianniu_generation = 1
        app.xianniu_events = queue.Queue()
        app.backend = SimpleNamespace(process=None)
        app.view = SimpleNamespace(refresh=Mock())
        app.running_controls = Mock()
        app._link_existing_proxy = Mock()
        app._t = lambda value: value
        return app

    def test_unverified_control_port_does_not_change_configuration(self):
        app = self.app()
        before = copy.deepcopy(app.raw)
        app.xianniu_events.put((app.path, 1, 'link', {'running': True, 'probe_passed': False,
            'verified_endpoint': {'host': '127.0.0.1', 'port': 56777}}))
        with patch('tkinter.messagebox.showinfo') as info:
            app._poll_xianniu()
        info.assert_called_once()
        app._link_existing_proxy.assert_not_called()
        self.assertEqual(app.raw, before)
        self.assertFalse(app.xianniu_checking)

    def test_verified_loopback_endpoint_uses_existing_lan_transaction(self):
        app = self.app()
        endpoint = {'host': '127.0.0.1', 'port': 12345}
        app.xianniu_events.put((app.path, 1, 'link', {'running': True, 'probe_passed': True,
                                         'verified_endpoint': endpoint}))
        app._poll_xianniu()
        app._link_existing_proxy.assert_called_once_with(endpoint, provider='xianniu')
        self.assertFalse(app._xianniu_starting)

    def test_verified_claim_with_unsafe_endpoint_cannot_start(self):
        for endpoint in ({'host': '0.0.0.0', 'port': 12345},
                         {'host': '127.0.0.1', 'port': True},
                         {'host': '127.0.0.1', 'port': 80}):
            with self.subTest(endpoint=endpoint):
                app = self.app()
                app.xianniu_events.put((app.path, 1, 'link', {'running': True, 'probe_passed': True,
                                                 'verified_endpoint': endpoint}))
                with patch('tkinter.messagebox.showinfo'):
                    app._poll_xianniu()
                app._link_existing_proxy.assert_not_called()

    def test_stale_result_and_close_never_start_a_listener(self):
        for close, owner in ((False, Path('old-config.json')), (True, Path('fixture-config.json'))):
            with self.subTest(close=close):
                app = self.app()
                app.closing = close
                app.xianniu_events.put((owner, 1, 'link', {'probe_passed': True,
                    'verified_endpoint': {'host': '127.0.0.1', 'port': 12345}}))
                app._poll_xianniu()
                app._link_existing_proxy.assert_not_called()

    def test_saved_xianniu_rechecks_client_instead_of_using_system_proxy(self):
        app = self.app()
        app.raw['existing_proxy_provider'] = 'xianniu'
        app.xianniu_checking = False
        app.use_xianniu_proxy = Mock()
        with patch('portalproxy.existing_proxy.detect_system_proxy') as system:
            app.quick_start()
        system.assert_not_called()
        app.use_xianniu_proxy.assert_called_once()

    def test_advanced_start_also_rechecks_a_saved_xianniu_endpoint(self):
        app = self.app()
        app.raw['existing_proxy_provider'] = 'xianniu'
        app.xianniu_checking = False
        app.use_xianniu_proxy = Mock()
        app.save = Mock()
        self.assertFalse(app.start())
        app.save.assert_not_called()
        app.use_xianniu_proxy.assert_called_once_with(action='manual')

    def test_cancelled_check_cannot_start_sharing_when_its_worker_finishes(self):
        app = self.app()
        app.stop()
        self.assertFalse(app.xianniu_checking)
        app.xianniu_events.put((app.path, 1, 'link', {'probe_passed': True,
            'verified_endpoint': {'host': '127.0.0.1', 'port': 12345}}))
        app._poll_xianniu()
        app._link_existing_proxy.assert_not_called()

    def test_manual_restart_keeps_lan_settings_and_rolls_back_failed_start(self):
        app = self.app()
        app.raw['existing_proxy_provider'] = 'xianniu'
        app._quick_snapshot = Mock(return_value={'fixture': 'snapshot'})
        app._configure_lan = Mock()
        app._rollback_quick_start = Mock()
        app.start = Mock(return_value=False)
        app.xianniu_events.put((app.path, 1, 'manual', {'probe_passed': True,
            'verified_endpoint': {'host': '127.0.0.1', 'port': 12345}}))
        app._poll_xianniu()
        app._configure_lan.assert_not_called()
        app._link_existing_proxy.assert_not_called()
        app.start.assert_called_once()
        app._rollback_quick_start.assert_called_once()

    def test_real_link_transaction_restores_previous_proxy_and_saved_bytes(self):
        app = self.app()
        app.raw.update(existing_proxy_provider='system', linked_previous_source={
            'engine_mode': 'external', 'subscription_url': 'https://fixture.invalid/source'})
        previous_raw = copy.deepcopy(app.raw)
        class Variable:
            def __init__(self, value): self.value = value
            def get(self): return self.value
            def set(self, value): self.value = value
        app.vars = {key: Variable(value) for key, value in dict(product_mode='game',
            engine_mode='external', profile_file='', subscription_file='', subscription_url='',
            selection_mode='auto', preferred_node='', listen_host='192.168.1.20',
            allowed_clients='192.168.1.30', listen_port='10081').items()}
        previous_values = {key: variable.get() for key, variable in app.vars.items()}
        app.view.preview = None
        app.view.subscription_info = {'keep': 'old display'}
        app.view.setup_network = '192.168.1.0/24'
        app.dirty = app.loading = False
        app.engine_controls = Mock()
        app.backend.log = Mock()
        app._discard_import = Mock()
        app._configure_lan = Mock(return_value=({'listen_host': '192.168.2.20'}, '192.168.2.0/24'))
        with tempfile.TemporaryDirectory() as folder:
            app.path = Path(folder) / 'config.json'
            original = b'{"previous":"configuration"}\n'
            app.path.write_bytes(original)
            def failed_start():
                written = b'{"temporary":"xianniu"}\n'
                app.path.write_bytes(written)
                app._quick_rollback['written'] = written
                return False
            app.start = Mock(side_effect=failed_start)
            DesktopApp._link_existing_proxy(app, {'host': '127.0.0.1', 'port': 12345}, provider='xianniu')
            self.assertEqual(app.path.read_bytes(), original)
        self.assertEqual(app.raw, previous_raw)
        self.assertEqual({key: variable.get() for key, variable in app.vars.items()}, previous_values)
        self.assertEqual(app.view.subscription_info, {'keep': 'old display'})
        self.assertEqual(app.view.setup_network, '192.168.1.0/24')
