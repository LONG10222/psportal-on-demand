"""Conservative client destination policy; never delegate unsafe names to a core.

This intentionally mirrors src/protocol.lua, rather than ipaddress.is_private,
whose definition is broader than the RFC1918/ULA direct-routing policy.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass

IPV4_REJECT_NETWORKS = (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
    "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24",
    "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
)
IPV6_REJECT_NETWORKS = (
    "::/3", "4000::/2", "8000::/1", "2001::/23", "2001:db8::/32",
    "2002::/16", "3fff::/20",
)
_LOCAL4 = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
_DENY4 = tuple(ipaddress.ip_network(n) for n in IPV4_REJECT_NETWORKS)
_LOCAL6 = ipaddress.ip_network("fc00::/7")
_EXTERNAL6 = ipaddress.ip_network("2000::/3")
_DENY6 = tuple(ipaddress.ip_network(n) for n in IPV6_REJECT_NETWORKS[3:])
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z", re.ASCII)
_NUMERIC_LABEL = re.compile(r"(?:[0-9]+|0x[0-9a-f]+)\Z", re.ASCII)


class DestinationDenied(ValueError):
    """An address or name violates the client destination policy."""


class ResolutionFailed(ValueError):
    """The system resolver could not establish a safe destination."""


@dataclass(frozen=True)
class Route:
    kind: str
    address: str | None = None


def ipv4(host: str) -> bool:
    if not isinstance(host, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", host, re.ASCII):
        return False
    return all(len(p) <= 3 and (p == "0" or not p.startswith("0")) and int(p) <= 255 for p in host.split("."))


def ipv6(host: str) -> bool:
    if not isinstance(host, str) or ":" not in host or not re.fullmatch(r"[a-fA-F0-9:.]+", host, re.ASCII):
        return False
    if "." in host and not ipv4(host.rsplit(":", 1)[-1]):
        return False
    try:
        ipaddress.IPv6Address(host)
        return True
    except ValueError:
        return False


def normalize_host(host: str) -> str:
    host = host.lower()
    return host[:-1] if ":" not in host and host.endswith(".") else host


def valid_name(host: str) -> bool:
    if not isinstance(host, str) or not 1 <= len(host) <= 253:
        return False
    labels = host.split(".")
    return all(_LABEL.fullmatch(label) for label in labels) and not all(_NUMERIC_LABEL.fullmatch(label) for label in labels)


def destination(host: str) -> str:
    """Return local, external, name, or deny without consulting DNS."""
    if not isinstance(host, str):
        return "deny"
    host = normalize_host(host)
    if ipv4(host):
        addr = ipaddress.IPv4Address(host)
        if any(addr in n for n in _LOCAL4):
            return "local"
        return "deny" if any(addr in n for n in _DENY4) else "external"
    if ":" in host:
        if not ipv6(host):
            return "deny"
        addr = ipaddress.IPv6Address(host)
        if addr in _LOCAL6:
            return "local"
        return "external" if addr in _EXTERNAL6 and not any(addr in n for n in _DENY6) else "deny"
    if not valid_name(host) or host == "localhost" or host.endswith(".localhost"):
        return "deny"
    return "name"


def local_ip(host: str) -> bool:
    return (ipv4(host) or ipv6(host)) and destination(host) == "local"


def backend_reject_rules() -> list[str]:
    """Mihomo rules: DNS resolution MUST stay enabled for these IP rules."""
    return (["DOMAIN-SUFFIX,localhost,REJECT"]
            + [f"IP-CIDR,{n},REJECT" for n in IPV4_REJECT_NETWORKS]
            + [f"IP-CIDR6,{n},REJECT" for n in IPV6_REJECT_NETWORKS])


async def resolve_destination(host: str, port: int) -> Route:
    """Classify every system resolver answer and pin direct routes numerically.

    getaddrinfo is the OS resolver trust boundary. It does not expose DNS wire
    records, so the portable implementation cannot validate echoed questions or
    CNAME chains itself. No resolution error, empty result, unsupported family,
    malformed address, or denied answer is ever an external fallback. Mixed
    approved local/public answers use the core, whose rules also reject LAN IPs.
    """
    host = normalize_host(host)
    kind = destination(host)
    if kind == "deny":
        raise DestinationDenied("destination is not permitted")
    if kind != "name":
        return Route(kind, host if kind == "local" else None)
    try:
        answers = await asyncio.get_running_loop().getaddrinfo(
            host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ResolutionFailed("destination lookup failed") from exc
    if not answers:
        raise ResolutionFailed("destination lookup returned no addresses")
    local_addresses = []
    has_external = False
    for answer in answers:
        if not isinstance(answer, (tuple, list)) or len(answer) != 5:
            raise ResolutionFailed("malformed resolver answer")
        family, socktype, protocol, _canonical_name, sockaddr = answer
        if family not in (socket.AF_INET, socket.AF_INET6) or socktype != socket.SOCK_STREAM or protocol not in (0, socket.IPPROTO_TCP):
            raise ResolutionFailed("unsupported resolver answer")
        if not isinstance(sockaddr, tuple) or not sockaddr or not isinstance(sockaddr[0], str):
            raise ResolutionFailed("malformed resolver answer")
        if family == socket.AF_INET and len(sockaddr) != 2:
            raise ResolutionFailed("malformed IPv4 resolver answer")
        address = sockaddr[0]
        # Never let a scope identifier bypass the literal policy.
        if family == socket.AF_INET6 and (len(sockaddr) != 4 or sockaddr[3] != 0):
            raise DestinationDenied("scoped resolver address is not permitted")
        if (family == socket.AF_INET and not ipv4(address)) or (family == socket.AF_INET6 and not ipv6(address)):
            raise ResolutionFailed("resolver family/address mismatch")
        answer_kind = destination(address)
        if answer_kind not in ("local", "external"):
            raise DestinationDenied("destination lookup contained a denied address")
        if answer_kind == "external":
            has_external = True
        else:
            local_addresses.append(address)
    if has_external:
        return Route("external")
    return Route("local", local_addresses[0])


class FastestSelection:
    """Measured latency selection with a deadband, two rounds, and hold-down.

    Unhealthy/missing current nodes fail over immediately. Healthy nodes only
    switch after the same challenger wins two complete probe rounds, improving
    latency by more than the configured threshold, and a 30-second hold-down.
    """
    def __init__(self):
        self.current = ''
        self.challenger = ''
        self.rounds = 0
        self.switched_at = float('-inf')

    def choose(self, nodes, threshold_ms=50, now=None, measured=True):
        import time
        now = time.monotonic() if now is None else now
        if not measured:
            self.challenger, self.rounds = "", 0
        healthy = {n['name']: n['delay_ms'] for n in nodes
                   if n.get('healthy') is True and type(n.get('delay_ms')) in (int, float)
                   and n['delay_ms'] >= 0}
        if not healthy:
            self.challenger, self.rounds = '', 0
            return ''
        best = min(healthy, key=lambda name: (healthy[name], name))
        if self.current not in healthy:
            self.current, self.switched_at = best, now
            self.challenger, self.rounds = '', 0
        elif measured and best != self.current and healthy[self.current] - healthy[best] > threshold_ms:
            self.rounds = self.rounds + 1 if self.challenger == best else 1
            self.challenger = best
            if self.rounds >= 2 and now - self.switched_at >= 30:
                self.current, self.switched_at = best, now
                self.challenger, self.rounds = '', 0
        elif measured:
            self.challenger, self.rounds = '', 0
        return self.current
