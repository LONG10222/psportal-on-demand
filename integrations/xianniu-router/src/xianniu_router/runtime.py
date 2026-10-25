"""Bounded IPv4 native relay, with local SOCKS5 and Linux transparent listeners."""
import asyncio
import contextlib
import ipaddress
import json
import os
import signal
import socket
import struct
import time
from pathlib import Path

from .control import refresh, start_session, stop_session, APIError
from .dns import AddressBook
from .protocol import build_request, frame, read_frame
from .async_socket import recvfrom, sendto

IP_TRANSPARENT = 19
IP_RECVORIGDSTADDR = 20


async def close_writer(writer):
    writer.close()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(writer.wait_closed(), 2)


async def race(*coroutines):
    tasks = [asyncio.create_task(c) for c in coroutines]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class NativeUDP:
    def __init__(self, service, callback):
        self.service, self.callback = service, callback
        self.control = None
        self.sock = None
        self.tasks = []
        self.last_used = time.monotonic()
        self.closed = False

    async def open(self):
        reader, self.control, reply = await self.service.open_native(4, b'', 1)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        try:
            await asyncio.get_running_loop().sock_connect(
                self.sock, (self.service.config['node']['host'], int.from_bytes(reply[2:4], 'little')))
        except BaseException:
            await self.close()
            raise
        self.tasks = [asyncio.create_task(self.receive()), asyncio.create_task(self.watch(reader))]
        return self

    async def watch(self, reader):
        try:
            while not self.closed:
                try:
                    data = await asyncio.wait_for(reader.read(4096), 15)
                    if not data:
                        # Observed node closes the command-4 TCP exchange after
                        # its eight-byte success reply. The UDP lease remains
                        # usable; TCP EOF is not association termination here.
                        await close_writer(self.control)
                        self.control = None
                        while not self.closed and time.monotonic() - self.last_used <= 120:
                            await asyncio.sleep(15)
                        return
                except asyncio.TimeoutError:
                    if time.monotonic() - self.last_used > 120:
                        return
        finally:
            await self.close()

    async def send(self, host, port, payload):
        if self.closed or len(payload) > 65000:
            raise ValueError('UDP association unavailable')
        address = ipaddress.IPv4Address(host)
        if not address.is_global:
            raise ValueError('Native relay only accepts public destinations')
        packet = b'\xfe' + address.packed + struct.pack('!H', port) + payload
        await asyncio.get_running_loop().sock_sendall(self.sock, packet)
        self.service.counters['sent'] += len(payload)
        self.last_used = time.monotonic()

    async def receive(self):
        try:
            while True:
                packet = await asyncio.get_running_loop().sock_recv(self.sock, 65535)
                if len(packet) < 7 or packet[0] != 254:
                    continue
                host = socket.inet_ntoa(packet[1:5])
                port = struct.unpack_from('!H', packet, 5)[0]
                self.service.counters['received'] += len(packet) - 7
                self.last_used = time.monotonic()
                await self.callback(host, port, packet[7:])
        except (OSError, ValueError):
            self.service.counters['udp_errors'] += 1
        finally:
            await self.close()

    async def close(self):
        if self.closed:
            return
        self.closed = True
        for task in self.tasks:
            if task is not asyncio.current_task():
                task.cancel()
        if self.sock:
            self.sock.close()
        if self.control:
            await close_writer(self.control)


class Service:
    def __init__(self, config, status_file=None):
        self.config = config
        self.auth = dict(config['auth'])
        self.status_file = Path(status_file) if status_file else None
        self.counters = dict(sent=0, received=0, tcp_connections=0, tcp_errors=0,
                             udp_packets=0, udp_errors=0, rejected=0)
        self.book = AddressBook()
        self.servers = []
        self.tasks = set()
        self.associations = {}
        self.reply_sockets = {}
        self.udp_listener = None
        self.dns_listener = None
        self.dns_associations = {}
        self.slots = asyncio.Semaphore(128)
        self.last_refresh = None
        self.refresh_ok = False
        self.routing_active = False
        self.managed_ports = None
        self.refresh_failures = 0
        self.http_proxy = None
        self.restore_attempted = False

    async def restore_login_once(self):
        if self.restore_attempted:raise RuntimeError('Saved login was already revalidated in this service run')
        self.restore_attempted=True
        from .auth_api import restore_session
        return await asyncio.to_thread(restore_session,self.config)

    def task(self, coroutine):
        if len(self.tasks) >= 512:
            coroutine.close()
            self.counters['rejected'] += 1
            return
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        task.add_done_callback(lambda t: None if t.cancelled() else t.exception())

    async def open_native(self, command, host, port):
        node = self.config['node']
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(node['host'], int(node['port'])), 8)
        try:
            writer.write(build_request(self.auth, command, host, port))
            await writer.drain()
            reply = await asyncio.wait_for(reader.readexactly(8), 8)
            if reply[1] != 90:
                raise RuntimeError('Native node refused request')
            return reader, writer, reply
        except BaseException:
            await close_writer(writer)
            raise

    async def bridge(self, local_reader, local_writer, remote_reader, remote_writer):
        async def upload():
            while True:
                payload = await local_reader.read(16384)
                if not payload:
                    return
                remote_writer.write(frame(payload))
                await remote_writer.drain()
                self.counters['sent'] += len(payload)

        async def download():
            while True:
                payload = await read_frame(remote_reader)
                local_writer.write(payload)
                await local_writer.drain()
                self.counters['received'] += len(payload)
        await race(upload(), download())

    async def read_socks_address(self, reader, kind):
        if kind == 1:
            return socket.inet_ntoa(await reader.readexactly(4))
        if kind == 3:
            size = (await reader.readexactly(1))[0]
            if size == 0:
                raise ValueError('Empty SOCKS target')
            return (await reader.readexactly(size)).decode('ascii')
        raise ValueError('Only IPv4 and domain destinations are supported')

    async def socks(self, reader, writer):
        remote = None
        try:
            async with self.slots:
                head = await asyncio.wait_for(reader.readexactly(2), 5)
                if head[0] != 5 or not head[1]:
                    return
                methods = await asyncio.wait_for(reader.readexactly(head[1]), 5)
                writer.write(b'\x05\x00' if 0 in methods else b'\x05\xff')
                await writer.drain()
                if 0 not in methods:
                    return
                version, command, reserved, kind = await asyncio.wait_for(reader.readexactly(4), 5)
                if version != 5 or reserved:
                    return
                host = await asyncio.wait_for(self.read_socks_address(reader, kind), 5)
                port = struct.unpack('!H', await asyncio.wait_for(reader.readexactly(2), 5))[0]
                if command == 3:
                    await self.socks_udp(reader, writer)
                    return
                if command != 1:
                    writer.write(b'\x05\x07\0\x01' + b'\0' * 6)
                    await writer.drain()
                    return
                remote_reader, remote, _ = await self.open_native(1, host, port)
                self.counters['tcp_connections'] += 1
                writer.write(b'\x05\0\0\x01' + b'\0' * 6)
                await writer.drain()
                await self.bridge(reader, writer, remote_reader, remote)
        except asyncio.IncompleteReadError as error:
            if error.partial:
                self.counters['tcp_errors'] += 1
        except (OSError, ValueError, RuntimeError, asyncio.TimeoutError):
            self.counters['tcp_errors'] += 1
        finally:
            if remote:
                await close_writer(remote)
            await close_writer(writer)

    async def socks_udp(self, reader, writer):
        loop = asyncio.get_running_loop()
        local = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        local.setblocking(False)
        local.bind(('127.0.0.1', 0))
        peer = [None]

        async def reply(host, port, payload):
            if peer[0]:
                packet = b'\0\0\0\x01' + socket.inet_aton(host) + struct.pack('!H', port) + payload
                await sendto(local, packet, peer[0])

        relay = NativeUDP(self, reply)
        try:
            await relay.open()
            writer.write(b'\x05\0\0\x01\x7f\0\0\x01' + struct.pack('!H', local.getsockname()[1]))
            await writer.drain()

            async def upload():
                while not relay.closed:
                    packet, sender = await recvfrom(local, 65535)
                    if sender[0] != '127.0.0.1' or len(packet) < 10 or packet[:3] != b'\0\0\0':
                        continue
                    if peer[0] is not None and peer[0] != sender:
                        continue
                    peer[0] = sender
                    if packet[3] != 1:
                        continue
                    await relay.send(socket.inet_ntoa(packet[4:8]), struct.unpack_from('!H', packet, 8)[0], packet[10:])
                    self.counters['udp_packets'] += 1
            await race(upload(), reader.read())
        finally:
            await relay.close()
            local.close()

    async def transparent_tcp(self, reader, writer):
        remote = None
        try:
            peer = writer.get_extra_info('peername')
            if peer[0] not in self.config.get('devices', []):
                self.counters['rejected'] += 1
                return
            async with self.slots:
                target = writer.get_extra_info('sockname')
                host = self.book.lookup(peer[0], target[0])
                remote_reader, remote, _ = await self.open_native(1, host, target[1])
                self.counters['tcp_connections'] += 1
                await self.bridge(reader, writer, remote_reader, remote)
        except asyncio.IncompleteReadError as error:
            if error.partial:
                self.counters['tcp_errors'] += 1
        except (OSError, ValueError, RuntimeError, asyncio.TimeoutError):
            self.counters['tcp_errors'] += 1
        finally:
            if remote:
                await close_writer(remote)
            await close_writer(writer)

    async def transparent_udp(self, payload, peer, destination):
        if peer[0] not in self.config.get('devices', []):
            self.counters['rejected'] += 1
            return
        self.counters['udp_packets'] += 1
        pending = self.associations.get(peer)
        if pending is None or pending.done() and (pending.cancelled() or pending.exception() or pending.result().closed):
            if len(self.associations) >= 128:
                self.associations = {k: v for k, v in self.associations.items()
                                     if not v.done() or not v.cancelled() and not v.exception() and not v.result().closed}
                if len(self.associations) >= 128:
                    self.counters['rejected'] += 1
                    return

            async def reply(host, port, body):
                if port == 53:
                    self.book.learn(body, peer[0])
                key = (host, port)
                sock = self.reply_sockets.get(key)
                if sock is None:
                    if len(self.reply_sockets) >= 128:
                        _, old = self.reply_sockets.popitem()
                        old.close()
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.setsockopt(socket.SOL_IP, IP_TRANSPARENT, 1)
                    sock.setblocking(False)
                    try:
                        sock.bind((host, port))
                    except BaseException:
                        sock.close()
                        raise
                    self.reply_sockets[key] = sock
                await sendto(sock, body, peer)

            pending = asyncio.create_task(NativeUDP(self, reply).open())
            self.associations[peer] = pending
        try:
            relay = await pending
            await relay.send(destination[0], destination[1], payload)
        except (OSError, RuntimeError, ValueError, asyncio.IncompleteReadError, asyncio.TimeoutError):
            self.counters['udp_errors'] += 1

    def udp_ready(self):
        for _ in range(32):
            try:
                payload, ancillary, flags, peer = self.udp_listener.recvmsg(65535, 128)
            except BlockingIOError:
                return
            if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                continue
            for level, kind, value in ancillary:
                if level == socket.SOL_IP and kind == IP_RECVORIGDSTADDR and len(value) >= 8:
                    destination = (socket.inet_ntoa(value[4:8]), struct.unpack_from('!H', value, 2)[0])
                    self.task(self.transparent_udp(payload, peer, destination))
                    break

    async def dns_query(self, payload, peer):
        if peer[0] not in self.config.get('devices', []) or not 12 <= len(payload) <= 4096:
            self.counters['rejected'] += 1
            return
        future = self.dns_associations.get(peer)
        if future is None or future.done() and (future.cancelled() or future.exception() or future.result().closed):
            if len(self.dns_associations) >= 128:
                self.dns_associations = {k: v for k, v in self.dns_associations.items()
                                         if not v.done() or not v.cancelled() and not v.exception() and not v.result().closed}
                if len(self.dns_associations) >= 128:
                    self.counters['rejected'] += 1
                    return

            async def reply(host, port, body):
                if host != self.config.get('game_dns', '1.1.1.1') or port != 53:
                    return
                self.book.learn(body, peer[0])
                await sendto(self.dns_listener, body, peer)
            future = asyncio.create_task(NativeUDP(self, reply).open())
            self.dns_associations[peer] = future
        try:
            relay = await future
            await relay.send(self.config.get('game_dns', '1.1.1.1'), 53, payload)
        except (OSError, ValueError, RuntimeError, asyncio.IncompleteReadError, asyncio.TimeoutError):
            self.counters['udp_errors'] += 1

    def dns_ready(self):
        for _ in range(32):
            try:
                payload, peer = self.dns_listener.recvfrom(4097)
            except BlockingIOError:
                return
            self.task(self.dns_query(payload, peer))

    async def renew(self):
        if self.last_refresh is not None:
            await asyncio.sleep(120)
        while True:
            try:
                try:
                    self.auth = await asyncio.to_thread(refresh, self.config, dict(self.counters))
                except APIError as error:
                    if error.code not in (400009,400010,400011,400024):raise
                    await self.restore_login_once()
                    self.auth = await asyncio.to_thread(refresh,self.config,dict(self.counters))
                self.last_refresh = int(time.time())
                self.refresh_ok = True
                self.refresh_failures = 0
                if self.managed_ports and not self.routing_active:
                    from .routing import install
                    install(self.config, *self.managed_ports)
                    self.routing_active = True
            except Exception:
                self.refresh_ok = False
                self.refresh_failures += 1
                if self.refresh_failures >= 3 and self.routing_active:
                    from .routing import remove
                    try:
                        remove()
                        self.routing_active = False
                    except Exception:
                        self.counters['routing_errors'] = self.counters.get('routing_errors', 0) + 1
            await asyncio.sleep(120 if self.refresh_ok else 30)

    async def routing_watch(self):
        from .routing import ensure
        while True:
            await asyncio.sleep(5)
            try:
                if self.routing_active:
                    ensure(self.config, *self.managed_ports)
            except Exception:
                # A firewall reload may briefly remove a chain; retry next tick.
                self.counters['routing_errors'] = self.counters.get('routing_errors', 0) + 1

    async def status(self):
        while True:
            if self.status_file:
                row = {'running': True, 'version': '0.4.4', 'experimental': True, 'ipv4_only': True,
                       'routing_active': self.routing_active,
                       'last_refresh': self.last_refresh, 'refresh_ok': self.refresh_ok,
                       'devices': self.config.get('devices', []), 'counters': self.counters}
                row['game_id'] = self.config.get('game_id')
                row['profile'] = {k: self.config.get('profile', {}).get(k) for k in ('area_id', 'line_id', 'isp_type')}
                row['node'] = {k:self.config.get('node',{}).get(k) for k in ('host','port')}
                row['mode']='http_proxy_tcp'
                row['steam_store_direct']=self.config.get('steam_store_direct',True)
                row['http_proxy'] = self.http_proxy.status() if self.http_proxy else {'running': False}
                temporary = self.status_file.with_suffix('.tmp')
                temporary.write_text(json.dumps(row))
                os.chmod(temporary, 0o644)
                os.replace(temporary, self.status_file)
            await asyncio.sleep(5)

    async def run(self, socks_port, transparent_port, dns_port=0, manage_routing=False,
                  http_host='127.0.0.1', http_port=0):
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        try:
            if self.config.get('start_on_launch'):
                try:
                    node, self.auth = await asyncio.to_thread(start_session, self.config)
                except APIError as error:
                    if error.code not in (400009,400010,400011,400024):raise
                    await self.restore_login_once()
                    node,self.auth=await asyncio.to_thread(start_session,self.config)
                self.config['node'] = node
            if socks_port:
                self.servers.append(await asyncio.start_server(
                    lambda r, w: self.task(self.socks(r, w)), '127.0.0.1', socks_port))
            if http_port:
                from .http_proxy import make_proxy
                self.http_proxy = make_proxy(self, http_host, http_port)
                await self.http_proxy.start()
            if transparent_port:
                tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                tcp.setsockopt(socket.SOL_IP, IP_TRANSPARENT, 1)
                tcp.bind(('0.0.0.0', transparent_port))
                tcp.listen(128)
                tcp.setblocking(False)
                self.servers.append(await asyncio.start_server(
                    lambda r, w: self.task(self.transparent_tcp(r, w)), sock=tcp))
                self.udp_listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.udp_listener.setsockopt(socket.SOL_IP, IP_TRANSPARENT, 1)
                self.udp_listener.setsockopt(socket.SOL_IP, IP_RECVORIGDSTADDR, 1)
                self.udp_listener.setblocking(False)
                self.udp_listener.bind(('0.0.0.0', transparent_port))
                loop.add_reader(self.udp_listener, self.udp_ready)
            if dns_port:
                self.dns_listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.dns_listener.setblocking(False)
                self.dns_listener.bind(('0.0.0.0', dns_port))
                loop.add_reader(self.dns_listener, self.dns_ready)
            if manage_routing:
                from .routing import install
                self.managed_ports = (transparent_port, dns_port)
                self.auth = await asyncio.to_thread(refresh, self.config, dict(self.counters))
                self.last_refresh, self.refresh_ok = int(time.time()), True
                install(self.config, transparent_port, dns_port)
                self.routing_active = True
                self.task(self.routing_watch())
            if self.config.get('account', {}).get('access_token'):
                self.task(self.renew())
            self.task(self.status())
            print(json.dumps({'ready': True, 'socks_port': socks_port,
                              'transparent_port': transparent_port, 'dns_port': dns_port,
                              'http_host': http_host if http_port else None, 'http_port': http_port}), flush=True)
            await stop.wait()
        finally:
            if self.http_proxy:
                await self.http_proxy.close()
            if self.routing_active:
                from .routing import remove
                remove()
                self.routing_active = False
            if self.udp_listener:
                loop.remove_reader(self.udp_listener)
                self.udp_listener.close()
            if self.dns_listener:
                loop.remove_reader(self.dns_listener)
                self.dns_listener.close()
            for server in self.servers:
                server.close()
                await server.wait_closed()
            for task in tuple(self.tasks):
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            for future in (*self.associations.values(), *self.dns_associations.values()):
                if not future.done():
                    future.cancel()
                elif not future.cancelled() and not future.exception():
                    await future.result().close()
            for sock in self.reply_sockets.values():
                sock.close()
            if self.status_file:
                self.status_file.write_text(json.dumps({'running': False}))
            if self.config.get('_owned_session_started'):
                try:
                    await asyncio.to_thread(stop_session, self.config, dict(self.counters))
                    stop_ok = True
                except Exception:
                    stop_ok = False
                if self.status_file:
                    self.status_file.write_text(json.dumps({'running': False, 'session_stop_ok': stop_ok}))
