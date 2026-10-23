"""Generic accelerators use explicit standard protocols, with no fallback."""
import asyncio
import copy
import io
import json
from pathlib import Path
import socket
import ssl
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from portalproxy import __main__ as backend, config
from portalproxy.accelerator_proxy import (GenericAcceleratorProxy, TEST_TARGET,
    validate_proxy_settings, verify_accelerator_proxy)
from portalproxy.policy import DestinationDenied
from portalproxy.proxy import ProxyServer


def endpoint(protocol='socks5', port=56777):
    return dict(host='127.0.0.1', port=port, protocol=protocol)


def values(protocol='socks5', **changes):
    raw = dict(product_mode='accelerator', accelerator_proxy=endpoint(protocol),
               listen_host='192.168.50.2', allowed_clients=['192.168.50.3'])
    raw.update(changes)
    return raw


def public_answer(port=443, address='8.8.8.8'):
    return (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (address, port))


def generic(raw=None, resolver=None):
    with patch('portalproxy.steam_host.sys.platform', 'win32'):
        return GenericAcceleratorProxy(raw or values(), resolver=resolver)


class AcceleratorProxyConfigTests(unittest.TestCase):
    def test_two_protocols_are_explicit_sources_without_core_or_subscription(self):
        for protocol in ('http', 'socks5'):
            raw = values(protocol)
            before = copy.deepcopy(raw)
            with self.subTest(protocol=protocol), patch('portalproxy.accelerator_proxy.verify_accelerator_proxy') as probe:
                checked = config.validate(raw, '/unused/config.json')
            self.assertEqual(checked['accelerator_proxy'], endpoint(protocol))
            self.assertNotIn('core_path', checked)
            self.assertNotIn('host_relay', checked)
            self.assertEqual(raw, before)
            probe.assert_not_called()

    def test_endpoint_shape_types_credentials_and_non_loopback_are_rejected(self):
        invalid = [None, {}, [], '127.0.0.1:7897', dict(endpoint(), password=''),
                   dict(endpoint(), username='user'), dict(endpoint(), extra=True)]
        for field, bad in [('host', 'localhost'), ('host', '0.0.0.0'), ('host', '::1'),
                           ('host', '8.8.8.8'), ('port', True), ('port', '56777'),
                           ('port', 80), ('port', 65536), ('protocol', 'auto'),
                           ('protocol', 'SOCKS5'), ('protocol', 'socks4')]:
            invalid.append(dict(endpoint(), **{field: bad}))
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_proxy_settings(value)

    def test_all_other_sources_modes_and_self_loop_are_rejected(self):
        for key, value in [('host_relay', 'steam'), ('existing_proxy_port', 7897),
                           ('existing_proxy_provider', 'xianniu'), ('profile_file', '/unused.yaml'),
                           ('subscription_file', '/unused.yaml'), ('subscription_url', 'https://example.com/sub'),
                           ('product_mode', 'game'), ('product_mode', 'mixed'), ('product_mode', 'clash'),
                           ('engine_mode', 'embedded'), ('listen_port', 56777)]:
            raw = values()
            raw[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                config.validate(raw, '/unused/config.json')
        raw = values()
        raw.pop('product_mode')
        with self.assertRaises(ValueError):
            config.validate(raw, '/unused/config.json')

    def test_offline_check_is_cross_platform_without_network_or_core(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps(values()), encoding='utf-8')
            with patch('portalproxy.steam_host.sys.platform', 'linux'), patch('portalproxy.accelerator_proxy.verify_accelerator_proxy') as probe, patch.object(backend, 'serve') as serve, patch.object(backend.sys, 'stdout', io.StringIO()):
                self.assertEqual(backend.main(['--config', str(path), '--check']), 0)
            probe.assert_not_called()
            serve.assert_not_called()

    def test_runtime_remains_windows_only(self):
        with patch('portalproxy.steam_host.sys.platform', 'linux'), self.assertRaisesRegex(ValueError, 'Windows only'):
            GenericAcceleratorProxy(values())


class FakeSocket:
    def __init__(self, incoming):
        self.incoming = bytearray(incoming)
        self.sent = []
        self.closed = False
        self.timeouts = []

    def recv(self, count):
        part = bytes(self.incoming[:count])
        del self.incoming[:count]
        return part

    def sendall(self, data): self.sent.append(data)
    def settimeout(self, timeout): self.timeouts.append(timeout)
    def close(self): self.closed = True


def context(handshake_error=None):
    encrypted = Mock()
    encrypted.do_handshake.side_effect = handshake_error
    encrypted.getpeercert.return_value = {'subjectAltName': [('DNS', TEST_TARGET)]}
    secure = Mock()
    secure.verify_mode, secure.check_hostname = ssl.CERT_REQUIRED, True
    secure.wrap_socket.return_value = encrypted
    return secure, encrypted


SUCCESS_REPLY = b'\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00'


class AcceleratorProxyPreflightTests(unittest.TestCase):
    def verify(self, incoming, protocol='socks5', handshake_error=None):
        transport = FakeSocket(incoming)
        secure, encrypted = context(handshake_error)
        result = verify_accelerator_proxy(endpoint(protocol), socket_factory=Mock(return_value=transport),
                                          context_factory=lambda: secure)
        return result, transport, secure, encrypted

    def test_socks5_noauth_connect_and_target_certificate_are_required(self):
        result, transport, secure, encrypted = self.verify(b'\x05\x00' + SUCCESS_REPLY)
        self.assertTrue(result['probe_passed'])
        self.assertTrue(result['tls_verified'])
        self.assertFalse(result['acceleration_verified'])
        self.assertEqual(result['verified_endpoint'], endpoint())
        self.assertEqual(transport.sent[0], b'\x05\x01\x00')
        self.assertEqual(transport.sent[1], b'\x05\x01\x00\x03' + bytes((len(TEST_TARGET),)) + TEST_TARGET.encode() + b'\x01\xbb')
        secure.wrap_socket.assert_called_once_with(transport, server_hostname=TEST_TARGET, do_handshake_on_connect=False)
        encrypted.do_handshake.assert_called_once_with()
        encrypted.getpeercert.assert_called_once_with()
        self.assertTrue(transport.closed)
        self.assertTrue(all(0 < timeout <= 5 for timeout in transport.timeouts))

    def test_ipv6_and_bounded_domain_bind_replies_are_consumed(self):
        for reply in (b'\x05\x00\x00\x04' + b'\0' * 18,
                      b'\x05\x00\x00\x03\xff' + b'x' * 255 + b'\0\0'):
            with self.subTest(size=len(reply)):
                result, transport, _, _ = self.verify(b'\x05\x00' + reply)
                self.assertTrue(result['probe_passed'])
                self.assertEqual(transport.incoming, b'')

    def test_authentication_wrong_protocol_failed_connect_and_malformed_replies_fail(self):
        for incoming in (b'\x05\x02', b'\x05\xff', b'\x04\x00', b'HTTP/1.1 200 OK\r\n\r\n',
                         b'\x05\x00\x05\x05\x00\x01', b'\x05\x00\x05\x00\x01\x01',
                         b'\x05\x00\x05\x00\x00\xff', b'\x05\x00\x05\x00\x00\x03\x00',
                         b'\x05\x00' + SUCCESS_REPLY[:-1]):
            with self.subTest(incoming=incoming):
                result, transport, secure, _ = self.verify(incoming)
                self.assertFalse(result['probe_passed'])
                self.assertIsNone(result['verified_endpoint'])
                secure.wrap_socket.assert_not_called()
                self.assertTrue(transport.closed)

    def test_successful_socks_reply_without_valid_tls_is_not_a_proxy_proof(self):
        for error in (ssl.SSLError('untrusted client output'), TimeoutError()):
            with self.subTest(error=type(error)):
                result, _, _, _ = self.verify(b'\x05\x00' + SUCCESS_REPLY, handshake_error=error)
                self.assertFalse(result['probe_passed'])
                self.assertFalse(result['tls_verified'])
                self.assertIsNone(result['verified_endpoint'])
                self.assertNotIn('untrusted client output', json.dumps(result))

    def test_insecure_tls_context_missing_certificate_and_connect_timeout_fail(self):
        secure, encrypted = context()
        secure.verify_mode, secure.check_hostname = ssl.CERT_NONE, False
        connect = Mock()
        result = verify_accelerator_proxy(endpoint(), socket_factory=connect, context_factory=lambda: secure)
        self.assertFalse(result['probe_passed'])
        connect.assert_not_called()
        secure, encrypted = context()
        encrypted.getpeercert.return_value = {}
        result = verify_accelerator_proxy(endpoint(), socket_factory=Mock(return_value=FakeSocket(b'\x05\x00' + SUCCESS_REPLY)), context_factory=lambda: secure)
        self.assertEqual(result['reason'], 'tls_certificate_missing')
        result = verify_accelerator_proxy(endpoint(), socket_factory=Mock(side_effect=TimeoutError()), context_factory=lambda: secure)
        self.assertEqual(result['reason'], 'probe_timeout')

    def test_http_requires_connect_and_tls_and_rejects_plain_control_pages(self):
        result, transport, secure, _ = self.verify(b'HTTP/1.1 200 Connection Established\r\n\r\n', protocol='http')
        self.assertTrue(result['probe_passed'])
        self.assertFalse(result['acceleration_verified'])
        self.assertEqual(result['verified_endpoint'], endpoint('http'))
        self.assertTrue(transport.sent[0].startswith(b'CONNECT store.steampowered.com:443 HTTP/1.1\r\n'))
        secure.wrap_socket.assert_called_once()
        for reply in (b'HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\n',
                      b'HTTP/1.1 407 Proxy Authentication Required\r\n\r\n'):
            with self.subTest(reply=reply):
                result, _, secure, _ = self.verify(reply, protocol='http')
                self.assertFalse(result['probe_passed'])
                secure.wrap_socket.assert_not_called()

    def test_fixed_total_deadline_or_invalid_timeout_cannot_pass(self):
        connect = Mock()
        for timeout in (0, -1, float('inf'), float('nan'), 20):
            self.assertFalse(verify_accelerator_proxy(endpoint(), timeout, socket_factory=connect)['probe_passed'])
        connect.assert_not_called()
        with patch('portalproxy.accelerator_proxy.time.monotonic', side_effect=[10.0, 16.0]):
            secure, _ = context()
            result = verify_accelerator_proxy(endpoint(), context_factory=lambda: secure)
        self.assertEqual(result['reason'], 'probe_timeout')


class AcceleratorProxyAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_policy_denies_domain_boundary_bare_ip_private_dns_and_wrong_port(self):
        resolver = AsyncMock(return_value=[public_answer()])
        core = generic(resolver=resolver)
        for host, port in [('steamcommunity.com.evil.example', 443), ('notsteamcommunity.com', 443),
                           ('example.com', 443), ('8.8.8.8', 443), ('steamcommunity.com', 27015)]:
            with self.subTest(host=host, port=port), self.assertRaises(DestinationDenied):
                await core.resolve_target(host, port)
        resolver.assert_not_called()
        resolver.return_value = [public_answer(), public_answer(address='192.168.50.1')]
        with self.assertRaises(DestinationDenied):
            await core.resolve_target('steamcommunity.com', 443)
        resolver.return_value = [public_answer()]
        self.assertEqual((await core.resolve_target('chat.steamcommunity.com', 443)).address, '8.8.8.8')

    async def test_async_socks_handshake_rejects_auth_eof_bad_reply_and_timeout(self):
        core = generic()
        for data in (b'\x05\x02', b'', b'\x05\x00\x05\x00\x00\x08', b'\x05\x00' + SUCCESS_REPLY[:-1]):
            reader = asyncio.StreamReader()
            reader.feed_data(data)
            reader.feed_eof()
            writer = SimpleNamespace(write=Mock(), drain=AsyncMock())
            with self.subTest(data=data), self.assertRaises(ValueError):
                await core.prepare_connection(reader, writer, 'store.steampowered.com', 443)
        core.handshake_timeout = 0.01
        with self.assertRaises(asyncio.TimeoutError):
            await core.prepare_connection(asyncio.StreamReader(), SimpleNamespace(write=Mock(), drain=AsyncMock()), TEST_TARGET, 443)

    async def test_accounting_status_and_closed_core(self):
        core = generic()
        self.assertEqual(await core.acquire(), ('127.0.0.1', 56777))
        self.assertEqual(core.active, 1)
        await core.release()
        self.assertEqual(core.active, 0)
        self.assertFalse(core.status()['node_management'])
        self.assertFalse(core.status()['acceleration_verified'])
        await core.close()
        with self.assertRaises(RuntimeError):
            await core.acquire()


class AcceleratorProxyTransportTests(unittest.IsolatedAsyncioTestCase):
    async def run_exchange(self, protocol, connect):
        received = []
        socks_targets = []
        async def proxy_service(reader, writer):
            try:
                if protocol == 'socks5':
                    self.assertEqual(await reader.readexactly(3), b'\x05\x01\x00')
                    writer.write(b'\x05\x00')
                    await writer.drain()
                    header = await reader.readexactly(5)
                    self.assertEqual(header[:4], b'\x05\x01\x00\x03')
                    name = await reader.readexactly(header[4])
                    port = int.from_bytes(await reader.readexactly(2), 'big')
                    socks_targets.append((name.decode(), port))
                    writer.write(SUCCESS_REPLY)
                    await writer.drain()
                if protocol == 'http' or not connect:
                    received.append(await reader.readuntil(b'\r\n\r\n'))
                if connect:
                    if protocol == 'http':
                        writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                        await writer.drain()
                    received.append(await reader.readexactly(11))
                    writer.write(received[-1])
                else:
                    writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok')
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        upstream = await asyncio.start_server(proxy_service, '127.0.0.1', 0)
        proxy_port = upstream.sockets[0].getsockname()[1]
        port = 443 if connect else 80
        cfg = dict(config.DEFAULTS, accelerator_proxy=endpoint(protocol, proxy_port),
                   listen_host='127.0.0.1', listen_port=0, allowed_clients=['127.0.0.1'])
        core = generic(cfg, AsyncMock(return_value=[public_answer(port)]))
        relay = ProxyServer(cfg, core)
        try:
            await relay.start()
            reader, writer = await asyncio.open_connection(*relay.bound_addresses[0][:2])
            if connect:
                writer.write(b'CONNECT store.steampowered.com:443 HTTP/1.1\r\nHost: store.steampowered.com:443\r\n\r\n')
                await writer.drain()
                self.assertIn(b'200 Connection Established', await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 2))
                writer.write(b'\x16TLSfixture')
                await writer.drain()
                self.assertEqual(await asyncio.wait_for(reader.readexactly(11), 2), b'\x16TLSfixture')
            else:
                writer.write(b'GET http://store.steampowered.com/fixture HTTP/1.1\r\nHost: store.steampowered.com\r\nProxy-Authorization: Basic not-forwarded\r\n\r\n')
                await writer.drain()
                self.assertTrue((await asyncio.wait_for(reader.read(), 2)).endswith(b'ok'))
            writer.close()
            await writer.wait_closed()
            await relay.close()
            self.assertEqual(core.active, 0)
            self.assertFalse(relay.status()['acceleration_verified'])
            return received, socks_targets
        finally:
            await relay.close()
            await core.close()
            upstream.close()
            await upstream.wait_closed()

    async def test_http_upstream_keeps_absolute_form_and_connect(self):
        received, _ = await self.run_exchange('http', False)
        self.assertTrue(received[0].startswith(b'GET http://store.steampowered.com:80/fixture HTTP/1.1\r\n'))
        self.assertNotIn(b'Proxy-Authorization', received[0])
        received, _ = await self.run_exchange('http', True)
        self.assertTrue(received[0].startswith(b'CONNECT store.steampowered.com:443 HTTP/1.1\r\n'))
        self.assertEqual(received[1], b'\x16TLSfixture')

    async def test_socks_upstream_uses_origin_form_and_no_proxy_connect_after_handshake(self):
        received, targets = await self.run_exchange('socks5', False)
        self.assertTrue(received[0].startswith(b'GET /fixture HTTP/1.1\r\n'))
        self.assertEqual(targets, [(TEST_TARGET, 80)])
        self.assertNotIn(b'Proxy-Authorization', received[0])
        received, targets = await self.run_exchange('socks5', True)
        self.assertEqual(received, [b'\x16TLSfixture'])
        self.assertEqual(targets, [(TEST_TARGET, 443)])

    async def test_source_acl_rejects_before_proxy_connection_or_resolution(self):
        resolver = AsyncMock(return_value=[public_answer()])
        core = generic(resolver=resolver)
        relay = ProxyServer(dict(config.DEFAULTS, accelerator_proxy=endpoint(), listen_host='127.0.0.1',
                                 listen_port=0, allowed_clients=['127.0.0.2']), core)
        try:
            await relay.start()
            reader, writer = await asyncio.open_connection(*relay.bound_addresses[0][:2])
            self.assertIn(b'403 Forbidden', await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 2))
            writer.close()
            await writer.wait_closed()
            resolver.assert_not_called()
            self.assertEqual(core.active, 0)
        finally:
            await relay.close()


class AcceleratorProxyBackendTests(unittest.IsolatedAsyncioTestCase):
    def test_backend_preflight_never_echoes_client_errors_or_accepts_incomplete_proofs(self):
        for result in ({'probe_passed': False}, {'probe_passed': True, 'tls_verified': False},
                       {'probe_passed': True, 'tls_verified': True, 'verified_endpoint': endpoint(port=56778)}):
            with self.subTest(result=result), patch('portalproxy.accelerator_proxy.verify_accelerator_proxy', return_value=result):
                with self.assertRaises(ValueError):
                    backend.validate_generic_accelerator_proxy(values())
        with patch('portalproxy.accelerator_proxy.verify_accelerator_proxy', side_effect=RuntimeError('secret-client-details')):
            with self.assertRaises(ValueError) as error:
                backend.validate_generic_accelerator_proxy(values())
        self.assertNotIn('secret-client-details', str(error.exception))

    async def test_failed_preflight_never_opens_listener_or_starts_mihomo(self):
        with patch('portalproxy.steam_host.sys.platform', 'win32'), patch.object(backend, 'validate_generic_accelerator_proxy', side_effect=ValueError('no proof')), patch('portalproxy.proxy.ProxyServer') as listener, patch.object(backend, 'CoreManager') as mihomo, patch.object(backend.signal, 'signal'), patch.object(backend.sys, 'stdout', io.StringIO()):
            with self.assertRaises(ValueError):
                await backend.serve(values())
        listener.assert_not_called()
        mihomo.assert_not_called()

    async def test_preflight_is_off_event_loop_and_parent_eof_prevents_late_listener(self):
        loop_thread = threading.get_ident()
        worker_threads = []
        def check(_):
            worker_threads.append(threading.get_ident())
            threading.Event().wait(0.1)
        with patch('portalproxy.steam_host.sys.platform', 'win32'), patch.object(backend, 'validate_generic_accelerator_proxy', side_effect=check), patch('portalproxy.proxy.ProxyServer') as listener, patch.object(backend.signal, 'signal'), patch.object(backend.sys, 'stdin', io.StringIO('')), patch.object(backend.sys, 'stdout', io.StringIO()):
            await asyncio.wait_for(backend.serve(values(), desktop_child=True), 2)
        listener.assert_not_called()
        self.assertEqual(len(worker_threads), 1)
        self.assertNotEqual(worker_threads[0], loop_thread)


if __name__ == '__main__':
    unittest.main()
