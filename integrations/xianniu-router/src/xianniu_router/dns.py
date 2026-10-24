"""DNS address learning for transparent TCP; never stores packet payloads."""
import ipaddress
import secrets
import socket
import struct
import time


def name_at(data, offset):
    labels = []
    following = None
    seen = set()
    for _ in range(128):
        if offset >= len(data) or offset in seen:
            raise ValueError('Invalid DNS name')
        seen.add(offset)
        size = data[offset]
        if size & 0xc0 == 0xc0:
            if offset + 1 >= len(data):
                raise ValueError('Truncated DNS pointer')
            if following is None:
                following = offset + 2
            offset = ((size & 0x3f) << 8) | data[offset + 1]
        elif size & 0xc0 or size > 63:
            raise ValueError('Invalid DNS label')
        elif size == 0:
            return b'.'.join(labels).decode('ascii').lower(), following or offset + 1
        else:
            offset += 1
            if offset + size > len(data):
                raise ValueError('Truncated DNS name')
            labels.append(data[offset:offset + size])
            offset += size
    raise ValueError('DNS pointer depth exceeded')


def addresses(data):
    if len(data) < 12:
        return None, []
    _, flags, questions, answers, _, _ = struct.unpack_from('!6H', data)
    if not flags & 0x8000 or flags & 15 or flags & 0x200 or questions != 1:
        return None, []
    question, offset = name_at(data, 12)
    offset += 4
    found = []
    for _ in range(min(answers, 128)):
        _, offset = name_at(data, offset)
        typ, cls, ttl, length = struct.unpack_from('!HHIH', data, offset)
        offset += 10
        if offset + length > len(data):
            raise ValueError('Truncated DNS record')
        if typ == cls == 1 and length == 4:
            address = str(ipaddress.IPv4Address(data[offset:offset + 4]))
            if ipaddress.ip_address(address).is_global:
                found.append((address, min(ttl, 3600)))
        offset += length
    return question, found


class AddressBook:
    def __init__(self):
        self.entries = {}

    def learn(self, payload, client):
        try:
            question, rows = addresses(payload)
        except (ValueError, UnicodeError, struct.error):
            return
        if len(self.entries) > 4096:
            now = time.monotonic()
            self.entries = {k: v for k, v in self.entries.items() if v[1] > now}
        for address, ttl in rows:
            if len(self.entries) < 4096:
                self.entries[(client, address)] = (question, time.monotonic() + ttl)

    def lookup(self, client, address):
        value = self.entries.get((client, address))
        return value[0] if value and value[1] > time.monotonic() else address


def resolve_real(domain, resolver, timeout=5):
    """Query an explicit LAN DNS server, bypassing local fake-IP answers."""
    ident = secrets.randbelow(65536)
    labels = b''.join(bytes([len(v)]) + v.encode('ascii') for v in domain.split('.'))
    packet = struct.pack('!6H', ident, 256, 1, 0, 0, 0) + labels + b'\0\0\1\0\1'
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.connect((str(ipaddress.IPv4Address(resolver)), 53))
        sock.send(packet)
        response = sock.recv(4096)
    if len(response) < 12 or response[:2] != packet[:2]:
        raise ValueError('Unmatched DNS reply')
    _, found = addresses(response)
    if not found:
        raise ValueError('No public API address from configured resolver')
    return found[0][0]
