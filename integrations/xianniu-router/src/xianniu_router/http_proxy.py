"""Explicit LAN HTTP entry sharing the existing managed native session."""
import asyncio
import ipaddress

from starpass_http.policy import DestinationDenied, ResolutionFailed, Route, destination
from starpass_http.proxy import ProxyServer
from .dns import resolve_real
from .http_streams import NativeCore


def steam_store_host(host):
    host=host.lower().rstrip('.')
    return host in ('store.steampowered.com','checkout.steampowered.com','store.steamstatic.com') or (
        host.startswith('store.') and host.endswith('.steamstatic.com'))


class RouterCore(NativeCore):
    def direct(self,host):
        return self.service.config.get('steam_store_direct',True) and steam_store_host(host)

    async def acquire_for_request(self,host,port):
        if self.direct(host):return ('127.0.0.1',1)
        return await self.acquire()

    async def open_connection(self,host,port):
        if self.direct(host):
            address=await asyncio.to_thread(resolve_real,host,self.service.config.get('dns_server','192.168.31.1'))
            if not ipaddress.IPv4Address(address).is_global:raise ValueError('Invalid public destination')
            streams=await asyncio.wait_for(asyncio.open_connection(address,port),8)
            self.service.counters['direct_connections']=self.service.counters.get('direct_connections',0)+1
            return streams
        return await super().open_connection(host,port)
    def status(self):
        return {'engine': 'xianniu-native', 'session_mode': 'managed',
                'refresh_ok': self.service.refresh_ok}

    async def acquire(self):
        if self.service.refresh_failures >= 3:
            raise RuntimeError('Session renewal unavailable')
        return await super().acquire()


def make_proxy(service, host, port):
    address = ipaddress.IPv4Address(host)
    if address.is_unspecified or address.is_multicast or not (address.is_private or address.is_loopback):
        raise ValueError('HTTP entry must bind a local IPv4 address')

    async def resolve(hostname, target_port):
        # Query the existing LAN resolver explicitly. N1's system resolver can
        # return OpenClash fake-IP addresses, which cannot identify real targets.
        kind = destination(hostname)
        if kind == 'external':
            if ':' in hostname:
                raise DestinationDenied('IPv6 is unsupported')
            return Route('external')
        if kind != 'name':
            raise DestinationDenied('Only public destinations are accelerated')
        try:
            answer = await asyncio.to_thread(resolve_real, hostname, service.config.get('dns_server', '192.168.31.1'))
        except (OSError, ValueError) as exc:
            raise ResolutionFailed('LAN DNS lookup failed') from exc
        if not ipaddress.IPv4Address(answer).is_global:
            raise DestinationDenied('Destination resolved to a non-public IPv4 address')
        return Route('external')

    allowed = sorted(set(service.config.get('devices', [])) | {'127.0.0.1', str(address)})
    return ProxyServer({'listen_host': str(address), 'listen_port': port,
                        'allowed_clients': allowed, 'request_timeout': 20,
                        'max_connections': 64, 'destination_resolver': resolve}, RouterCore(service))
