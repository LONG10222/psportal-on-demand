"""Expose framed native TCP as a byte stream to the StarPass HTTP frontend."""
import asyncio
import ipaddress
import struct

from xianniu_router.protocol import MAX_FRAME, frame


class NativeReader:
    def __init__(self, reader, counters):
        self.reader, self.counters = reader, counters
        self.pending = bytearray()

    async def read(self, count=65536):
        if count <= 0:
            return b''
        if not self.pending:
            try:
                header = await self.reader.readexactly(4)
            except asyncio.IncompleteReadError as exc:
                if exc.partial:
                    raise ValueError('Truncated native frame') from None
                return b''
            size, = struct.unpack('<I', header)
            if not 0 < size <= MAX_FRAME:
                raise ValueError('Invalid native frame length')
            try:
                payload = await self.reader.readexactly(size)
            except asyncio.IncompleteReadError:
                raise ValueError('Truncated native frame body') from None
            self.counters['received'] += len(payload)
            self.pending.extend(payload)
        data = bytes(self.pending[:count])
        del self.pending[:count]
        return data


class NativeWriter:
    def __init__(self, writer, counters):
        self.writer, self.counters = writer, counters

    def write(self, data):
        for offset in range(0, len(data), 65536):
            payload = data[offset:offset + 65536]
            self.writer.write(frame(payload))
            self.counters['sent'] += len(payload)

    async def drain(self):
        await self.writer.drain()

    def can_write_eof(self):
        # The observed protocol has no verified half-close frame. Keep receiving
        # the response; the frontend's bounded timeout still applies.
        return False

    def close(self):
        self.writer.close()

    async def wait_closed(self):
        await self.writer.wait_closed()


class NativeCore:
    def __init__(self, service):
        self.service = service

    async def acquire(self):
        # Protocol-compatible placeholder; no connection to this tuple is made.
        return ('127.0.0.1', 1)

    async def release(self):
        pass

    def status(self):
        return {'engine': 'xianniu-native', 'session_mode': 'snapshot',
                'traffic_verified': False}

    async def open_connection(self, host, port):
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if address.version != 4 or not address.is_global:
                raise ValueError('Only public IPv4 destinations supported')
        try:
            reader, writer, _ = await self.service.open_native(1, host, port)
            self.service.counters['tcp_connections'] += 1
            return NativeReader(reader, self.service.counters), NativeWriter(writer, self.service.counters)
        except Exception:
            self.service.counters['tcp_errors'] += 1
            raise
