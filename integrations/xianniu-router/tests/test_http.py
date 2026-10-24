import asyncio
import base64
import contextlib
import struct
import unittest
from unittest.mock import patch
from starpass_http.policy import Route
from starpass_http.proxy import ProxyServer
from xianniu_router.protocol import frame, rc4, read_frame
from xianniu_router.runtime import Service
from xianniu_router.http_streams import NativeCore, NativeReader
from xianniu_router.http_proxy import make_proxy
from starpass_http.policy import DestinationDenied
AUTH = {'u': base64.b64encode(b'fixture-user').decode(),
        'key': base64.b64encode(b'fixture-key').decode(), 'x': '', 'plain_second': True}


class RouterPolicy(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = Service({'node': {'host': '8.8.8.8', 'port': 1}, 'auth': AUTH,
                                'devices': ['192.168.31.112'], 'dns_server': '192.168.31.1'})
        self.proxy = make_proxy(self.service, '192.168.31.222', 10082)

    async def test_router_dns_uses_configured_lan_resolver(self):
        with patch('xianniu_router.http_proxy.resolve_real', return_value='8.8.8.8') as resolve:
            route = await self.proxy.config['destination_resolver']('example.com', 443)
            self.assertEqual(route.kind, 'external')
            resolve.assert_called_once_with('example.com', '192.168.31.1')

    async def test_private_and_fake_ip_destinations_are_rejected(self):
        for hostname in ('192.168.31.1', '127.0.0.1', '198.18.0.1', '::1'):
            with self.assertRaises(DestinationDenied):
                await self.proxy.config['destination_resolver'](hostname, 443)
        with patch('xianniu_router.http_proxy.resolve_real', return_value='198.18.0.2'):
            with self.assertRaises(DestinationDenied):
                await self.proxy.config['destination_resolver']('example.com', 443)

    async def test_failed_renewal_blocks_new_proxy_sessions(self):
        self.service.refresh_failures = 3
        with self.assertRaises(RuntimeError):
            await self.proxy.core.acquire()
        self.service.refresh_failures = 0
        self.assertEqual(await self.proxy.core.acquire(), ('127.0.0.1', 1))

class Streams(unittest.IsolatedAsyncioTestCase):
    async def test_fragmented_frame_and_clean_eof(self):
        reader = asyncio.StreamReader()
        native = NativeReader(reader, {'received': 0})
        pending = asyncio.create_task(native.read(2))
        encoded = frame(b'abcdef')
        for byte in encoded:
            reader.feed_data(bytes([byte]))
            await asyncio.sleep(0)
        self.assertEqual(await pending, b'ab')
        self.assertEqual(await native.read(10), b'cdef')
        reader.feed_eof()
        self.assertEqual(await native.read(10), b'')

    async def test_truncated_body_never_becomes_clean_eof(self):
        reader = asyncio.StreamReader()
        reader.feed_data(struct.pack('<I', 5))
        reader.feed_eof()
        with self.assertRaises(ValueError):
            await NativeReader(reader, {'received': 0}).read()

class HTTPInterop(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.observed = []
        self.tasks = set()

        async def accept(reader, writer):
            try:
                head = await reader.readexactly(8)
                fields = []
                for _ in range(4):
                    size, = struct.unpack('<I', await reader.readexactly(4))
                    fields.append(await reader.readexactly(size))
                host = rc4(fields[2], b'fixture-key')
                self.observed.append({'command': head[1], 'host': host,
                                      'port': int.from_bytes(head[2:4], 'big'), 'data': bytearray()})
                row = self.observed[-1]
                writer.write(b'\x00\x5a' + b'\x00' * 6)
                await writer.drain()
                if row['port'] == 443:
                    payload = await read_frame(reader)
                    row['data'].extend(payload)
                    response = frame(payload)
                    for offset in range(0, len(response), 3):
                        writer.write(response[offset:offset+3])
                        await writer.drain()
                        await asyncio.sleep(0)
                else:
                    while b'\r\n\r\n' not in row['data']:
                        row['data'].extend(await read_frame(reader))
                    if b'Transfer-Encoding: chunked' in row['data']:
                        while not row['data'].endswith(b'0\r\n\r\n'):
                            row['data'].extend(await read_frame(reader))
                    writer.write(frame(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK'))
                    await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError):
                pass
            finally:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()

        def tracked(r, w):
            task = asyncio.create_task(accept(r, w))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

        self.node = await asyncio.start_server(tracked, '127.0.0.1', 0)
        self.service = Service({'node': {'host': '127.0.0.1',
                                        'port': self.node.sockets[0].getsockname()[1]}, 'auth': AUTH})
        self.proxy = ProxyServer({'listen_host': '127.0.0.1', 'listen_port': 0,
                                  'allowed_clients': ['127.0.0.1'], 'request_timeout': 2}, NativeCore(self.service))
        await self.proxy.start()
        self.port = self.proxy.bound_addresses[0][1]
        # Only this controlled test replaces DNS classification; production does not.
        async def fixture_route(host, port):
            return Route('external')
        self.patch = patch('starpass_http.proxy.resolve_destination', fixture_route)
        self.patch.start()

    async def asyncTearDown(self):
        self.patch.stop()
        await self.proxy.close()
        self.node.close()
        await self.node.wait_closed()
        for task in tuple(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def test_connect_tunnels_binary_without_nested_connect(self):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        writer.write(b'CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n')
        await writer.drain()
        self.assertIn(b'200 Connection Established', await reader.readuntil(b'\r\n\r\n'))
        payload = bytes(range(256))
        writer.write(payload)
        await writer.drain()
        self.assertEqual(await reader.readexactly(len(payload)), payload)
        writer.close()
        await writer.wait_closed()
        self.assertEqual(bytes(self.observed[0]['data']), payload)
        self.assertEqual(self.observed[0]['host'], b'example.com')

    async def test_http_origin_form_and_authentication_stripping(self):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        writer.write(b'GET http://example.com/a?b=1 HTTP/1.1\r\nHost: example.com\r\nProxy-Authorization: Basic SECRET\r\n\r\n')
        await writer.drain()
        self.assertTrue((await reader.read()).endswith(b'OK'))
        data = bytes(self.observed[0]['data'])
        self.assertTrue(data.startswith(b'GET /a?b=1 HTTP/1.1\r\n'))
        self.assertNotIn(b'SECRET', data)
        writer.close()
        await writer.wait_closed()

    async def test_chunked_post_preserves_framing(self):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        writer.write(b'POST http://example.com/upload HTTP/1.1\r\nHost: example.com\r\nTransfer-Encoding: chunked\r\n\r\n4\r\nDATA\r\n0\r\n\r\n')
        await writer.drain()
        self.assertTrue((await reader.read()).endswith(b'OK'))
        self.assertTrue(bytes(self.observed[0]['data']).endswith(b'4\r\nDATA\r\n0\r\n\r\n'))
        writer.close()
        await writer.wait_closed()

    async def test_bad_request_rejected_before_node_connection(self):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        writer.write(b'BAD\r\n\r\n')
        await writer.drain()
        self.assertIn(b'400 Bad Request', await reader.read())
        self.assertEqual(self.observed, [])
        writer.close()
        await writer.wait_closed()
