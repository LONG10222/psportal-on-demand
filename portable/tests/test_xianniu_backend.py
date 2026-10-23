"""Saved Xianniu configurations must be verified before any LAN listener opens."""
import asyncio
import copy
import io
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from portalproxy import __main__ as backend


def verified(port=56777):
    return dict(installed=True, running=True, probe_passed=True,
                process_ids=[42], verified_endpoint=dict(host='127.0.0.1', port=port,
                pid=42, protocol='http-connect'))


def config(provider='xianniu', port=56777):
    return dict(existing_proxy_provider=provider, existing_proxy_port=port,
                listen_host='192.168.50.2', listen_port=10081,
                allowed_clients=['192.168.50.3'])


class XianniuBackendValidationTests(unittest.TestCase):
    def test_generic_upstream_does_not_probe_or_change_config(self):
        for provider in ('system', None):
            with self.subTest(provider=provider):
                values = config(provider)
                before = copy.deepcopy(values)
                with patch('portalproxy.windows_accelerator.detect_xianniu') as detect:
                    backend.validate_existing_proxy(values)
                detect.assert_not_called()
                self.assertEqual(values, before)

    def test_saved_xianniu_is_freshly_verified_and_keeps_its_port(self):
        values = config()
        before = copy.deepcopy(values)
        with patch('portalproxy.windows_accelerator.detect_xianniu', return_value=verified()) as detect:
            backend.validate_existing_proxy(values)
            backend.validate_existing_proxy(values)
        self.assertEqual(detect.call_count, 2)
        detect.assert_called_with(probe=True)
        self.assertEqual(values, before)

    def test_verified_different_port_is_rejected_without_silent_migration(self):
        values = config()
        before = copy.deepcopy(values)
        with patch('portalproxy.windows_accelerator.detect_xianniu', return_value=verified(56778)):
            with self.assertRaisesRegex(ValueError, 'saved Xianniu proxy port no longer matches'):
                backend.validate_existing_proxy(values)
        self.assertEqual(values, before)

    def test_no_process_or_unverified_or_unattributed_listener_cannot_pass(self):
        cases = [dict(installed=False, running=False), dict(installed=True, running=True),
                 dict(verified(), probe_passed=False), dict(verified(), installed=False)]
        for field, value in [('host', '0.0.0.0'), ('pid', True), ('pid', 99),
                             ('port', True), ('protocol', 'socks5')]:
            data = verified()
            data['verified_endpoint'][field] = value
            cases.append(data)
        for data in cases:
            with self.subTest(data=data), patch('portalproxy.windows_accelerator.detect_xianniu', return_value=data):
                with self.assertRaises(ValueError):
                    backend.validate_existing_proxy(config())

    def test_missing_or_invalid_saved_port_does_not_probe(self):
        for port in (None, True, '56777', 80, 65536):
            with self.subTest(port=port), patch('portalproxy.windows_accelerator.detect_xianniu') as detect:
                with self.assertRaisesRegex(ValueError, 'saved loopback proxy port'):
                    backend.validate_existing_proxy(config(port=port))
                detect.assert_not_called()

    def test_errors_never_echo_detector_or_client_details(self):
        with patch('portalproxy.windows_accelerator.detect_xianniu', side_effect=RuntimeError('secret-token-client-output')):
            with self.assertRaises(ValueError) as error:
                backend.validate_existing_proxy(config())
        self.assertNotIn('secret-token', str(error.exception))
        self.assertIn('HTTP CONNECT TCP', str(error.exception))

    def test_config_check_stays_offline_without_starting_or_probing(self):
        values = dict(config(), engine_mode='external')
        with patch.object(backend, 'load', return_value=values), patch.object(backend, 'serve') as serve, patch('portalproxy.windows_accelerator.detect_xianniu') as detect, patch.object(backend.sys, 'stdout', io.StringIO()):
            self.assertEqual(backend.main(['--config', 'fixture.json', '--check']), 0)
        serve.assert_not_called()
        detect.assert_not_called()


class XianniuBackendStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_verification_failure_occurs_before_listener_or_core_creation(self):
        with patch.object(backend, 'validate_existing_proxy', side_effect=ValueError('Xianniu verification failed')), patch('portalproxy.proxy.ProxyServer') as proxy, patch('portalproxy.existing_proxy.ExistingProxy') as core, patch.object(backend.signal, 'signal'), patch.object(backend.sys, 'stdout', io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'verification failed'):
                await backend.serve(config())
        proxy.assert_not_called()
        core.assert_not_called()

    async def test_verification_does_not_block_event_loop(self):
        event_loop_thread = threading.get_ident()
        threads = []
        def check(_):
            threads.append(threading.get_ident())
            raise ValueError('fixture')
        with patch.object(backend, 'validate_existing_proxy', side_effect=check), patch.object(backend.signal, 'signal'), patch.object(backend.sys, 'stdout', io.StringIO()):
            with self.assertRaises(ValueError):
                await backend.serve(config())
        self.assertEqual(len(threads), 1)
        self.assertNotEqual(threads[0], event_loop_thread)

    async def test_parent_eof_during_verification_never_binds_listener(self):
        release = threading.Event()
        def check(_):
            # The parent-reader must already be active before this wait.
            release.wait(timeout=0.2)
        with patch.object(backend, 'validate_existing_proxy', side_effect=check), patch('portalproxy.proxy.ProxyServer') as proxy, patch('portalproxy.existing_proxy.ExistingProxy') as core, patch.object(backend.signal, 'signal'), patch.object(backend.sys, 'stdin', io.StringIO('')), patch.object(backend.sys, 'stdout', io.StringIO()):
            await asyncio.wait_for(backend.serve(config(), desktop_child=True), 2)
        proxy.assert_not_called()
        core.assert_not_called()

    async def test_generic_backend_keeps_existing_transport_without_detector(self):
        stopped = SimpleNamespace(wait=AsyncMock(), set=Mock())
        core = SimpleNamespace(start_monitor=Mock(), close=AsyncMock())
        proxy = SimpleNamespace(start=AsyncMock(), close=AsyncMock())
        with patch.object(backend, 'validate_existing_proxy') as check, patch.object(backend.asyncio, 'Event', return_value=stopped), patch('portalproxy.existing_proxy.ExistingProxy', return_value=core), patch('portalproxy.proxy.ProxyServer', return_value=proxy), patch.object(backend.signal, 'signal'), patch.object(backend.sys, 'stdout', io.StringIO()):
            await backend.serve(config('system'))
        check.assert_not_called()
        proxy.start.assert_awaited_once_with()
        proxy.close.assert_awaited_once_with()
        core.close.assert_awaited_once_with()


if __name__ == '__main__':
    unittest.main()
