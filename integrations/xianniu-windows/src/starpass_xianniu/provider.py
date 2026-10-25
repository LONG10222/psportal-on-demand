"""Native provider with explicit session ownership and bounded LAN SOCKS5 UDP."""
import asyncio
import contextlib
import copy
import ipaddress
import socket
import struct
import time
import traceback
from pathlib import Path

from xianniu_router import control
from xianniu_router.dns import resolve_real
from xianniu_router.http_proxy import RouterCore, make_proxy, steam_store_host
from xianniu_router.member_time import balances
from xianniu_router.runtime import Service, NativeUDP, close_writer, race
from xianniu_router.manager import Manager
from . import __version__


class ReadyCore(RouterCore):
    async def acquire_for_request(self, host, port):
        if not self.service.active or self.service.refresh_failures:
            raise RuntimeError('Provider is not ready')
        return await super().acquire_for_request(host, port)


class Catalog(Manager):
    def __init__(self, config, path):
        self.value = config
        self.catalog_path = path
    def config(self):
        return copy.deepcopy(self.value)
    def preferences(self):
        return {'recent': [self.value.get('game_id', 797)]}


def validate(config):
    result = copy.deepcopy({k: v for k, v in config.items() if not k.startswith('_')})
    if result.get('session_mode') not in ('borrowed', 'managed'):
        raise ValueError('无效的会话模式')
    host = ipaddress.IPv4Address(result.get('listen_host', '127.0.0.1'))
    if not (host.is_loopback or host in ipaddress.ip_network('192.168.0.0/16') or
            host in ipaddress.ip_network('10.0.0.0/8') or host in ipaddress.ip_network('172.16.0.0/12')):
        raise ValueError('请使用电脑的实际局域网 IPv4 地址')
    for key in ('http_port', 'socks_port'):
        if type(result.get(key)) is not int or not 1024 <= result[key] <= 65535:
            raise ValueError('代理端口必须在 1024–65535')
    if result['http_port'] == result['socks_port']:
        raise ValueError('HTTP 与 SOCKS5 端口不能相同')
    result['devices'] = sorted({str(ipaddress.IPv4Address(x)) for x in result.get('devices', [])})
    if len(result['devices']) > 32:
        raise ValueError('预览最多允许 32 台设备')
    for device in result['devices']:
        if not ipaddress.IPv4Address(device).is_private or ipaddress.IPv4Address(device).is_unspecified:
            raise ValueError('共享设备必须是明确的局域网地址')
    ipaddress.IPv4Address(result['dns_server'])
    if not result.get('account', {}).get('access_token'):
        raise ValueError('请先使用官方微信登录')
    if result['session_mode'] == 'borrowed':
        if not result.get('external_session_owner'):
            raise ValueError('复用模式需要明确的现有会话来源')
        if not ipaddress.IPv4Address(result['node']['host']).is_global:
            raise ValueError('现有会话缺少有效节点')
        if not 1 <= int(result['node']['port']) <= 65535:
            raise ValueError('现有会话节点端口无效')
    return result


class WindowsService(Service):
    async def open_native(self, command, host, port):
        if not self.active or self.refresh_failures:
            raise RuntimeError('官方续期失败，已暂停新连接')
        return await super().open_native(command, host, port)

    async def target(self, host, port):
        try:
            address = ipaddress.IPv4Address(host)
        except ValueError:
            from starpass_http.policy import valid_name
            if not valid_name(host) or host == 'localhost' or host.endswith('.localhost'):
                raise ValueError('Invalid destination name')
            address = ipaddress.IPv4Address(await asyncio.to_thread(resolve_real, host, self.config['dns_server']))
        if not address.is_global or not 1 <= port <= 65535:
            raise ValueError('Only public IPv4 destinations are supported')
        return str(address)

    async def socks(self, reader, writer):
        remote = None
        peer = writer.get_extra_info('peername')[0]
        try:
            if peer not in self.allowed:
                self.counters['rejected'] += 1
                return
            if self.slots.locked():
                self.counters['rejected'] += 1
                return
            async with self.slots:
                version, count = await asyncio.wait_for(reader.readexactly(2), 5)
                if version != 5 or count == 0: return
                methods = await asyncio.wait_for(reader.readexactly(count), 5)
                writer.write(b'\x05\x00' if 0 in methods else b'\x05\xff')
                await writer.drain()
                if 0 not in methods: return
                version, command, reserved, kind = await asyncio.wait_for(reader.readexactly(4), 5)
                host = await asyncio.wait_for(self.read_socks_address(reader, kind), 5)
                port = struct.unpack('!H', await asyncio.wait_for(reader.readexactly(2), 5))[0]
                if version != 5 or reserved: return
                if command == 3:
                    # The association always belongs to the TCP source IP.
                    if host not in ('0.0.0.0', peer):
                        raise ValueError('UDP endpoint does not match TCP peer')
                    await self.socks_udp(reader, writer, peer, port)
                    return
                if command != 1: raise ValueError('Unsupported SOCKS command')
                await self.target(host, port)
                if not self.active: raise RuntimeError('Provider is not ready')
                core = ReadyCore(self)
                remote_reader, remote = await core.open_connection(host, port)
                writer.write(b'\x05\0\0\x01' + b'\0' * 6)
                await writer.drain()
                self.clients[peer] = self.clients.get(peer, 0) + 1
                await self.byte_bridge(reader, writer, remote_reader, remote)
        except (OSError, ValueError, RuntimeError, asyncio.IncompleteReadError, asyncio.TimeoutError):
            self.counters['tcp_errors'] += 1
            with contextlib.suppress(Exception):
                writer.write(b'\x05\x01\0\x01' + b'\0' * 6)
                await writer.drain()
        finally:
            if remote: await close_writer(remote)
            await close_writer(writer)

    async def byte_bridge(self, reader, writer, remote_reader, remote_writer):
        async def pump(source, target):
            while True:
                data = await asyncio.wait_for(source.read(16384), 180)
                if not data: return
                target.write(data)
                await asyncio.wait_for(target.drain(), 20)
        await race(pump(reader, remote_writer), pump(remote_reader, writer))

    async def socks_udp(self, reader, writer, peer_ip, requested_port=0):
        loop = asyncio.get_running_loop()
        local = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        local.setblocking(False)
        host = writer.get_extra_info('sockname')[0]
        local.bind((host, 0))
        peer = [(peer_ip, requested_port) if requested_port else None]
        permitted_responses = set()

        async def reply(host, port, payload):
            if peer[0] and (host, port) in permitted_responses:
                packet = b'\0\0\0\x01' + socket.inet_aton(host) + struct.pack('!H', port) + payload
                await loop.sock_sendto(local, packet, peer[0])

        relay = NativeUDP(self, reply)
        try:
            await relay.open()
            writer.write(b'\x05\0\0\x01' + socket.inet_aton(host) + struct.pack('!H', local.getsockname()[1]))
            await writer.drain()

            async def upload():
                while not relay.closed:
                    packet, sender = await asyncio.wait_for(loop.sock_recvfrom(local, 65535), 120)
                    if sender[0] != peer_ip or peer[0] and sender != peer[0]: continue
                    if len(packet) < 10 or packet[:3] != b'\0\0\0': continue
                    if packet[3] == 1:
                        target, offset = socket.inet_ntoa(packet[4:8]), 8
                    elif packet[3] == 3 and len(packet) >= 7 + packet[4]:
                        target, offset = packet[5:5+packet[4]].decode('ascii'), 5+packet[4]
                    else: continue
                    port = struct.unpack_from('!H', packet, offset)[0]
                    try:
                        address = await self.target(target, port)
                    except (OSError, ValueError):
                        self.counters['rejected'] += 1
                        continue
                    if len(permitted_responses) >= 256 and (address, port) not in permitted_responses:
                        self.counters['rejected'] += 1
                        continue
                    peer[0] = sender
                    permitted_responses.add((address, port))
                    if self.refresh_failures: raise RuntimeError('Renewal unavailable')
                    await relay.send(address, port, packet[offset+2:])
                    self.counters['udp_packets'] += 1
                    self.clients[peer_ip] = self.clients.get(peer_ip, 0) + 1
            await race(upload(), reader.read(), self.wait_udp_closed(relay))
        finally:
            await relay.close()
            local.close()

    async def wait_udp_closed(self, relay):
        while not relay.closed:
            await asyncio.sleep(1)


class Provider:
    def __init__(self, config, store=None):
        self.config = validate(config)
        self.store = store
        self.service = WindowsService(self.config)
        self.service.allowed = set(self.config['devices']) | {'127.0.0.1', self.config['listen_host']}
        self.service.clients = {}
        self.service.active = False
        self.service.slots = asyncio.Semaphore(32)
        self.proxies = []
        self.background = []
        self.member = {}
        self.running = False
        self.last_error = ''
        self.renewals = 0
        self.stop_ok = None
        self.lifecycle = asyncio.Lock()
        self.renew_seconds = 120
        self.retry_seconds = 30
        self.startup_stage = 'stopped'
        self.failure_site = []

    async def member_refresh(self):
        data = await asyncio.to_thread(control.call_api, self.config, '/client/member/details',
                                       {'access_token': self.config['account']['access_token']})
        self.member = {**balances(data), 'pause_state': data.get('pause_state'),
                       'package_title': data.get('package_title'), 'expired_datetime': data.get('expired_datetime'),
                       'updated_at': int(time.time())}
        return self.member

    async def start(self, exclusive=False):
        async with self.lifecycle:
            return await self._start(exclusive)

    async def _start(self, exclusive):
        if self.running: return
        self.last_error = ''
        self.failure_site = []
        self.stop_ok = None
        if self.config['session_mode'] == 'managed':
            if not exclusive or self.config.get('external_session_owner'):
                raise ValueError('请先在其他入口停止该账号会话，并在高级设置确认由 Windows 独占')
            if self.store and self.store.unresolved():
                raise ValueError('上次会话未确认结束，请先核对官方客户端；本预览不会自动停止未知会话')
        # Reserve every listener before any billable API operation.
        try:
            self.startup_stage = 'reserve_listeners'
            hosts = {'127.0.0.1', self.config['listen_host']}
            for host in sorted(hosts):
                proxy = make_proxy(self.service, host, self.config['http_port'])
                proxy.core = ReadyCore(self.service)
                await proxy.start()
                self.proxies.append(proxy)
                self.service.servers.append(await asyncio.start_server(
                    lambda r, w: self.service.task(self.service.socks(r, w)), host, self.config['socks_port']))
            if self.config['session_mode'] == 'managed':
                self.startup_stage = 'member_details'
                member = await self.member_refresh()
                if member.get('pause_state') in (0, '0'):
                    self.startup_stage = 'member_recovery'
                    await asyncio.to_thread(control.call_api, self.config, '/client/member/recovery',
                                            {'access_token': self.config['account']['access_token'], 'sender': 0})
                if self.store: self.store.journal('start_pending')
                self.startup_stage = 'official_start'
                try:
                    node, auth = await asyncio.to_thread(control.start_session, self.config)
                except control.APIError:
                    # An explicit official refusal is not an owned session.
                    if self.store: self.store.journal(None)
                    raise
                self.config['node'] = node
                self.service.auth = auth
                if self.store: self.store.journal('owned')
            self.startup_stage = 'initial_token'
            self.service.auth = await asyncio.to_thread(control.refresh, self.config, dict(self.service.counters))
            self.service.last_refresh = int(time.time())
            self.service.refresh_ok = True
            self.service.refresh_failures = 0
            self.running = True
            self.service.active = True
            self.background = [asyncio.create_task(self.renew()), asyncio.create_task(self.members())]
            self.startup_stage = 'ready'
        except BaseException as error:
            self.failure_site = [{'module':Path(f.filename).name,'function':f.name,'line':f.lineno} for f in traceback.extract_tb(error.__traceback__)]
            self.last_error = '准备失败：' + type(error).__name__ + (' code=' + str(error.code) if isinstance(error, control.APIError) else '')
            await self._stop()
            raise

    async def renew(self):
        while self.running:
            await asyncio.sleep(self.renew_seconds if self.service.refresh_ok else self.retry_seconds)
            try:
                self.service.auth = await asyncio.to_thread(control.refresh, self.config, dict(self.service.counters))
                self.service.last_refresh = int(time.time())
                self.service.refresh_ok = True
                self.service.refresh_failures = 0
                self.renewals += 1
                self.last_error = ''
            except Exception:
                self.service.refresh_ok = False
                self.service.refresh_failures += 1
                self.last_error = '官方续期失败；新连接已暂停，不会改走其他出口'
                if self.service.refresh_failures >= 3:
                    await self.stop()
                    return

    async def members(self):
        while self.running:
            try: await self.member_refresh()
            except Exception: self.last_error = '官方会员资料刷新失败，请重试'
            await asyncio.sleep(60)

    async def stop(self):
        async with self.lifecycle:
            await self._stop()

    async def stop_and_pause(self):
        async with self.lifecycle:
            if self.config['session_mode'] != 'managed' or not self.config.get('_owned_session_started'):
                raise ValueError('只能暂停本预览当前独占的会话；复用或未知会话请在原入口管理')
            await self._stop()
            if self.stop_ok is not True:
                raise ValueError('官方停止未确认，暂不暂停账号计时，请在官方客户端核对')
            await asyncio.to_thread(control.call_api, self.config, '/client/member/suspend',
                                    {'access_token': self.config['account']['access_token'], 'sender': 0})
            member = await self.member_refresh()
            if member.get('pause_state') not in (0, '0'):
                raise ValueError('官方尚未确认暂停，请刷新时长后核对')
            return member

    async def _stop(self):
        self.running = False
        self.service.active = False
        tasks = [t for t in self.background if t is not asyncio.current_task()]
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.background = []
        for proxy in self.proxies: await proxy.close()
        self.proxies.clear()
        for server in self.service.servers:
            server.close()
            await server.wait_closed()
        self.service.servers.clear()
        tasks = list(self.service.tasks)
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.config.get('_owned_session_started'):
            try:
                self.stop_ok = await asyncio.to_thread(control.stop_session, self.config, dict(self.service.counters))
                if self.stop_ok and self.store: self.store.journal(None)
            except Exception:
                self.stop_ok = False
                self.last_error = '官方停止未确认，请在官方客户端核对；未自动暂停会员计时'

    def status(self):
        return {'running': self.running, 'engine': 'xianniu-native', 'version': __version__, 'startup_stage':self.startup_stage, 'failure_site':list(self.failure_site),
                'session_mode': self.config['session_mode'], 'game_id': self.config['game_id'],
                'profile': dict(self.config['profile']), 'refresh_ok': self.service.refresh_ok,
                'last_refresh': self.service.last_refresh, 'renewals': self.renewals,
                'counters': dict(self.service.counters), 'member': dict(self.member),
                'clients': dict(self.service.clients), 'http_clients': [dict(p.clients) for p in self.proxies],
                'listen_host': self.config['listen_host'], 'http_port': self.config['http_port'],
                'socks_port': self.config['socks_port'], 'last_error': self.last_error,
                'official_stop_ok': self.stop_ok, 'console_udp_captured': False,
                'traffic_verified': False, 'network_configuration_changed': False}
