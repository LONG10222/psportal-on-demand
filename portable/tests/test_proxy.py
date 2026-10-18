import asyncio
import contextlib
import unittest
from unittest.mock import AsyncMock, patch

from portalproxy import policy, proxy


class ParserTests(unittest.TestCase):
    def request(self, first="GET http://example.com/a?b=1 HTTP/1.1", headers="Host: example.com"):
        return proxy.parse_request((first + "\r\n" + headers + "\r\n\r\n").encode("latin-1"))

    def test_rewrites_origin_and_absolute_form(self):
        request = self.request()
        self.assertTrue(request.forwarded_header(False).startswith(b"GET /a?b=1 HTTP/1.1\r\n"))
        self.assertTrue(request.forwarded_header(True).startswith(b"GET http://example.com:80/a?b=1 HTTP/1.1\r\n"))
        self.assertIn(b"Connection: close\r\n", request.forwarded_header(True))

    def test_connect_ipv6_and_query_only(self):
        request = self.request("CONNECT [2606:4700::1111]:443 HTTP/1.1", "Host: [2606:4700::1111]:443")
        self.assertEqual((request.host, request.port), ("2606:4700::1111", 443))
        self.assertEqual(self.request("GET http://example.com?q=1 HTTP/1.1").path, "/?q=1")
        self.assertEqual(self.request("CONNECT example.com HTTP/1.0", "X-Test: ok").port, 443)

    def test_removes_proxy_credentials_and_connection_listed_fields(self):
        request = self.request(headers="Host: example.com\r\nProxy-Authorization: Basic secret\r\nProxy-Authenticate: private\r\nProxy-Connection: keep-alive\r\nConnection: keep-alive, X-Hop\r\nKeep-Alive: 100\r\nX-Hop: private\r\nTE: trailers\r\nAuthorization: Bearer origin\r\nX-End: yes")
        for external in (False, True):
            forwarded = request.forwarded_header(external)
            for denied in (b"secret", b"private", b"keep-alive", b"trailers", b"X-Hop", b"Proxy-"):
                self.assertNotIn(denied, forwarded)
            self.assertIn(b"Authorization: Bearer origin", forwarded)
            self.assertIn(b"X-End: yes", forwarded)

    def test_rejects_smuggling_and_malformed_headers(self):
        invalid_headers = [
            "Host: example.com\r\nContent-Length: 0\r\nTransfer-Encoding: chunked",
            "Host: example.com\r\nContent-Length: 1\r\nContent-Length: 1",
            "Host: example.com\r\nContent-Length: 1, 1",
            "Host: example.com\r\nContent-Length: +1",
            "Host: example.com\r\nContent-Length: -1",
            "Host: example.com\r\nTransfer-Encoding: gzip, chunked",
            "Host: example.com\r\nTransfer-Encoding: chunked\r\nTransfer-Encoding: chunked",
            "Host: example.com\r\nConnection: content-length",
            "Host: example.com\r\nConnection: Host",
            "Host: example.com\r\nConnection: x,,y",
            "Host: example.com\r\nX-Test : yes",
            "Host: example.com\r\n X-Test: folded",
            "Host: example.com\r\nX-Test: a\nb",
            "Host: example.com\r\nX-Test: a\rb",
            "Host: example.com\r\nX-Test: a\x00b",
            "Host: example.com\r\nX-Test: a\x7fb",
            "Host: example.com\r\nHost: example.com",
            "Host: other.example",
            "Host: example.com:443",
            "Host: example.com\r\nUpgrade: websocket",
            "X-Test: missing host",
        ]
        for headers in invalid_headers:
            with self.subTest(headers=headers):
                with self.assertRaises(proxy.ProtocolError):
                    self.request(headers=headers)

    def test_rejects_ambiguous_authorities_and_unsupported_targets(self):
        for first in ("GET / HTTP/1.1", "GET https://example.com/ HTTP/1.1", "GET http://u:p@example.com/ HTTP/1.1",
                      "GET http://example.com/a#f HTTP/1.1", "GET http://example.com\\evil/ HTTP/1.1",
                      "GET http://example.com:0/ HTTP/1.1", "GET http://example.com:65536/ HTTP/1.1",
                      "GET http://example.com:/ HTTP/1.1", "GET http://127.1/ HTTP/1.1",
                      "GET http://0x7f000001/ HTTP/1.1", "GET http://01.2.3.4/ HTTP/1.1",
                      "CONNECT [fe80::1%eth0]:443 HTTP/1.1", "GET  http://example.com/ HTTP/1.1",
                      "GET\thttp://example.com/ HTTP/1.1", "GET http://example.com/ HTTP/2"):
            with self.subTest(first=first):
                with self.assertRaises(proxy.ProtocolError):
                    self.request(first)

    def test_connect_body_and_expectation_rejected(self):
        with self.assertRaises(proxy.ProtocolError):
            self.request("CONNECT example.com:443 HTTP/1.1", "Host: example.com:443\r\nContent-Length: 1")
        with self.assertRaises(proxy.ProtocolError) as caught:
            self.request(headers="Host: example.com\r\nExpect: something")
        self.assertEqual(caught.exception.status, 417)

    def test_limits(self):
        with self.assertRaises(proxy.ProtocolError) as caught:
            self.request(headers="Host: example.com\r\nX-Test: " + "a" * proxy.MAX_LINE_BYTES)
        self.assertEqual(caught.exception.status, 431)
        with self.assertRaises(proxy.ProtocolError):
            self.request(headers="Host: example.com\r\n" + "X: y\r\n" * 101)


class FakeCore:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.active = 0
        self.acquisitions = 0
        self.releases = 0

    async def acquire(self):
        self.active += 1
        self.acquisitions += 1
        return self.endpoint

    async def release(self):
        self.active -= 1
        self.releases += 1


class ProxyNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.servers = []
        self.proxies = []
        self.fixture_tasks = set()
        self.fixture_errors = []

    async def asyncTearDown(self):
        for server in self.proxies:
            await server.close()
        for server in self.servers:
            server.close()
            await server.wait_closed()
        tasks = list(self.fixture_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.fixture_errors:
            raise self.fixture_errors[0]

    async def fixture(self, handler):
        async def checked(reader, writer):
            try:
                await handler(reader, writer)
            except (ConnectionError, asyncio.CancelledError):
                pass
            except BaseException as exc:
                self.fixture_errors.append(exc)
            finally:
                writer.close()
                with contextlib.suppress(ConnectionError):
                    await writer.wait_closed()
        def accept(reader, writer):
            task = asyncio.create_task(checked(reader, writer))
            self.fixture_tasks.add(task)
            task.add_done_callback(self.fixture_tasks.discard)
        server = await asyncio.start_server(accept, "127.0.0.1", 0)
        self.servers.append(server)
        return server.sockets[0].getsockname()[:2]

    async def start_proxy(self, endpoint=("127.0.0.1", 1), **changes):
        config = dict(listen_host="127.0.0.1", listen_port=0, allowed_clients=["127.0.0.1"], request_timeout=1, max_connections=128)
        config.update(changes)
        core = FakeCore(endpoint)
        server = proxy.ProxyServer(config, core)
        await server.start()
        self.proxies.append(server)
        return server, core

    async def connect(self, server):
        return await asyncio.open_connection(*server.bound_addresses[0][:2])

    async def exchange(self, server, data):
        reader, writer = await self.connect(server)
        try:
            writer.write(data)
            await writer.drain()
            chunks = []
            try:
                while True:
                    chunk = await asyncio.wait_for(reader.read(65536), 3)
                    if not chunk:
                        break
                    chunks.append(chunk)
            except ConnectionResetError:
                # Immediate source denial can reset a socket with unread input.
                # The HTTP rejection must still have been received.
                if not chunks:
                    raise
            return b"".join(chunks)
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    async def settle(self, core):
        for _ in range(100):
            if core.active == 0:
                return
            await asyncio.sleep(.005)
        self.fail("core reference not released")

    async def test_external_http_streams_body_and_releases_core(self):
        captured = []
        async def backend(reader, writer):
            captured.append(await reader.readuntil(b"\r\n\r\n"))
            captured.append(await reader.readexactly(5))
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
            await writer.drain()
        endpoint = await self.fixture(backend)
        server, core = await self.start_proxy(endpoint)
        result = await self.exchange(server, b"POST http://8.8.8.8/upload HTTP/1.1\r\nHost: 8.8.8.8\r\nContent-Length: 5\r\nProxy-Authorization: hidden\r\n\r\nhello")
        self.assertTrue(result.endswith(b"OK"))
        self.assertTrue(captured[0].startswith(b"POST http://8.8.8.8:80/upload HTTP/1.1\r\n"))
        self.assertNotIn(b"hidden", captured[0])
        self.assertEqual(captured[1], b"hello")
        await self.settle(core)
        self.assertEqual((core.acquisitions, core.releases), (1, 1))

    async def test_external_connect_tunnel_and_half_close(self):
        captured = []
        async def backend(reader, writer):
            captured.append(await reader.readuntil(b"\r\n\r\n"))
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            body = await reader.read()
            writer.write(b"echo:" + body)
            await writer.drain()
        server, core = await self.start_proxy(await self.fixture(backend))
        reader, writer = await self.connect(server)
        writer.write(b"CONNECT 8.8.8.8:443 HTTP/1.1\r\nHost: 8.8.8.8:443\r\nProxy-Authorization: hidden\r\n\r\nhello")
        await writer.drain()
        self.assertIn(b"200", await reader.readuntil(b"\r\n\r\n"))
        self.assertEqual(core.active, 1)
        writer.write_eof()
        self.assertEqual(await asyncio.wait_for(reader.read(), 3), b"echo:hello")
        writer.close()
        await writer.wait_closed()
        self.assertNotIn(b"hidden", captured[0])
        await self.settle(core)
        self.assertEqual(core.releases, 1)

    async def test_lan_route_is_numeric_origin_form_without_core(self):
        captured = []
        async def origin(reader, writer):
            captured.append(await reader.readuntil(b"\r\n\r\n"))
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
        endpoint = await self.fixture(origin)
        server, core = await self.start_proxy()
        # Test-only resolver substitution permits an actual loopback fixture.
        # Production resolver continues to deny every loopback destination.
        with patch.object(proxy, "resolve_destination", AsyncMock(return_value=policy.Route("local", endpoint[0]))) as resolve:
            result = await self.exchange(server, f"GET http://printer.lan:{endpoint[1]}/status HTTP/1.1\r\nHost: printer.lan:{endpoint[1]}\r\n\r\n".encode())
        self.assertIn(b"200 OK", result)
        resolve.assert_awaited_once_with("printer.lan", endpoint[1])
        self.assertTrue(captured[0].startswith(b"GET /status HTTP/1.1\r\n"))
        self.assertEqual(core.acquisitions, 0)

    async def test_loopback_metadata_and_localhost_rejected_before_core(self):
        server, core = await self.start_proxy()
        for target in ("127.0.0.1", "169.254.169.254", "localhost", "foo.localhost", "100.64.0.1", "[::1]"):
            for connect in (False, True):
                with self.subTest(target=target, connect=connect):
                    first = f"CONNECT {target}:80" if connect else f"GET http://{target}/"
                    host = f"{target}:80" if connect else target
                    result = await self.exchange(server, f"{first} HTTP/1.1\r\nHost: {host}\r\n\r\n".encode())
                    self.assertIn(b"403 Forbidden", result)
        self.assertEqual(core.acquisitions, 0)

    async def test_dns_denial_and_errors_do_not_wake_core(self):
        server, core = await self.start_proxy()
        for error, expected in ((policy.DestinationDenied("denied"), b"403"), (policy.ResolutionFailed("NXDOMAIN"), b"502")):
            with patch.object(proxy, "resolve_destination", AsyncMock(side_effect=error)):
                result = await self.exchange(server, b"GET http://fixture.example/ HTTP/1.1\r\nHost: fixture.example\r\n\r\n")
            self.assertIn(expected, result)
        self.assertEqual(core.acquisitions, 0)

    async def test_denied_client_and_connection_limit(self):
        server, core = await self.start_proxy(allowed_clients=["192.168.1.55"])
        result = await self.exchange(server, b"GET http://8.8.8.8/ HTTP/1.1\r\nHost: 8.8.8.8\r\n\r\n")
        self.assertIn(b"403 Forbidden", result)
        self.assertEqual(core.acquisitions, 0)
        server, core = await self.start_proxy(max_connections=1)
        reader, writer = await self.connect(server)
        writer.write(b"GET ")
        await writer.drain()
        result = await self.exchange(server, b"GET http://8.8.8.8/ HTTP/1.1\r\nHost: 8.8.8.8\r\n\r\n")
        self.assertIn(b"503 Service Unavailable", result)
        writer.close()
        await writer.wait_closed()

    async def test_chunked_body_normalization_and_trailer_removal(self):
        captured = []
        async def backend(reader, writer):
            captured.append(await reader.readuntil(b"\r\n\r\n"))
            captured.append(await reader.readuntil(b"0\r\n\r\n"))
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
        server, core = await self.start_proxy(await self.fixture(backend))
        result = await self.exchange(server, b"POST http://8.8.8.8/ HTTP/1.1\r\nHost: 8.8.8.8\r\nTransfer-Encoding: chunked\r\nTrailer: X-Trailer\r\n\r\n0005\r\nhello\r\n0\r\nX-Trailer: discard\r\nProxy-Authorization: secret\r\n\r\n")
        self.assertIn(b"200 OK", result)
        self.assertNotIn(b"Trailer:", captured[0])
        self.assertEqual(captured[1], b"5\r\nhello\r\n0\r\n\r\n")
        await self.settle(core)

    async def test_pipelined_second_request_is_not_forwarded(self):
        captured = []
        async def backend(reader, writer):
            captured.append(await reader.readuntil(b"\r\n\r\n"))
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(reader.read(1), .05)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
        server, core = await self.start_proxy(await self.fixture(backend))
        result = await self.exchange(server, b"GET http://8.8.8.8/ HTTP/1.1\r\nHost: 8.8.8.8\r\n\r\nGET http://127.0.0.1/ HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        self.assertIn(b"200 OK", result)
        self.assertNotIn(b"127.0.0.1", captured[0])
        await self.settle(core)
        self.assertEqual(core.acquisitions, 1)

    async def test_expect_continue_and_malformed_body(self):
        async def backend(reader, writer):
            header = await reader.readuntil(b"\r\n\r\n")
            self.assertNotIn(b"Expect:", header)
            self.assertEqual(await reader.readexactly(5), b"hello")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
        server, core = await self.start_proxy(await self.fixture(backend))
        reader, writer = await self.connect(server)
        writer.write(b"POST http://8.8.8.8/ HTTP/1.1\r\nHost: 8.8.8.8\r\nContent-Length: 5\r\nExpect: 100-continue\r\n\r\n")
        await writer.drain()
        self.assertEqual(await reader.readuntil(b"\r\n\r\n"), b"HTTP/1.1 100 Continue\r\n\r\n")
        writer.write(b"hello")
        await writer.drain()
        self.assertIn(b"200 OK", await reader.read())
        writer.close()
        await writer.wait_closed()
        await self.settle(core)

    async def test_failed_backend_connect_releases_core(self):
        async def backend(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
            await writer.drain()
        server, core = await self.start_proxy(await self.fixture(backend))
        result = await self.exchange(server, b"CONNECT 8.8.8.8:443 HTTP/1.1\r\nHost: 8.8.8.8:443\r\n\r\n")
        self.assertIn(b"502 Bad Gateway", result)
        await self.settle(core)
        self.assertEqual(core.releases, 1)

    async def test_shutdown_cancels_tunnels_and_releases_core(self):
        async def backend(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\n\r\n")
            await writer.drain()
            await reader.read()
        server, core = await self.start_proxy(await self.fixture(backend))
        reader, writer = await self.connect(server)
        writer.write(b"CONNECT 8.8.8.8:443 HTTP/1.1\r\nHost: 8.8.8.8:443\r\n\r\n")
        await writer.drain()
        await reader.readuntil(b"\r\n\r\n")
        self.assertEqual(core.active, 1)
        await server.close()
        self.assertEqual(core.active, 0)
        self.assertEqual(core.releases, 1)
        self.assertEqual(server.stats["active"], 0)
        writer.close()
        await writer.wait_closed()

    async def test_startup_failure_has_no_leaked_reference(self):
        server, core = await self.start_proxy()
        with patch.object(core, "acquire", AsyncMock(side_effect=RuntimeError("startup failed"))):
            result = await self.exchange(server, b"GET http://8.8.8.8/ HTTP/1.1\r\nHost: 8.8.8.8\r\n\r\n")
        self.assertIn(b"502 Bad Gateway", result)
        self.assertEqual((core.active, core.releases), (0, 0))

    async def test_mixed_denied_dns_cannot_start_backend(self):
        import socket
        server, core = await self.start_proxy()
        answers = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 80))
                   for address in ("8.8.8.8", "127.0.0.1")]
        with patch.object(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=answers)):
            result = await self.exchange(server, b"GET http://mixed.example/ HTTP/1.1\r\nHost: mixed.example\r\n\r\n")
        self.assertIn(b"403 Forbidden", result)
        self.assertEqual(core.acquisitions, 0)

    async def test_bind_conflict_is_reported(self):
        server, _core = await self.start_proxy()
        duplicate = proxy.ProxyServer(dict(server.config, listen_port=server.bound_addresses[0][1]), FakeCore(("127.0.0.1", 1)))
        with self.assertRaises(OSError):
            await duplicate.start()
        await duplicate.close()

    async def test_malformed_chunk_releases_core_without_forwarding_extra_request(self):
        async def backend(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            self.assertEqual(await reader.read(), b"")
        server, core = await self.start_proxy(await self.fixture(backend))
        result = await self.exchange(server, b"POST http://8.8.8.8/ HTTP/1.1\r\nHost: 8.8.8.8\r\nTransfer-Encoding: chunked\r\n\r\n5;ext=unsupported\r\nhello\r\n0\r\n\r\n")
        self.assertIn(b"400 Bad Request", result)
        await self.settle(core)
        self.assertEqual(core.releases, 1)

    async def test_truncated_content_length_fails_and_releases_core(self):
        async def backend(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            await reader.read()
        server, core = await self.start_proxy(await self.fixture(backend))
        reader, writer = await self.connect(server)
        writer.write(b"POST http://8.8.8.8/ HTTP/1.1\r\nHost: 8.8.8.8\r\nContent-Length: 5\r\n\r\nhi")
        await writer.drain()
        writer.write_eof()
        self.assertIn(b"400 Bad Request", await asyncio.wait_for(reader.read(), 3))
        writer.close()
        await writer.wait_closed()
        await self.settle(core)
        self.assertEqual(core.releases, 1)

    async def test_direct_connect_uses_only_injected_numeric_destination(self):
        async def origin(reader, writer):
            writer.write(await reader.readexactly(4))
            await writer.drain()
        endpoint = await self.fixture(origin)
        server, core = await self.start_proxy()
        with patch.object(proxy, "resolve_destination", AsyncMock(return_value=policy.Route("local", endpoint[0]))):
            reader, writer = await self.connect(server)
            writer.write(f"CONNECT printer.lan:{endpoint[1]} HTTP/1.1\r\nHost: printer.lan:{endpoint[1]}\r\n\r\nping".encode())
            await writer.drain()
            self.assertIn(b"200 Connection Established", await reader.readuntil(b"\r\n\r\n"))
            self.assertEqual(await reader.read(), b"ping")
            writer.close()
            await writer.wait_closed()
        self.assertEqual(core.acquisitions, 0)

    async def test_headers_timeout_does_not_start_core(self):
        server, core = await self.start_proxy(request_timeout=.05)
        reader, writer = await self.connect(server)
        self.assertIn(b"504 Gateway Timeout", await asyncio.wait_for(reader.read(), 1))
        writer.close()
        await writer.wait_closed()
        self.assertEqual(core.acquisitions, 0)


if __name__ == "__main__":
    unittest.main()
