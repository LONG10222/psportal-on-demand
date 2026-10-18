"""Opt-in real Mihomo test using a controlled local upstream, not the Internet."""
import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from portalproxy.config import DEFAULTS
from portalproxy.core import CoreManager
from portalproxy.proxy import ProxyServer
from test_core import port


@unittest.skipUnless(os.environ.get('MIHOMO_BINARY'), 'Set MIHOMO_BINARY to trusted native Mihomo')
class RealCoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_core_http_connect_fixed_selection_and_idle(self):
        requests = []
        async def upstream(reader, writer):
            try:
                header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
                requests.append(header)
                if header.startswith(b'CONNECT '):
                    writer.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
                    await writer.drain()
                    if b'1.1.1.1:443' in header:
                        while data := await reader.read(65536):
                            writer.write(data)
                            await writer.drain()
                    else:
                        inner = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
                        requests.append(inner)
                        writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 12\r\nConnection: close\r\n\r\nreal-mihomo!')
                elif b'/health' in header:
                    writer.write(b'HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n')
                else:
                    writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 12\r\nConnection: close\r\n\r\nreal-mihomo!')
                await writer.drain()
            except (OSError, asyncio.IncompleteReadError, TimeoutError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()
        server = await asyncio.start_server(upstream, '127.0.0.1', 0)
        node_port = server.sockets[0].getsockname()[1]
        with tempfile.TemporaryDirectory() as tmp:
            cfg = dict(DEFAULTS, data_dir=tmp, listen_host='127.0.0.1', listen_port=0,
                allowed_clients=['127.0.0.1'], backend_port=port(), api_port=port(),
                core_path=os.environ['MIHOMO_BINARY'], subscription_url='https://example.com/fixture',
                health_url=f'http://127.0.0.1:{node_port}/health',
                selection_mode='fixed', preferred_node='Tokyo', idle_seconds=1, wakeup_timeout=15)
            # Only subscription transport replaced. Production policy/proxy, generated
            # config, actual core -t/process/controller/node adapter all execute.
            def seed(url, target):
                target.write_text(json.dumps({'proxies':[{'name':'Tokyo','type':'http','server':'127.0.0.1','port':node_port}]}))
            core = CoreManager(cfg)
            proxy = ProxyServer(cfg, core)
            try:
                with patch('portalproxy.core.download_subscription', seed):
                    await proxy.start()
                    core.start_monitor()
                    address = proxy.bound_addresses[0]
                    reader, writer = await asyncio.open_connection(address[0], address[1])
                    writer.write(b'GET http://1.1.1.1/fixture HTTP/1.1\r\nHost: 1.1.1.1\r\n\r\n')
                    await writer.drain()
                    data = await asyncio.wait_for(reader.read(), 20)
                    self.assertIn(b'200 OK', data, repr(requests))
                    self.assertIn(b'real-mihomo!', data)
                    writer.close(); await writer.wait_closed()
                    first_pid = core.process.pid
                    reader, writer = await asyncio.open_connection(address[0], address[1])
                    writer.write(b'CONNECT 1.1.1.1:443 HTTP/1.1\r\nHost: 1.1.1.1:443\r\n\r\n')
                    await writer.drain()
                    header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)
                    self.assertIn(b'200', header)
                    writer.write(b'local-echo'); await writer.drain()
                    self.assertEqual(await asyncio.wait_for(reader.readexactly(10), 5), b'local-echo')
                    await asyncio.sleep(1.2)
                    self.assertEqual(core.process.pid, first_pid)
                    writer.close(); await writer.wait_closed()
                    for _ in range(35):
                        if core.process is None:
                            break
                        await asyncio.sleep(.1)
                    self.assertIsNone(core.process)
                    self.assertTrue(any(b'GET /fixture' in req for req in requests))
            finally:
                await proxy.close()
                await core.close()
                server.close()
                await server.wait_closed()
