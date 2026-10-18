"""Subscription transport tests: mocked sockets/TLS, never real network access."""
import contextlib
import io
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

from portalproxy.core import CoreError, download_subscription


class FakeSocket:
    def __init__(self, wire):
        self.file = io.BufferedReader(io.BytesIO(wire))
        self.sent = []
        self.closed = False
        self.shutdown_called = False

    def makefile(self, mode, *args, **kwargs):
        return self.file

    def sendall(self, data):
        self.sent.append(bytes(data))

    def setsockopt(self, *args):
        pass

    def settimeout(self, *args):
        pass

    def gettimeout(self):
        return 5

    def shutdown(self, *args):
        self.shutdown_called = True

    def close(self):
        self.closed = True


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'provider.yaml'
        self.path.write_bytes(b'previous cache')

    def tearDown(self):
        self.temp.cleanup()

    def answer(self, address):
        family = socket.AF_INET6 if ':' in address else socket.AF_INET
        sockaddr = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
        return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', sockaddr)

    @contextlib.contextmanager
    def transport(self, wire, addresses=('8.8.8.8',)):
        raw = FakeSocket(wire)
        context = Mock()
        context.wrap_socket.return_value = raw
        with patch('portalproxy.core.socket.getaddrinfo', return_value=[self.answer(a) for a in addresses]) as dns, \
                patch('portalproxy.core.socket.create_connection', return_value=raw) as connect, \
                patch('portalproxy.core.ssl.create_default_context', return_value=context) as tls:
            yield raw, dns, connect, context, tls

    def response(self, body=b'proxies: []\n', status='200 OK', extra=b''):
        return (f'HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\n'.encode()
                + extra + b'Connection: close\r\n\r\n' + body)

    def test_pins_numeric_address_but_preserves_hostname_and_tls_sni(self):
        with self.transport(self.response()) as (raw, dns, connect, context, tls):
            download_subscription('https://subscription.example/path?token=private', self.path)
        self.assertEqual(self.path.read_bytes(), b'proxies: []\n')
        dns.assert_called_once_with('subscription.example', 443, type=socket.SOCK_STREAM)
        self.assertEqual(connect.call_args.args[0], ('8.8.8.8', 443))
        tls.assert_called_once_with()
        context.wrap_socket.assert_called_once_with(raw, server_hostname='subscription.example')
        sent = b''.join(raw.sent)
        self.assertIn(b'GET /path?token=private HTTP/1.1\r\n', sent)
        self.assertIn(b'Host: subscription.example\r\n', sent)
        self.assertIn(b'Accept-Encoding: identity\r\n', sent)
        self.assertTrue(raw.closed)
        if hasattr(self.path.stat(), 'st_mode'):
            import os
            if os.name != 'nt':
                self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_every_dns_address_must_be_public(self):
        for denied in ('127.0.0.1', '169.254.169.254', '192.168.1.1', '100.64.0.1', '::1', 'fd00::1', '::ffff:8.8.8.8'):
            with self.subTest(denied=denied), self.transport(self.response(), ('8.8.8.8', denied)) as (_raw, _dns, connect, _context, _tls):
                with self.assertRaises(CoreError):
                    download_subscription('https://subscription.example/private', self.path)
                connect.assert_not_called()
                self.assertEqual(self.path.read_bytes(), b'previous cache')

    def test_dns_error_empty_and_malformed_results_are_redacted(self):
        with self.transport(self.response()) as (_raw, dns, connect, _context, _tls):
            for result in ([], [(socket.AF_INET,)], None):
                dns.return_value = result
                with self.assertRaises(CoreError) as caught:
                    download_subscription('https://subscription.example/private-token', self.path)
                self.assertNotIn('private-token', str(caught.exception))
            dns.side_effect = OSError('sensitive-private-token')
            with self.assertRaises(CoreError) as caught:
                download_subscription('https://subscription.example/private-token', self.path)
            self.assertNotIn('private-token', str(caught.exception))
            connect.assert_not_called()

    def test_non200_redirect_and_compression_cannot_replace_cache(self):
        for wire in (self.response(status='302 Found', extra=b'Location: https://other.example/\r\n'),
                     self.response(status='206 Partial Content'), self.response(status='404 Not Found'),
                     self.response(extra=b'Content-Encoding: gzip\r\n')):
            with self.subTest(wire=wire), self.transport(wire):
                with self.assertRaises(CoreError):
                    download_subscription('https://subscription.example/private', self.path)
                self.assertEqual(self.path.read_bytes(), b'previous cache')

    def test_empty_invalid_utf8_and_oversized_cannot_replace_cache(self):
        for body in (b'', b'\xff\xfeinvalid', b'x' * (10 * 1024 * 1024 + 1)):
            with self.subTest(length=len(body)), self.transport(self.response(body)):
                with self.assertRaises(CoreError):
                    download_subscription('https://subscription.example/private', self.path)
                self.assertEqual(self.path.read_bytes(), b'previous cache')

    def test_tls_error_closes_raw_socket_and_redacts_secret(self):
        with self.transport(self.response()) as (raw, _dns, _connect, context, _tls):
            context.wrap_socket.side_effect = OSError('failure private-token')
            with self.assertRaises(CoreError) as caught:
                download_subscription('https://subscription.example/private-token', self.path)
            self.assertNotIn('private-token', str(caught.exception))
            self.assertTrue(raw.closed)
            self.assertEqual(self.path.read_bytes(), b'previous cache')

    def test_truncated_content_length_cannot_replace_cache(self):
        wire = b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\nproxies: []\n'
        with self.transport(wire):
            with self.assertRaises(CoreError):
                download_subscription('https://subscription.example/private', self.path)
            self.assertEqual(self.path.read_bytes(), b'previous cache')

    def test_ambiguous_response_framing_cannot_replace_cache(self):
        invalid = (
            b'Content-Length: 11\r\nContent-Length: 11\r\n',
            b'Content-Length: 11\r\nTransfer-Encoding: chunked\r\n',
            b'Transfer-Encoding: chunked\r\nTransfer-Encoding: chunked\r\n',
            b'Transfer-Encoding: gzip\r\n',
            b'Content-Length: -1\r\n',
            b'Content-Length: nope\r\n',
        )
        for fields in invalid:
            with self.subTest(fields=fields), self.transport(b'HTTP/1.1 200 OK\r\n' + fields + b'\r\nproxies: []\n'):
                with self.assertRaises(CoreError):
                    download_subscription('https://subscription.example/private', self.path)
                self.assertEqual(self.path.read_bytes(), b'previous cache')

    def test_valid_chunked_response_and_truncated_chunk(self):
        for body, success in ((b'c\r\nproxies: []\n\r\n0\r\n\r\n', True),
                              (b'c\r\nproxies:', False)):
            self.path.write_bytes(b'previous cache')
            with self.transport(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n' + body):
                if success:
                    download_subscription('https://subscription.example/private', self.path)
                    self.assertEqual(self.path.read_bytes(), b'proxies: []\n')
                else:
                    with self.assertRaises(CoreError):
                        download_subscription('https://subscription.example/private', self.path)
                    self.assertEqual(self.path.read_bytes(), b'previous cache')

    def test_watchdog_shuts_socket_during_blocked_headers(self):
        timers = []
        class ManualTimer:
            def __init__(self, interval, callback):
                self.interval, self.callback, self.cancelled = interval, callback, False
                timers.append(self)
            def start(self):
                pass
            def cancel(self):
                self.cancelled = True
        class BlockedHeaderFile:
            def readline(self, *args):
                timers[0].callback()
                raise OSError('blocked private-token')
            def close(self):
                pass
        with self.transport(self.response()) as (raw, _dns, _connect, _context, _tls):
            raw.file = BlockedHeaderFile()
            with patch('portalproxy.core.threading.Timer', ManualTimer):
                with self.assertRaises(CoreError) as caught:
                    download_subscription('https://subscription.example/private-token', self.path)
            self.assertNotIn('private-token', str(caught.exception))
            self.assertTrue(raw.shutdown_called)
            self.assertTrue(raw.closed)
            self.assertEqual(timers[0].interval, 15)
            self.assertTrue(timers[0].cancelled)
            self.assertEqual(self.path.read_bytes(), b'previous cache')

    def test_monotonic_deadline_cannot_publish_late_body(self):
        with self.transport(self.response()):
            with patch('portalproxy.core.time.monotonic', side_effect=[0, 0, 0, 16, 16, 16]):
                with self.assertRaises(CoreError):
                    download_subscription('https://subscription.example/private', self.path)
            self.assertEqual(self.path.read_bytes(), b'previous cache')


if __name__ == '__main__':
    unittest.main()
