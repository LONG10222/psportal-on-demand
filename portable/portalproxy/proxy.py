"""Small explicit HTTP/1 proxy with strict framing and an exact client allowlist.

One HTTP request is served per client connection. CONNECT is a byte tunnel.
The core is acquired only for external traffic and released after the entire
connection ends. No destination-policy exceptions exist for test fixtures.
"""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import re
import time
from dataclasses import dataclass
from typing import Any

from .policy import (DestinationDenied, ResolutionFailed, Route, ipv4, ipv6,
                     normalize_host, resolve_destination, valid_name)

MAX_HEADER_BYTES = 65536
MAX_HEADER_COUNT = 100
MAX_LINE_BYTES = 8192
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z", re.ASCII)
_REQUEST_LINE = re.compile(r"([A-Z]{1,32}) ([!-~]+) (HTTP/1\.[01])\Z", re.ASCII)
_HOP_HEADERS = {
    "connection", "proxy-connection", "proxy-authorization", "proxy-authenticate",
    "keep-alive", "te", "trailer", "transfer-encoding", "upgrade",
}
_REASONS = {400: "Bad Request", 403: "Forbidden", 408: "Request Timeout",
            413: "Content Too Large", 417: "Expectation Failed", 431: "Request Header Fields Too Large",
            502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout"}


class ProtocolError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Request:
    method: str
    host: str
    port: int
    path: str
    version: str
    headers: tuple[tuple[str, str], ...]
    content_length: int | None = None
    chunked: bool = False
    expect_continue: bool = False
    connection_headers: frozenset[str] = frozenset()

    @property
    def authority(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"

    def forwarded_header(self, external: bool) -> bytes:
        if self.method == "CONNECT":
            target = self.authority
        elif external:
            target = f"http://{self.authority}{self.path}"
        else:
            target = self.path
        lines = [f"{self.method} {target} {self.version}", f"Host: {self.authority}"]
        strip = _HOP_HEADERS | self.connection_headers | {"host", "content-length", "expect"}
        for name, value in self.headers:
            if name.lower() not in strip:
                lines.append(f"{name}: {value}")
        if self.chunked:
            lines.append("Transfer-Encoding: chunked")
        elif self.content_length is not None:
            lines.append(f"Content-Length: {self.content_length}")
        if self.method != "CONNECT":
            lines.append("Connection: close")
        return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")


def parse_authority(authority: str, default_port: int) -> tuple[str, int]:
    if not authority or any(c in authority for c in "@/?#\\%"):
        raise ProtocolError("invalid authority")
    if authority.startswith("["):
        match = re.fullmatch(r"\[([^\]]+)\](?::([0-9]{1,5}))?", authority, re.ASCII)
        if not match or not ipv6(match.group(1)):
            raise ProtocolError("invalid IPv6 authority")
        host, raw_port = match.groups()
    else:
        match = re.fullmatch(r"([^:\[\]]+)(?::([0-9]{1,5}))?", authority, re.ASCII)
        if not match:
            raise ProtocolError("invalid authority")
        host, raw_port = match.groups()
        host = normalize_host(host)
        if not ipv4(host) and not valid_name(host):
            raise ProtocolError("invalid host")
    host = normalize_host(host)
    port = int(raw_port) if raw_port is not None else default_port
    if not 1 <= port <= 65535:
        raise ProtocolError("invalid port")
    return host, port


def _header_lines(data: bytes) -> list[str]:
    if len(data) > MAX_HEADER_BYTES:
        raise ProtocolError("headers too large", 431)
    if not data.endswith(b"\r\n\r\n"):
        raise ProtocolError("incomplete headers")
    lines = data[:-4].split(b"\r\n")
    if len(lines) > MAX_HEADER_COUNT + 1:
        raise ProtocolError("too many headers", 431)
    for line in lines:
        if len(line) > MAX_LINE_BYTES:
            raise ProtocolError("header line too long", 431)
        if any(c < 32 and c != 9 or c == 127 for c in line):
            raise ProtocolError("invalid header control character")
    return [line.decode("latin-1") for line in lines]


def _parse_fields(lines: list[str]) -> tuple[tuple[str, str], ...]:
    fields = []
    for line in lines:
        if not line or line[0] in " \t" or ":" not in line:
            raise ProtocolError("invalid or folded header")
        name, value = line.split(":", 1)
        if not _TOKEN.fullmatch(name):
            raise ProtocolError("invalid header name")
        fields.append((name, value.strip(" \t")))
    return tuple(fields)


def parse_request(data: bytes) -> Request:
    lines = _header_lines(data)
    match = _REQUEST_LINE.fullmatch(lines[0]) if lines else None
    if not match:
        raise ProtocolError("invalid request line")
    method, target, version = match.groups()
    default_port = 443 if method == "CONNECT" else 80
    if "\\" in target or "#" in target:
        raise ProtocolError("invalid request target")
    if method == "CONNECT":
        host, port = parse_authority(target, default_port)
        path = ""
    else:
        match = re.fullmatch(r"http://([^/?]+)(.*)", target, re.ASCII)
        if not match:
            raise ProtocolError("absolute-form HTTP target required")
        host, port = parse_authority(match.group(1), default_port)
        path = match.group(2) or "/"
        if path.startswith("?"):
            path = "/" + path
    fields = _parse_fields(lines[1:])
    values: dict[str, list[str]] = {}
    for name, value in fields:
        values.setdefault(name.lower(), []).append(value)
    hosts = values.get("host", [])
    if len(hosts) > 1 or (version == "HTTP/1.1" and not hosts):
        raise ProtocolError("exactly one Host is required")
    if hosts and parse_authority(hosts[0], default_port) != (host, port):
        raise ProtocolError("Host disagrees with request target")
    lengths = values.get("content-length", [])
    encodings = values.get("transfer-encoding", [])
    if len(lengths) > 1 or len(encodings) > 1 or (lengths and encodings):
        raise ProtocolError("ambiguous body framing")
    length = None
    if lengths:
        if not re.fullmatch(r"[0-9]{1,19}", lengths[0], re.ASCII):
            raise ProtocolError("invalid Content-Length")
        length = int(lengths[0])
    chunked = bool(encodings)
    if encodings and (encodings[0].lower() != "chunked" or version != "HTTP/1.1"):
        raise ProtocolError("unsupported Transfer-Encoding")
    if method == "CONNECT" and (chunked or length not in (None, 0)):
        raise ProtocolError("CONNECT cannot carry a framed request body")
    if "upgrade" in values:
        raise ProtocolError("HTTP upgrade is unsupported; use CONNECT")
    connection = set()
    for value in values.get("connection", []) + values.get("proxy-connection", []):
        for token in value.split(","):
            token = token.strip().lower()
            if not token or not _TOKEN.fullmatch(token):
                raise ProtocolError("invalid Connection token")
            if token in {"host", "content-length", "transfer-encoding"}:
                raise ProtocolError("Connection cannot remove framing headers")
            connection.add(token)
    expects = values.get("expect", [])
    if expects and (len(expects) != 1 or expects[0].lower() != "100-continue" or method == "CONNECT"):
        raise ProtocolError("unsupported expectation", 417)
    return Request(method, host, port, path, version, fields, length, chunked,
                   bool(expects), frozenset(connection))


async def _close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(writer.wait_closed(), 1)


class ProxyServer:
    def __init__(self, config: dict[str, Any], core: Any):
        self.config, self.core = config, core
        self.timeout = float(config.get("request_timeout", 30))
        self.max_connections = int(config.get("max_connections", 128))
        if self.timeout <= 0 or self.max_connections < 1:
            raise ValueError("request_timeout and max_connections must be positive")
        self.allowed_clients = frozenset(ipaddress.ip_address(ip) for ip in config["allowed_clients"])
        if not self.allowed_clients:
            raise ValueError("allowed_clients must not be empty")
        self._server: asyncio.Server | None = None
        self._tasks: set[asyncio.Task] = set()
        self._closing = False
        self.stats = {"accepted": 0, "denied_clients": 0, "local_requests": 0,
                      "external_requests": 0, "errors": 0, "active": 0}
        self.clients = {}

    def snapshot(self):
        """Only clients that actually reached this listener, never a Wi-Fi scan."""
        now = time.time()
        self.clients = {ip: row for ip, row in self.clients.items()
                        if row['active'] or now - row['last_seen'] <= 300}
        rows = [dict(ip=ip, **row) for ip, row in self.clients.items()]
        rows.sort(key=lambda row: (-bool(row['active']), -row['last_seen'], row['ip']))
        return dict(kind='statistics', **self.stats,
                    devices=sum(row['active'] > 0 for row in rows), clients=rows[:256],
                    truncated=len(rows) > 256)

    @property
    def bound_addresses(self) -> list[tuple]:
        return [sock.getsockname() for sock in self._server.sockets] if self._server else []

    async def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("proxy is already started")
        self._closing = False
        self._server = await asyncio.start_server(self._accept, self.config["listen_host"],
                                                  self.config["listen_port"], limit=MAX_HEADER_BYTES)

    async def close(self) -> None:
        self._closing = True
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _error(self, writer: asyncio.StreamWriter, status: int) -> None:
        reason = _REASONS[status]
        body = (reason + "\n").encode("ascii")
        writer.write((f"HTTP/1.1 {status} {reason}\r\nConnection: close\r\n"
                      f"Content-Type: text/plain\r\nContent-Length: {len(body)}\r\n\r\n").encode("ascii") + body)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(writer.drain(), self.timeout)

    def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(self._handle(reader, writer))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _header(self, reader: asyncio.StreamReader) -> bytes:
        try:
            return await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), self.timeout)
        except asyncio.LimitOverrunError as exc:
            raise ProtocolError("headers too large", 431) from exc
        except asyncio.IncompleteReadError as exc:
            raise ProtocolError("incomplete headers") from exc

    async def _drain(self, writer: asyncio.StreamWriter) -> None:
        await asyncio.wait_for(writer.drain(), self.timeout)

    async def _read_exactly(self, reader: asyncio.StreamReader, length: int) -> bytes:
        try:
            return await asyncio.wait_for(reader.readexactly(length), self.timeout)
        except asyncio.IncompleteReadError as exc:
            raise ProtocolError("incomplete request body") from exc

    async def _body(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, request: Request) -> None:
        if request.chunked:
            while True:
                try:
                    line = await asyncio.wait_for(reader.readuntil(b"\r\n"), self.timeout)
                except (asyncio.LimitOverrunError, asyncio.IncompleteReadError) as exc:
                    raise ProtocolError("invalid chunk header") from exc
                # Chunk extensions are intentionally unsupported, preventing
                # divergent upstream interpretations of quoted/escaped syntax.
                if not re.fullmatch(rb"[0-9a-fA-F]{1,16}\r\n", line):
                    raise ProtocolError("invalid chunk size")
                size = int(line[:-2], 16)
                if size == 0:
                    # Validate and discard trailers; never let trailers inject
                    # authentication, routing or framing into the next hop.
                    total = 0
                    for _ in range(MAX_HEADER_COUNT + 1):
                        try:
                            trailer = await asyncio.wait_for(reader.readuntil(b"\r\n"), self.timeout)
                        except (asyncio.LimitOverrunError, asyncio.IncompleteReadError) as exc:
                            raise ProtocolError("invalid trailers") from exc
                        total += len(trailer)
                        if total > MAX_HEADER_BYTES or len(trailer) > MAX_LINE_BYTES:
                            raise ProtocolError("trailers too large", 431)
                        if trailer == b"\r\n":
                            writer.write(b"0\r\n\r\n")
                            await self._drain(writer)
                            return
                        _parse_fields(_header_lines(b"TRAILERS\r\n" + trailer + b"\r\n")[1:])
                    raise ProtocolError("too many trailers", 431)
                writer.write(f"{size:x}\r\n".encode("ascii"))
                await self._copy_exactly(reader, writer, size)
                if await self._read_exactly(reader, 2) != b"\r\n":
                    raise ProtocolError("invalid chunk terminator")
                writer.write(b"\r\n")
                await self._drain(writer)
        elif request.content_length:
            await self._copy_exactly(reader, writer, request.content_length)

    async def _copy_exactly(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, length: int) -> None:
        while length:
            data = await self._read_exactly(reader, min(length, 65536))
            length -= len(data)
            writer.write(data)
            await self._drain(writer)

    async def _pump(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, state: dict | None = None) -> None:
        while True:
            data = await asyncio.wait_for(reader.read(65536), self.timeout)
            if not data:
                if writer.can_write_eof():
                    with contextlib.suppress(OSError):
                        writer.write_eof()
                return
            if state is not None:
                state["responded"] = True
            writer.write(data)
            await self._drain(writer)

    async def _duplex(self, outgoing, incoming) -> None:
        """Preserve response after client half-close, close on upstream EOF."""
        send, receive = asyncio.create_task(outgoing), asyncio.create_task(incoming)
        try:
            done, _ = await asyncio.wait((send, receive), return_when=asyncio.FIRST_COMPLETED)
            if receive in done:
                await receive
                if send in done:
                    await send
            else:
                await send
                await receive
        finally:
            for task in (send, receive):
                if not task.done():
                    task.cancel()
            await asyncio.gather(send, receive, return_exceptions=True)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        upstream_writer = None
        acquired = False
        counted = False
        client = None
        state = {"responded": False}
        try:
            peer = writer.get_extra_info("peername")
            try:
                allowed = bool(peer) and ipaddress.ip_address(peer[0]) in self.allowed_clients
            except ValueError:
                allowed = False
            if not allowed:
                self.stats["denied_clients"] += 1
                await self._error(writer, 403)
                return
            if self._closing or self.stats["active"] >= self.max_connections:
                await self._error(writer, 503)
                return
            counted = True
            self.stats["active"] += 1
            self.stats["accepted"] += 1
            client = self.clients.setdefault(str(ipaddress.ip_address(peer[0])),
                dict(active=0, requests=0, last_seen=0))
            client['active'] += 1
            client['requests'] += 1
            client['last_seen'] = time.time()
            request = parse_request(await self._header(reader))
            route = await asyncio.wait_for(resolve_destination(request.host, request.port), self.timeout)
            if route.kind == "external":
                endpoint = await self.core.acquire()
                acquired = True
                self.stats["external_requests"] += 1
                host, port = endpoint
            elif route.kind == "local" and route.address is not None:
                host, port = route.address, request.port
                self.stats["local_requests"] += 1
            else:
                raise DestinationDenied("invalid route")
            upstream_reader, upstream_writer = await asyncio.wait_for(
                asyncio.open_connection(host, port, limit=MAX_HEADER_BYTES), self.timeout)
            if request.method == "CONNECT":
                if route.kind == "external":
                    upstream_writer.write(request.forwarded_header(True))
                    await self._drain(upstream_writer)
                    try:
                        response = await self._header(upstream_reader)
                        response_lines = _header_lines(response)
                        status_match = re.fullmatch(r"HTTP/1\.[01] ([0-9]{3})(?: [\x20-\x7e]*)?", response_lines[0])
                        _parse_fields(response_lines[1:])
                        if not status_match or not 200 <= int(status_match.group(1)) < 300:
                            raise ProtocolError("backend CONNECT failed")
                    except ProtocolError as exc:
                        raise ProtocolError("backend CONNECT failed", 502) from exc
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                state["responded"] = True
                await self._drain(writer)
                await self._duplex(self._pump(reader, upstream_writer), self._pump(upstream_reader, writer))
            else:
                upstream_writer.write(request.forwarded_header(route.kind == "external"))
                await self._drain(upstream_writer)
                if request.expect_continue:
                    writer.write(b"HTTP/1.1 100 Continue\r\n\r\n")
                    await self._drain(writer)
                await self._duplex(self._body(reader, upstream_writer, request),
                                   self._pump(upstream_reader, writer, state))
        except DestinationDenied:
            self.stats["errors"] += 1
            if not state["responded"]:
                await self._error(writer, 403)
        except ResolutionFailed:
            self.stats["errors"] += 1
            if not state["responded"]:
                await self._error(writer, 502)
        except ProtocolError as exc:
            self.stats["errors"] += 1
            if not state["responded"]:
                await self._error(writer, exc.status)
        except asyncio.TimeoutError:
            self.stats["errors"] += 1
            if not state["responded"]:
                await self._error(writer, 504)
        except (OSError, RuntimeError, ValueError):
            self.stats["errors"] += 1
            if not state["responded"]:
                await self._error(writer, 502)
        finally:
            if upstream_writer is not None:
                await _close_writer(upstream_writer)
            try:
                if acquired:
                    await self.core.release()
            finally:
                if counted:
                    self.stats["active"] -= 1
                    client['active'] -= 1
                    client['last_seen'] = time.time()
                await _close_writer(writer)
