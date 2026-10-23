"""Explicit, unauthenticated loopback proxy adapters for Steam web traffic.

Protocol and certificate checks prove a TCP tunnel, not accelerator coverage.
No brand-specific driver, account, settings, route or system proxy is controlled.
"""
from __future__ import annotations

import asyncio
import ipaddress
import math
import socket
import ssl
import time

from .policy import destination, normalize_host
from .steam_host import SteamHostCore, allowed_target
from .windows_accelerator import verify_http_connect

TEST_TARGET = 'store.steampowered.com'


def validate_proxy_settings(value):
    """A fixed IPv4 loopback endpoint with no credentials or extra fields."""
    if (not isinstance(value, dict) or set(value) != {'host', 'port', 'protocol'}
            or value.get('host') != '127.0.0.1' or type(value.get('port')) is not int
            or not 1024 <= value['port'] <= 65535 or value.get('protocol') not in ('http', 'socks5')):
        raise ValueError('Accelerator proxy must contain only host=127.0.0.1, an integer port from 1024 to 65535, and protocol=http or socks5')
    return dict(host='127.0.0.1', port=value['port'], protocol=value['protocol'])


def _connect_request(host, port):
    if type(port) is not int or port not in (80, 443) or not isinstance(host, str):
        raise ValueError('Invalid SOCKS5 target')
    host = normalize_host(host)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not allowed_target(host, port):
            raise ValueError('SOCKS5 target is outside the Steam service profile')
        encoded = host.encode('ascii')
        address_bytes = b'\x03' + bytes((len(encoded),)) + encoded
    else:
        if destination(host) != 'external' or not address.is_global or address.is_multicast:
            raise ValueError('SOCKS5 target must be public')
        address_bytes = (b'\x01' if address.version == 4 else b'\x04') + address.packed
    return b'\x05\x01\x00' + address_bytes + port.to_bytes(2, 'big')


def _reply_address_size(header):
    if len(header) != 4 or header[:3] != b'\x05\x00\x00' or header[3] not in (1, 3, 4):
        raise ValueError('SOCKS5 proxy rejected CONNECT or sent an invalid reply')
    return {1: 4, 3: None, 4: 16}[header[3]]


async def _socks5_connect(reader, writer, host, port):
    request = _connect_request(host, port)
    writer.write(b'\x05\x01\x00')
    await writer.drain()
    if await reader.readexactly(2) != b'\x05\x00':
        raise ValueError('SOCKS5 proxy requires authentication or does not support no-auth SOCKS5')
    writer.write(request)
    await writer.drain()
    size = _reply_address_size(await reader.readexactly(4))
    if size is None:
        size = (await reader.readexactly(1))[0]
        if not size:
            raise ValueError('SOCKS5 proxy returned an empty bound address')
    await reader.readexactly(size + 2)


class GenericAcceleratorProxy(SteamHostCore):
    """Reuse Steam's strict domain/public-DNS policy, through a chosen proxy."""
    def __init__(self, config, *, resolver=None):
        super().__init__(config, resolver=resolver)
        self.endpoint = validate_proxy_settings(config.get('accelerator_proxy'))
        self.protocol = self.endpoint['protocol']
        self.handshake_timeout = 5.0

    def status(self):
        return dict(core_state='external', accelerator_proxy_protocol=self.protocol,
                    node_management=False, selection_mode='delegated', selected_node='', nodes=[],
                    acceleration_verified=False, tcp_only=True, error='', preparing=False)

    async def acquire(self):
        await super().acquire()
        return self.endpoint['host'], self.endpoint['port']

    async def prepare_connection(self, reader, writer, host, port):
        if self.closing or self.protocol != 'socks5':
            raise ValueError('SOCKS5 connection preparation is unavailable')
        try:
            await asyncio.wait_for(_socks5_connect(reader, writer, host, port), self.handshake_timeout)
        except asyncio.TimeoutError:
            raise
        except (OSError, ValueError, asyncio.IncompleteReadError):
            raise ValueError('SOCKS5 proxy handshake failed') from None


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError()
    return remaining


def _read_exactly(transport, count, deadline):
    received = bytearray()
    while len(received) < count:
        transport.settimeout(_remaining(deadline))
        part = transport.recv(count - len(received))
        if not part:
            raise ValueError('Incomplete SOCKS5 reply')
        received.extend(part)
    return bytes(received)


def verify_accelerator_proxy(value, timeout=5.0, *, socket_factory=None, context_factory=None):
    """Fresh standard-protocol and target TLS check, with a total deadline.

    Factories are injectable for offline tests; production uses the system trust
    store, hostname verification and a fixed Steam HTTPS diagnostic destination.
    The probe sends no account credentials and no HTTP content after TLS.
    """
    result = dict(probe_passed=False, tls_verified=False, acceleration_verified=False,
                  tcp_only=True, verified_endpoint=None, reason='invalid_endpoint')
    try:
        endpoint = validate_proxy_settings(value)
        duration = float(timeout)
        if not math.isfinite(duration) or not 0 < duration <= 10:
            return result
    except (TypeError, ValueError):
        return result
    if endpoint['protocol'] == 'http':
        checked = verify_http_connect(endpoint['host'], endpoint['port'], TEST_TARGET, duration,
                                      socket_factory=socket_factory, context_factory=context_factory)
        result.update(checked)
        result.update(acceleration_verified=False, tcp_only=True)
        if checked.get('probe_passed') is True and checked.get('tls_verified') is True:
            result['verified_endpoint'] = endpoint
        return result
    transport = encrypted = None
    deadline = time.monotonic() + duration
    try:
        context = (context_factory or ssl.create_default_context)()
        if context.verify_mode != ssl.CERT_REQUIRED or context.check_hostname is not True:
            result['reason'] = 'tls_verification_required'
            return result
        transport = (socket_factory or socket.create_connection)(
            (endpoint['host'], endpoint['port']), timeout=_remaining(deadline))
        transport.settimeout(_remaining(deadline))
        transport.sendall(b'\x05\x01\x00')
        if _read_exactly(transport, 2, deadline) != b'\x05\x00':
            result['reason'] = 'socks5_noauth_rejected'
            return result
        transport.settimeout(_remaining(deadline))
        transport.sendall(_connect_request(TEST_TARGET, 443))
        size = _reply_address_size(_read_exactly(transport, 4, deadline))
        if size is None:
            size = _read_exactly(transport, 1, deadline)[0]
            if not size:
                result['reason'] = 'socks5_invalid_reply'
                return result
        _read_exactly(transport, size + 2, deadline)
        transport.settimeout(_remaining(deadline))
        encrypted = context.wrap_socket(transport, server_hostname=TEST_TARGET,
                                         do_handshake_on_connect=False)
        encrypted.settimeout(_remaining(deadline))
        encrypted.do_handshake()
        _remaining(deadline)
        if not encrypted.getpeercert():
            result['reason'] = 'tls_certificate_missing'
            return result
        result.update(probe_passed=True, tls_verified=True, verified_endpoint=endpoint,
                      reason='socks5_tls_verified')
    except TimeoutError:
        result['reason'] = 'probe_timeout'
    except ssl.SSLError:
        result['reason'] = 'tls_verification_failed'
    except (OSError, ValueError):
        result['reason'] = 'socks5_connection_failed'
    finally:
        for resource in (encrypted, transport):
            if resource is not None:
                try:
                    resource.close()
                except OSError:
                    pass
    return result
