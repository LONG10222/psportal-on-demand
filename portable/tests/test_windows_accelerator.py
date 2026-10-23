import base64
import json
import socket
import ssl
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch

from portalproxy import windows_accelerator as accelerator


def inventory(listeners=(), *, processes=None, installed=True):
    return dict(installations=[dict(display_name='鲜牛网游加速器', install_location='',
                                   display_icon=r'C:\Program Files (x86)\xianniu\XianNiuLauncher.exe,0')] if installed else [],
                processes=[dict(pid=42, name='XianNiu.exe', path=None)] if processes is None else processes,
                listeners=list(listeners), errors=[])


def listener(port=56777, host='127.0.0.1', pid=42):
    return dict(pid=pid, host=host, port=port)


class XianniuDiscoveryTests(unittest.TestCase):
    def test_not_installed_or_running_does_not_probe(self):
        check = Mock()
        missing = accelerator.detect_xianniu(probe=True, inventory=inventory(processes=[], installed=False), verifier=check)
        stopped = accelerator.detect_xianniu(probe=True, inventory=inventory(processes=[]), verifier=check)
        self.assertEqual(missing['reason'], 'not_installed')
        self.assertFalse(missing['installed'])
        self.assertEqual(stopped['reason'], 'not_running')
        self.assertTrue(stopped['installed'])
        check.assert_not_called()

    def test_elevated_main_with_unreadable_path_is_detected_by_name(self):
        found = accelerator.detect_xianniu(inventory=inventory([listener()]))
        self.assertTrue(found['running'])
        self.assertEqual(found['process_ids'], [42])
        self.assertEqual(found['reason'], 'not_probed')
        self.assertIsNone(found['verified_endpoint'])
        self.assertFalse(found['acceleration_verified'])

    def test_only_attributed_ipv4_loopback_ports_are_candidates(self):
        rows = [listener(), listener(56778, '::1'), listener(56779, '0.0.0.0'),
                listener(56780, '::'), listener(12345, pid=999), listener(80), listener()]
        check = Mock(return_value=dict(probe_passed=False, tls_verified=False, reason='probe_timeout'))
        found = accelerator.detect_xianniu(probe=True, inventory=inventory(rows), verifier=check)
        self.assertEqual(len(found['listeners']), 4)
        self.assertEqual(found['candidates'], [listener()])
        check.assert_called_once()
        self.assertEqual(check.call_args.args, ('127.0.0.1', 56777))
        self.assertEqual(found['reason'], 'probe_failed')

    def test_ipv6_or_wildcard_only_is_not_probeable(self):
        check = Mock()
        found = accelerator.detect_xianniu(probe=True,
            inventory=inventory([listener(host='::1'), listener(56778, '0.0.0.0')]), verifier=check)
        self.assertEqual(found['reason'], 'no_loopback_proxy')
        check.assert_not_called()

    def test_helpers_require_main_and_path_inside_verified_installation(self):
        processes = [dict(pid=42, name='XianNiu.exe', path=None),
                     dict(pid=43, name='SocksEngineHelper.exe', path=r'C:\Program Files (x86)\xianniu\mode_ss\SocksEngineHelper.exe'),
                     dict(pid=44, name='socksengine.exe', path=r'C:\Program Files (x86)\xianniu-other\socksengine.exe'),
                     dict(pid=45, name='socksengine.exe', path=None),
                     dict(pid=46, name='socksengine.exe', path=r'C:\Program Files (x86)\xianniu\..\other\socksengine.exe'),
                     dict(pid=47, name='unrelated.exe', path=r'C:\Program Files (x86)\xianniu\unrelated.exe')]
        found = accelerator.detect_xianniu(inventory=inventory([listener(56778, pid=43)], processes=processes))
        self.assertEqual(found['process_ids'], [42, 43])
        self.assertEqual(found['candidates'], [listener(56778, pid=43)])
        without_main = accelerator.detect_xianniu(inventory=inventory(processes=processes[1:]))
        self.assertFalse(without_main['running'])
        self.assertEqual(without_main['process_ids'], [])

    def test_quoted_display_icon_is_metadata_only(self):
        data = inventory()
        data['installations'][0]['display_icon'] = r'"C:\Program Files (x86)\xianniu\XianNiuLauncher.exe",0'
        self.assertEqual(accelerator._installation_roots(data), [r'c:\program files (x86)\xianniu'])

    def test_success_requires_connect_and_verified_tls_and_never_proves_acceleration(self):
        for tls_verified, expected in [(False, False), (True, True)]:
            with self.subTest(tls_verified=tls_verified):
                check = Mock(return_value=dict(probe_passed=True, tls_verified=tls_verified, reason='fixture'))
                found = accelerator.detect_xianniu(probe=True, inventory=inventory([listener()]), verifier=check)
                self.assertEqual(found['probe_passed'], expected)
                self.assertFalse(found['acceleration_verified'])
                self.assertTrue(found['tcp_only'])
                if expected:
                    self.assertEqual(found['verified_endpoint'], dict(listener(), protocol='http-connect'))
                    self.assertEqual(found['capabilities'], ['http-connect-tcp'])
                else:
                    self.assertIsNone(found['verified_endpoint'])

    def test_probe_is_opt_in_and_inventory_failure_never_opens_connections(self):
        check = Mock()
        accelerator.detect_xianniu(inventory=inventory([listener()]), verifier=check)
        error = accelerator.detect_xianniu(probe=True, inventory=dict(errors=['inventory_timeout']), verifier=check)
        self.assertEqual(error['reason'], 'inventory_timeout')
        self.assertIsNone(error['verified_endpoint'])
        check.assert_not_called()

    def test_candidates_and_total_probe_deadline_are_bounded(self):
        check = Mock(return_value=dict(reason='probe_timeout'))
        rows = [listener(50000 + index) for index in range(20)]
        with patch.object(accelerator.time, 'monotonic', side_effect=[100.0, 100.1, 106.1]):
            found = accelerator.detect_xianniu(probe=True, inventory=inventory(rows), verifier=check)
        self.assertEqual(len(found['candidates']), 8)
        check.assert_called_once()
        self.assertLessEqual(check.call_args.kwargs['timeout'], 2)
        self.assertEqual(found['reason'], 'probe_failed')

    def test_malformed_inventory_does_not_broaden_ownership(self):
        data = inventory([listener(pid=True), dict(pid=42, host='127.0.0.1', port=True), listener(pid=999)])
        data['errors'] = [dict(secret='must-not-return'), 'unknown-error']
        data['processes'].extend([dict(pid=True, name='XianNiu.exe'), dict(pid=99, name='notXianNiu.exe')])
        found = accelerator.detect_xianniu(probe=True, inventory=data)
        self.assertEqual(found['candidates'], [])
        self.assertNotIn('secret', json.dumps(found))


class FakeSocket:
    def __init__(self, header=b'HTTP/1.1 200 Connection Established\r\n\r\n'):
        self.header = bytearray(header)
        self.sent = b''
        self.closed = False
        self.timeouts = []

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def sendall(self, data):
        self.sent += data

    def recv(self, count):
        result = bytes(self.header[:count])
        del self.header[:count]
        return result

    def close(self):
        self.closed = True


def tls_context(*, handshake_error=None):
    encrypted = Mock()
    encrypted.getpeercert.return_value = dict(subject=((('commonName', 'example.com'),),))
    encrypted.do_handshake.side_effect = handshake_error
    context = Mock()
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    context.wrap_socket.return_value = encrypted
    return context, encrypted


class XianniuConnectTests(unittest.TestCase):
    def test_connect_and_tls_with_hostname_and_required_certificates(self):
        transport = FakeSocket()
        connect = Mock(return_value=transport)
        context, encrypted = tls_context()
        found = accelerator.verify_http_connect('127.0.0.1', 56777,
            socket_factory=connect, context_factory=lambda: context)
        self.assertTrue(found['probe_passed'])
        self.assertTrue(found['tls_verified'])
        self.assertFalse(found['acceleration_verified'])
        self.assertEqual(transport.sent, b'CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n')
        context.wrap_socket.assert_called_once_with(transport, server_hostname='example.com', do_handshake_on_connect=False)
        encrypted.do_handshake.assert_called_once_with()
        encrypted.getpeercert.assert_called_once_with()
        self.assertTrue(transport.closed)
        encrypted.close.assert_called_once_with()
        self.assertTrue(all(0 < timeout <= 2 for timeout in transport.timeouts))

    def test_plain_http_control_page_200_is_not_a_tunnel(self):
        for header in (b'HTTP/1.1 200 OK\r\nContent-Length: 42\r\n\r\n',
                       b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n'):
            with self.subTest(header=header):
                context, _ = tls_context()
                found = accelerator.verify_http_connect('127.0.0.1', 56777,
                    socket_factory=Mock(return_value=FakeSocket(header)), context_factory=lambda: context)
                self.assertFalse(found['probe_passed'])
                self.assertEqual(found['reason'], 'http_response_is_not_tunnel')
                context.wrap_socket.assert_not_called()

    def test_connect_200_requires_a_real_tls_handshake(self):
        context, encrypted = tls_context(handshake_error=ssl.SSLError('not a TLS tunnel'))
        found = accelerator.verify_http_connect('127.0.0.1', 56777,
            socket_factory=Mock(return_value=FakeSocket()), context_factory=lambda: context)
        self.assertFalse(found['probe_passed'])
        self.assertEqual(found['reason'], 'tls_verification_failed')
        encrypted.close.assert_called_once_with()

    def test_tls_without_verification_or_peer_certificate_is_rejected(self):
        for mode, hostname, certificate in [(ssl.CERT_NONE, False, {}), (ssl.CERT_REQUIRED, True, {})]:
            with self.subTest(mode=mode):
                context, encrypted = tls_context()
                context.verify_mode, context.check_hostname = mode, hostname
                encrypted.getpeercert.return_value = certificate
                found = accelerator.verify_http_connect('127.0.0.1', 56777,
                    socket_factory=Mock(return_value=FakeSocket()), context_factory=lambda: context)
                self.assertFalse(found['probe_passed'])
                self.assertFalse(found['tls_verified'])

    def test_connect_rejected_incomplete_oversized_or_malformed(self):
        for header in (b'HTTP/1.1 403 Forbidden\r\n\r\n', b'HTTP/1.1 200 OK\r\n',
                       b'HTTP/1.1 200 OK\r\nX: ' + b'a' * 8192 + b'\r\n\r\n',
                       b'HTTP/1.1 200 OK\r\n folded: x\r\n\r\n'):
            with self.subTest(header=header[:40]):
                context, _ = tls_context()
                transport = FakeSocket(header)
                found = accelerator.verify_http_connect('127.0.0.1', 56777,
                    socket_factory=Mock(return_value=transport), context_factory=lambda: context)
                self.assertFalse(found['probe_passed'])
                context.wrap_socket.assert_not_called()
                self.assertTrue(transport.closed)

    def test_unattributed_address_injection_and_invalid_port_do_not_connect(self):
        for host, port, target in [('0.0.0.0', 56777, 'example.com'), ('::1', 56777, 'example.com'),
                                   ('localhost', 56777, 'example.com'), ('127.0.0.1', 80, 'example.com'),
                                   ('127.0.0.1', True, 'example.com'),
                                   ('127.0.0.1', 56777, 'example.com\r\nX: injected')]:
            with self.subTest(host=host, port=port, target=target):
                connect = Mock()
                found = accelerator.verify_http_connect(host, port, target, socket_factory=connect)
                self.assertFalse(found['probe_passed'])
                connect.assert_not_called()

    def test_connect_or_tls_timeout_returns_failure(self):
        found = accelerator.verify_http_connect('127.0.0.1', 56777,
            socket_factory=Mock(side_effect=TimeoutError()), context_factory=lambda: tls_context()[0])
        self.assertEqual(found['reason'], 'probe_timeout')
        context, _ = tls_context(handshake_error=TimeoutError())
        found = accelerator.verify_http_connect('127.0.0.1', 56777,
            socket_factory=Mock(return_value=FakeSocket()), context_factory=lambda: context)
        self.assertEqual(found['reason'], 'probe_timeout')

    def test_real_loopback_http_control_service_cannot_pass_tls_check(self):
        request = []
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen(1)
            server.settimeout(2)
            def control_service():
                try:
                    connection, _ = server.accept()
                    with connection:
                        connection.settimeout(2)
                        request.append(connection.recv(4096))
                        connection.sendall(b'HTTP/1.1 200 OK\r\n\r\nThis is an HTTP control page, not TLS.')
                except OSError:
                    pass
            worker = threading.Thread(target=control_service, daemon=True)
            worker.start()
            found = accelerator.verify_http_connect('127.0.0.1', server.getsockname()[1], timeout=2)
            worker.join(timeout=2)
        self.assertFalse(found['probe_passed'])
        self.assertIn(found['reason'], ('tls_verification_failed', 'connection_failed'))
        self.assertTrue(request[0].startswith(b'CONNECT example.com:443 HTTP/1.1\r\n'))


class XianniuInventoryTests(unittest.TestCase):
    def test_powershell_is_hidden_encoded_bounded_and_only_returns_metadata(self):
        data = inventory([listener()])
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(data))
        with patch.object(accelerator.sys, 'platform', 'win32'), patch.object(accelerator.subprocess, 'run', return_value=completed) as run:
            self.assertEqual(accelerator.read_windows_inventory(), data)
        args = run.call_args.args[0]
        self.assertIn('-EncodedCommand', args)
        self.assertEqual(args[args.index('-WindowStyle') + 1], 'Hidden')
        script = base64.b64decode(args[-1]).decode('utf-16-le')
        self.assertIn("Name='XianNiu.exe'", script)
        self.assertIn('-OwningProcess $processIds', script)
        for forbidden in ('CommandLine', 'tunnel.ini', 'Get-Content', 'Start-Process', 'Set-ItemProperty'):
            self.assertNotIn(forbidden, script)
        self.assertFalse(run.call_args.kwargs['shell'])
        self.assertLessEqual(run.call_args.kwargs['timeout'], 15)
        self.assertEqual(run.call_args.kwargs['creationflags'], 0x08000000)

    def test_timeout_malformed_oversized_and_non_windows_fail_closed(self):
        for output in ('not json', '[]', ' ' * (accelerator.MAX_INVENTORY_BYTES + 1)):
            with self.subTest(output=output[:10]), patch.object(accelerator.sys, 'platform', 'win32'), patch.object(accelerator.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout=output)):
                self.assertTrue(accelerator.read_windows_inventory()['errors'])
        with patch.object(accelerator.sys, 'platform', 'win32'), patch.object(accelerator.subprocess, 'run', side_effect=subprocess.TimeoutExpired('powershell', 8)):
            self.assertEqual(accelerator.read_windows_inventory()['errors'], ['inventory_timeout'])
        with patch.object(accelerator.sys, 'platform', 'linux'), patch.object(accelerator.subprocess, 'run') as run:
            self.assertEqual(accelerator.read_windows_inventory()['errors'], ['unsupported_platform'])
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
