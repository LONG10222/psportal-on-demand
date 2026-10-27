"""Datagram helpers for Python 3.10 OpenWrt and newer event loops."""
import asyncio


async def _ready(loop, descriptor, write=False):
    future = loop.create_future()
    def wake():
        if not future.done():
            future.set_result(None)
    add = loop.add_writer if write else loop.add_reader
    remove = loop.remove_writer if write else loop.remove_reader
    add(descriptor, wake)
    try:
        await future
    finally:
        remove(descriptor)


async def _recvfrom_compat(loop, sock, size):
    while True:
        try:
            return sock.recvfrom(size)
        except (BlockingIOError, InterruptedError):
            await _ready(loop, sock.fileno())


async def _sendto_compat(loop, sock, data, address):
    while True:
        try:
            return sock.sendto(data, address)
        except (BlockingIOError, InterruptedError):
            await _ready(loop, sock.fileno(), write=True)


async def recvfrom(sock, size):
    loop = asyncio.get_running_loop()
    native = getattr(loop, 'sock_recvfrom', None)
    if native is not None:
        return await native(sock, size)
    return await _recvfrom_compat(loop, sock, size)


async def sendto(sock, data, address):
    loop = asyncio.get_running_loop()
    native = getattr(loop, 'sock_sendto', None)
    if native is not None:
        return await native(sock, data, address)
    return await _sendto_compat(loop, sock, data, address)
