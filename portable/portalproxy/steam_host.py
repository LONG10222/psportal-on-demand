"""Explicit Windows host egress for Steam HTTP/CONNECT traffic only.

The domain list follows Steam Support's Required Ports for Steam article:
https://help.steampowered.com/en/faqs/view/2EA8-4D75-DA21-31EB
Akamai's akamaihd.net is a shared CDN, not a Valve-owned namespace. This mode
does not control any accelerator, change OS networking or prove acceleration.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import sys

from .policy import (DestinationDenied, ResolutionFailed, Route, destination,
                     ipv4, ipv6, normalize_host, valid_name)

STEAM_DOMAINS = ('steampowered.com', 'steamcommunity.com', 'steamgames.com',
                 'steamusercontent.com', 'steamcontent.com', 'steamstatic.com', 'akamaihd.net')


def allowed_target(host, port):
    if not isinstance(host, str) or type(port) is not int or port not in (80, 443):
        return False
    host = normalize_host(host)
    return (valid_name(host) and any(host == root or host.endswith('.' + root)
                                    for root in STEAM_DOMAINS))


class SteamHostCore:
    """No core process: count owned TCP sessions and resolve approved domains."""
    def __init__(self, config, *, resolver=None):
        if sys.platform != 'win32':
            raise ValueError('Steam host relay runs on Windows only. Configuration checks are available on other systems.')
        self.active = 0
        self.closing = False
        self._resolver = resolver

    def status(self):
        return dict(core_state='host', host_relay='steam', node_management=False,
                    selection_mode='host', selected_node='', nodes=[],
                    acceleration_verified=False, tcp_only=True, error='', preparing=False)

    def start_monitor(self):
        pass

    async def acquire(self):
        if self.closing:
            raise RuntimeError('Steam host relay is stopping')
        self.active += 1
        return None

    async def release(self):
        self.active = max(0, self.active - 1)

    async def close(self):
        self.closing = True

    async def resolve_target(self, host, port):
        """Validate every DNS answer and return one numeric public address.

        No domain is delegated to the outbound connector. Mixed private/public,
        malformed or unsupported DNS results fail closed for the whole request.
        """
        if self.closing:
            raise RuntimeError('Steam host relay is stopping')
        if not allowed_target(host, port):
            raise DestinationDenied('Steam host relay permits documented Steam domains on TCP ports 80 and 443 only')
        host = normalize_host(host)
        resolver = self._resolver or asyncio.get_running_loop().getaddrinfo
        try:
            answers = await resolver(host, port, family=socket.AF_UNSPEC,
                                     type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
        except (OSError, UnicodeError, ValueError) as exc:
            raise ResolutionFailed('Steam destination lookup failed') from exc
        if not isinstance(answers, (tuple, list)) or not answers or len(answers) > 256:
            raise ResolutionFailed('Steam destination lookup returned no usable addresses')
        addresses = []
        for answer in answers:
            if not isinstance(answer, (tuple, list)) or len(answer) != 5:
                raise ResolutionFailed('Malformed Steam destination lookup')
            family, socktype, protocol, _canonical_name, sockaddr = answer
            if (family not in (socket.AF_INET, socket.AF_INET6) or socktype != socket.SOCK_STREAM
                    or protocol not in (0, socket.IPPROTO_TCP) or not isinstance(sockaddr, tuple)
                    or len(sockaddr) != (2 if family == socket.AF_INET else 4)
                    or not isinstance(sockaddr[0], str) or type(sockaddr[1]) is not int or sockaddr[1] != port):
                raise ResolutionFailed('Unsupported Steam destination lookup')
            address = sockaddr[0]
            if family == socket.AF_INET6 and sockaddr[3] != 0:
                raise DestinationDenied('Scoped Steam destination is not permitted')
            if (family == socket.AF_INET and not ipv4(address)
                    or family == socket.AF_INET6 and not ipv6(address)):
                raise ResolutionFailed('Steam destination address family mismatch')
            literal = ipaddress.ip_address(address)
            if destination(address) != 'external' or not literal.is_global or literal.is_multicast:
                raise DestinationDenied('Steam destination lookup contained a non-public address')
            addresses.append(str(literal))
        return Route('external', addresses[0])
