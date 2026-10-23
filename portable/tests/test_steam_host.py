"""Explicit Steam host routing never broadens the normal destination policy."""
import asyncio
import io
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from portalproxy import __main__ as backend, config
from portalproxy.existing_proxy import ExistingProxy
from portalproxy.policy import DestinationDenied, ResolutionFailed, Route
from portalproxy.proxy import ProxyServer
from portalproxy.steam_host import STEAM_DOMAINS, SteamHostCore, allowed_target


def answer(address='8.8.8.8', port=443, family=socket.AF_INET):
    sockaddr = (address, port) if family == socket.AF_INET else (address, port, 0, 0)
    return family, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', sockaddr


def host_core(resolver=None):
    with patch('portalproxy.steam_host.sys.platform', 'win32'):
        return SteamHostCore({}, resolver=resolver)


class SteamHostConfigurationTests(unittest.TestCase):
    def values(self, **changes):
        return dict(host_relay='steam', listen_host='127.0.0.1',
                    allowed_clients=['127.0.0.1'], **changes)

    def test_no_core_or_subscription_is_required_and_check_is_offline_cross_platform(self):
        raw = self.values()
        with patch('portalproxy.steam_host.sys.platform', 'linux'), tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps(raw), encoding='utf-8')
            self.assertEqual(config.load(path)['host_relay'], 'steam')
            with patch.object(backend, 'serve') as serve, patch('portalproxy.steam_host.SteamHostCore') as core, patch.object(backend.sys, 'stdout', io.StringIO()):
                self.assertEqual(backend.main(['--config', str(path), '--check']), 0)
            serve.assert_not_called()
            core.assert_not_called()

    def test_conflicting_sources_modes_and_unknown_host_modes_are_rejected(self):
        conflicts = [('existing_proxy_port', 7897), ('profile_file', '/unused.yaml'),
                     ('subscription_file', '/unused.yaml'), ('subscription_url', 'https://example.com/sub'),
                     ('engine_mode', 'embedded'), ('product_mode', 'mixed'),
                     ('product_mode', 'clash'), ('host_relay', ''), ('host_relay', True), ('host_relay', 'all')]
        for key, value in conflicts:
            raw = self.values()
            raw[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                config.validate(raw, '/unused.json')

    def test_explicit_game_mode_keeps_normal_lan_acl_constraints(self):
        raw = dict(host_relay='steam', product_mode='game', listen_host='192.168.50.2',
                   allowed_clients=['192.168.50.3'])
        self.assertEqual(config.validate(raw, '/unused.json')['allowed_clients'], ['192.168.50.3'])
        with self.assertRaises(ValueError):
            config.validate(dict(raw, allowed_clients=['192.168.50.2']), '/unused.json')

    def test_null_host_mode_keeps_existing_proxy_validation(self):
        raw = dict(host_relay=None, existing_proxy_port=7897,
                   listen_host='127.0.0.1', allowed_clients=['127.0.0.1'])
        self.assertEqual(config.validate(raw, '/unused.json')['existing_proxy_port'], 7897)
        with self.assertRaisesRegex(ValueError, 'subscription_url'):
            config.validate(dict(host_relay=None, listen_host='127.0.0.1', allowed_clients=['127.0.0.1']), '/unused.json')

    def test_runtime_is_windows_only(self):
        with patch('portalproxy.steam_host.sys.platform', 'linux'), self.assertRaisesRegex(ValueError, 'Windows only'):
            SteamHostCore({})


class SteamHostResolutionTests(unittest.IsolatedAsyncioTestCase):
    def test_documented_domains_use_label_boundaries_and_only_http_ports(self):
        for root in STEAM_DOMAINS:
            for host in (root, 'cdn.' + root, root.upper() + '.'):
                with self.subTest(host=host):
                    self.assertTrue(allowed_target(host, 80))
                    self.assertTrue(allowed_target(host, 443))
            for host in ('not' + root, root + '.evil.example', root + '..', 'x..' + root):
                self.assertFalse(allowed_target(host, 443))
        for host in ('127.0.0.1', '8.8.8.8', '192.168.50.1', '2606:4700:4700::1111', 'example.com'):
            self.assertFalse(allowed_target(host, 443))
        for port in (22, 27015, True, '443'):
            self.assertFalse(allowed_target('steamcommunity.com', port))

    async def test_every_answer_is_public_and_result_is_pinned_numerically(self):
        resolve = AsyncMock(return_value=[answer(), answer('2606:4700:4700::1111', family=socket.AF_INET6)])
        core = host_core(resolve)
        route = await core.resolve_target('STORE.STEAMPOWERED.COM.', 443)
        self.assertEqual(route, Route('external', '8.8.8.8'))
        resolve.assert_awaited_once_with('store.steampowered.com', 443,
            family=socket.AF_UNSPEC, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)

    async def test_any_private_reserved_or_mixed_dns_answer_rejects_entire_request(self):
        for address in ('127.0.0.1', '192.168.50.1', '10.0.0.1', '100.64.0.1',
                        '169.254.169.254', '192.0.2.1', '224.0.0.1', '0.0.0.0'):
            with self.subTest(address=address):
                core = host_core(AsyncMock(return_value=[answer(), answer(address)]))
                with self.assertRaises(DestinationDenied):
                    await core.resolve_target('steamcommunity.com', 443)
        for address in ('::1', 'fc00::1', 'fe80::1', '2001:db8::1', '::ffff:8.8.8.8'):
            with self.subTest(address=address):
                core = host_core(AsyncMock(return_value=[answer(), answer(address, family=socket.AF_INET6)]))
                with self.assertRaises(DestinationDenied):
                    await core.resolve_target('steamcommunity.com', 443)

    async def test_denied_domains_never_resolve_and_bad_dns_never_falls_back(self):
        resolve = AsyncMock()
        core = host_core(resolve)
        for host, port in [('steamcommunity.com.evil.example', 443), ('8.8.8.8', 443), ('steamcommunity.com', 27015)]:
            with self.assertRaises(DestinationDenied):
                await core.resolve_target(host, port)
        resolve.assert_not_called()
        for answers in ([], [None], [answer(port=80)],
                        [(socket.AF_INET, socket.SOCK_DGRAM, 0, '', ('8.8.8.8', 443))],
                        [answer('8.8.8.8', family=socket.AF_INET6)]):
            with self.subTest(answers=answers), self.assertRaises(ResolutionFailed):
                await host_core(AsyncMock(return_value=answers)).resolve_target('steamcommunity.com', 443)
        with self.assertRaises(ResolutionFailed):
            await host_core(AsyncMock(side_effect=OSError('resolver error'))).resolve_target('steamcommunity.com', 443)

    async def test_session_accounting_and_status_never_claim_acceleration(self):
        core = host_core()
        self.assertIsNone(await core.acquire())
        self.assertEqual(core.active, 1)
        await core.release()
        await core.release()
        self.assertEqual(core.active, 0)
        self.assertFalse(core.status()['node_management'])
        self.assertFalse(core.status()['acceleration_verified'])
        self.assertTrue(core.status()['tcp_only'])
        await core.close()
        with self.assertRaises(RuntimeError):
            await core.acquire()


class SteamHostTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_origin_form_reaches_numeric_target_without_proxy_headers(self):
        received = []
        async def origin(reader, writer):
            try:
                received.append(await reader.readuntil(b'\r\n\r\n'))
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok')
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        await self.run_transport(origin, connect=False, received=received)
        self.assertTrue(received[0].startswith(b'GET /store?fixture=1 HTTP/1.1\r\n'))
        self.assertIn(b'Host: store.steampowered.com:80\r\n', received[0])
        self.assertNotIn(b'Proxy-Authorization', received[0])
        self.assertNotIn(b'GET http://', received[0])

    async def test_connect_sends_only_client_tunnel_bytes_to_numeric_target(self):
        received = []
        async def origin(reader, writer):
            try:
                received.append(await reader.readexactly(11))
                writer.write(received[-1])
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        await self.run_transport(origin, connect=True, received=received)
        self.assertEqual(received, [b'\x16TLSfixture'])

    async def run_transport(self, origin, *, connect, received):
        upstream = await asyncio.start_server(origin, '127.0.0.1', 0)
        origin_port = upstream.sockets[0].getsockname()[1]
        real_connect = asyncio.open_connection
        port = 443 if connect else 80
        core = host_core(AsyncMock(return_value=[answer(port=port)]))
        values = dict(config.DEFAULTS, host_relay='steam', listen_host='127.0.0.1',
                      listen_port=0, allowed_clients=['127.0.0.1'])
        proxy = ProxyServer(values, core)
        calls = []
        async def mocked_outbound(host, target_port, **options):
            # Only the test connector maps the public numeric destination to an
            # isolated origin fixture. Production destination rules stay intact.
            calls.append((host, target_port))
            self.assertEqual((host, target_port), ('8.8.8.8', port))
            return await real_connect('127.0.0.1', origin_port, **options)
        try:
            await proxy.start()
            with patch('portalproxy.proxy.asyncio.open_connection', side_effect=mocked_outbound), patch('portalproxy.proxy.resolve_destination') as normal_resolver:
                reader, writer = await real_connect(*proxy.bound_addresses[0][:2])
                if connect:
                    writer.write(b'CONNECT store.steampowered.com:443 HTTP/1.1\r\nHost: store.steampowered.com:443\r\n\r\n')
                    await writer.drain()
                    header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 2)
                    self.assertIn(b'200 Connection Established', header)
                    writer.write(b'\x16TLSfixture')
                    await writer.drain()
                    self.assertEqual(await asyncio.wait_for(reader.readexactly(11), 2), b'\x16TLSfixture')
                else:
                    writer.write(b'GET http://store.steampowered.com/store?fixture=1 HTTP/1.1\r\nHost: store.steampowered.com\r\nProxy-Authorization: Basic must-not-forward\r\n\r\n')
                    await writer.drain()
                    self.assertTrue((await asyncio.wait_for(reader.read(), 2)).endswith(b'ok'))
                writer.close()
                await writer.wait_closed()
                normal_resolver.assert_not_called()
            await proxy.close()
            self.assertEqual(core.active, 0)
            self.assertEqual(calls, [('8.8.8.8', port)])
        finally:
            await proxy.close()
            await core.close()
            upstream.close()
            await upstream.wait_closed()

    async def test_source_acl_is_enforced_before_dns_or_outbound_connection(self):
        resolver = AsyncMock(return_value=[answer()])
        core = host_core(resolver)
        proxy = ProxyServer(dict(config.DEFAULTS, host_relay='steam', listen_host='127.0.0.1',
                                 listen_port=0, allowed_clients=['127.0.0.2']), core)
        real_connect = asyncio.open_connection
        try:
            await proxy.start()
            reader, writer = await real_connect(*proxy.bound_addresses[0][:2])
            with patch('portalproxy.proxy.asyncio.open_connection') as outbound:
                # Source rejection happens before reading any HTTP bytes.
                self.assertIn(b'403 Forbidden', await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 2))
                outbound.assert_not_called()
            writer.close()
            await writer.wait_closed()
            resolver.assert_not_called()
            self.assertEqual(core.active, 0)
        finally:
            await proxy.close()

    async def test_ordinary_existing_proxy_still_receives_absolute_form(self):
        received = []
        async def existing(reader, writer):
            received.append(await reader.readuntil(b'\r\n\r\n'))
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n')
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        upstream = await asyncio.start_server(existing, '127.0.0.1', 0)
        values = dict(config.DEFAULTS, host_relay=None, listen_host='127.0.0.1', listen_port=0,
                      allowed_clients=['127.0.0.1'], existing_proxy_port=upstream.sockets[0].getsockname()[1])
        proxy = ProxyServer(values, ExistingProxy(values))
        try:
            await proxy.start()
            with patch('portalproxy.proxy.resolve_destination', AsyncMock(return_value=Route('external'))):
                reader, writer = await asyncio.open_connection(*proxy.bound_addresses[0][:2])
                writer.write(b'GET http://example.com/fixture HTTP/1.1\r\nHost: example.com\r\n\r\n')
                await writer.drain()
                self.assertIn(b'200 OK', await asyncio.wait_for(reader.read(), 2))
                writer.close()
                await writer.wait_closed()
            self.assertTrue(received[0].startswith(b'GET http://example.com:80/fixture HTTP/1.1\r\n'))
        finally:
            await proxy.close()
            upstream.close()
            await upstream.wait_closed()


class SteamHostBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_steam_backend_never_constructs_mihomo_or_checks_xianniu_proxy(self):
        stopped = SimpleNamespace(wait=AsyncMock(), set=Mock())
        proxy = SimpleNamespace(start=AsyncMock(), close=AsyncMock())
        values = dict(config.DEFAULTS, host_relay='steam', existing_proxy_provider='xianniu',
                      listen_host='192.168.50.2', listen_port=10081)
        with patch('portalproxy.steam_host.sys.platform', 'win32'), patch.object(backend, 'CoreManager') as mihomo, patch.object(backend, 'validate_existing_proxy') as verify, patch.object(backend.asyncio, 'Event', return_value=stopped), patch('portalproxy.proxy.ProxyServer', return_value=proxy) as listener, patch.object(backend.signal, 'signal'), patch.object(backend.sys, 'stdout', io.StringIO()):
            await backend.serve(values)
        mihomo.assert_not_called()
        verify.assert_not_called()
        self.assertIsInstance(listener.call_args.args[1], SteamHostCore)
        proxy.start.assert_awaited_once_with()


if __name__ == '__main__':
    unittest.main()
