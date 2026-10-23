"""Selective PAC serving stays behind the LAN ACL and discloses no config."""
import asyncio
import json
import shutil
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from portalproxy import config
from portalproxy.accelerator_pac import make_accelerator_pac
from portalproxy.proxy import ProxyServer
from portalproxy.steam_host import STEAM_DOMAINS


class AcceleratorPacScriptTests(unittest.TestCase):
    def test_only_private_numeric_ipv4_and_valid_nonzero_ports_are_accepted(self):
        for host, port in [('192.168.50.2', 10081), ('10.0.0.2', 1), ('172.16.0.2', 65535), ('127.0.0.1', 10081)]:
            self.assertIsInstance(make_accelerator_pac(host, port), bytes)
        for host, port in [('0.0.0.0', 10081), ('8.8.8.8', 10081), ('169.254.1.2', 10081),
                           ('localhost', 10081), ('::1', 10081), ('192.168.050.2', 10081),
                           ('192.168.1.2\r\nsecret', 10081), (None, 10081),
                           ('192.168.1.2', 0), ('192.168.1.2', True), ('192.168.1.2', '10081'),
                           ('192.168.1.2', 65536)]:
            with self.subTest(host=host, port=port), self.assertRaises(ValueError):
                make_accelerator_pac(host, port)

    def test_bounded_script_has_fixed_domains_and_no_dns_or_direct_proxy_fallback(self):
        script = make_accelerator_pac('192.168.50.2', 10081).decode('ascii')
        self.assertLess(len(script), 4096)
        for domain in STEAM_DOMAINS:
            self.assertIn('"' + domain + '"', script)
        self.assertIn('host.slice(-(domains[i].length + 1)) === "." + domains[i]', script)
        self.assertEqual(script.count('return "PROXY 192.168.50.2:10081";'), 1)
        self.assertEqual(script.count('return "DIRECT";'), 1)
        for forbidden in ('PROXY 192.168.50.2:10081; DIRECT', 'dnsResolve', 'isResolvable',
                          'subscription', 'accelerator_previous_config', 'password', 'token'):
            self.assertNotIn(forbidden, script)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is optional for executing the generated PAC')
    def test_actual_javascript_domain_boundaries_case_and_nonsteam_direct_routes(self):
        cases = []
        for domain in STEAM_DOMAINS:
            cases.extend([(domain, True), ('cdn.' + domain, True), (domain.upper() + '.', True),
                          ('not' + domain, False), (domain + '.evil.example', False)])
        cases.extend([('example.com', False), ('8.8.8.8', False), ('192.168.50.1', False)])
        script = make_accelerator_pac('192.168.50.2', 10081).decode('ascii')
        script += ('\nprocess.stdout.write(JSON.stringify(' + json.dumps([host for host, _ in cases]) +
            '.map(function(h) { return FindProxyForURL("https://" + h + "/", h); })));')
        result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True,
                                text=True, encoding='utf-8', timeout=5, check=True,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        expected = ['PROXY 192.168.50.2:10081' if steam else 'DIRECT' for _, steam in cases]
        self.assertEqual(json.loads(result.stdout), expected)


class AcceleratorPacTransportTests(unittest.IsolatedAsyncioTestCase):
    async def start_relay(self, mode='accelerator', allowed=None, **changes):
        self.core = SimpleNamespace(resolve_target=AsyncMock(), acquire=AsyncMock(),
                                    release=AsyncMock(), status=lambda: {'node_management': False})
        values = dict(config.DEFAULTS, product_mode=mode, host_relay='steam',
                      listen_host='127.0.0.1', listen_port=0,
                      allowed_clients=allowed or ['127.0.0.1'],
                      accelerator_previous_config={'raw': {'subscription_url': 'https://private.invalid/secret-sentinel',
                                                          'token': 'source-secret-sentinel'}},
                      custom_secret='private-config-sentinel')
        values.update(changes)
        self.relay = ProxyServer(values, self.core)
        await self.relay.start()
        self.host, self.port = self.relay.bound_addresses[0][:2]

    async def asyncTearDown(self):
        if hasattr(self, 'relay'):
            await self.relay.close()

    async def exchange(self, request):
        reader, writer = await asyncio.open_connection(self.host, self.port)
        try:
            writer.write(request)
            await writer.drain()
            return await asyncio.wait_for(reader.read(), 2)
        finally:
            writer.close()
            await writer.wait_closed()

    def request(self, method='GET', target='/accelerator.pac', version='HTTP/1.1', fields=None):
        if fields is None:
            fields = [f'Host: {self.host}:{self.port}']
        return ('\r\n'.join([f'{method} {target} {version}'] + fields) + '\r\n\r\n').encode('ascii')

    async def test_origin_form_serves_pac_with_real_ephemeral_listener_and_no_dns_or_upstream(self):
        await self.start_relay()
        with patch('portalproxy.proxy.resolve_destination') as dns:
            response = await self.exchange(self.request())
        header, body = response.split(b'\r\n\r\n', 1)
        self.assertTrue(header.startswith(b'HTTP/1.1 200 OK\r\n'))
        self.assertIn(b'Content-Type: application/x-ns-proxy-autoconfig', header)
        self.assertIn(b'Cache-Control: no-store', header)
        self.assertIn(b'Connection: close', header)
        self.assertIn(f'Content-Length: {len(body)}'.encode(), header)
        self.assertEqual(body, make_accelerator_pac(self.host, self.port))
        self.assertNotIn(b'PROXY 127.0.0.1:0', body)
        for private in (b'secret-sentinel', b'private-config-sentinel', b'accelerator_previous_config'):
            self.assertNotIn(private, response)
        dns.assert_not_called()
        self.core.resolve_target.assert_not_called()
        self.core.acquire.assert_not_called()

    async def test_http10_and_matching_absolute_form_are_supported(self):
        await self.start_relay()
        requests = [self.request(version='HTTP/1.0', fields=[]),
                    self.request(target=f'http://{self.host}:{self.port}/accelerator.pac')]
        for request in requests:
            with self.subTest(request=request):
                response = await self.exchange(request)
                self.assertIn(b'200 OK', response)
                self.assertIn(b'function FindProxyForURL', response)
        self.core.acquire.assert_not_called()

    async def test_wrong_methods_bodies_and_hosts_never_receive_pac(self):
        await self.start_relay()
        host = f'Host: {self.host}:{self.port}'
        requests = [self.request(method='POST'), self.request(method='HEAD'),
                    self.request(fields=[host, 'Content-Length: 1']),
                    self.request(fields=[host, 'Transfer-Encoding: chunked']),
                    self.request(fields=[host, 'Expect: 100-continue']),
                    self.request(fields=['Host: example.com']),
                    self.request(fields=[]), self.request(fields=[host, host]),
                    self.request(target='http://example.com/accelerator.pac', fields=['Host: example.com'])]
        with patch('portalproxy.proxy.resolve_destination') as dns:
            for request in requests:
                with self.subTest(request=request):
                    response = await self.exchange(request)
                    self.assertTrue(response.startswith(b'HTTP/1.1 4'))
                    self.assertNotIn(b'FindProxyForURL', response)
                    self.assertNotIn(b'application/x-ns-proxy-autoconfig', response)
        dns.assert_not_called()
        self.core.resolve_target.assert_not_called()
        self.core.acquire.assert_not_called()

    async def test_exact_fixed_route_only_no_query_or_path_prefix(self):
        await self.start_relay()
        for target in ('/accelerator.pac?secret=1', '/accelerator.pac/other', '/other.pac'):
            with self.subTest(target=target):
                response = await self.exchange(self.request(target=target))
                self.assertNotIn(b'FindProxyForURL', response)
                self.assertTrue(response.startswith(b'HTTP/1.1 400'))
        self.core.resolve_target.assert_not_called()

    async def test_unauthorized_source_is_rejected_before_pac_or_dns(self):
        await self.start_relay(allowed=['127.0.0.2'])
        reader, writer = await asyncio.open_connection(self.host, self.port)
        try:
            response = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 2)
            self.assertIn(b'403 Forbidden', response)
            self.assertNotIn(b'FindProxyForURL', response)
        finally:
            writer.close()
            await writer.wait_closed()
        self.core.resolve_target.assert_not_called()
        self.core.acquire.assert_not_called()

    async def test_concurrent_limit_still_applies_to_pac(self):
        await self.start_relay(max_connections=1)
        first_reader, first_writer = await asyncio.open_connection(self.host, self.port)
        try:
            for _ in range(100):
                if self.relay.stats['active'] == 1:
                    break
                await asyncio.sleep(0.005)
            second_reader, second_writer = await asyncio.open_connection(self.host, self.port)
            try:
                response = await asyncio.wait_for(second_reader.readuntil(b'\r\n\r\n'), 2)
                self.assertIn(b'503 Service Unavailable', response)
                self.assertNotIn(b'FindProxyForURL', response)
            finally:
                second_writer.close()
                await second_writer.wait_closed()
        finally:
            first_writer.close()
            await first_writer.wait_closed()

    async def test_normal_modes_do_not_expose_origin_pac_route(self):
        for mode in ('game', 'mixed', 'clash'):
            with self.subTest(mode=mode):
                await self.start_relay(mode=mode)
                response = await self.exchange(self.request())
                self.assertTrue(response.startswith(b'HTTP/1.1 400'))
                self.assertNotIn(b'FindProxyForURL', response)
                self.core.resolve_target.assert_not_called()
                await self.relay.close()


if __name__ == '__main__':
    unittest.main()
