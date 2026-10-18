"""Local interface discovery and predictable ports; never changes networking."""
from __future__ import annotations
import ipaddress
import re
import socket
import subprocess
import sys


def parse_interfaces(output: str, preferred: str = '') -> dict:
    candidates = []
    name = ''
    for line in output.splitlines():
        if line and not line[0].isspace():
            name = line.split(':', 1)[0]
        if not re.fullmatch(r'(?:en|eth|wlan)\d+', name):
            continue  # Excludes VPN, loopback and virtual bridge addresses.
        match = re.search(r'\binet (\d+\.\d+\.\d+\.\d+) netmask (0x[0-9a-fA-F]+|[\d.]+)', line)
        if not match:
            continue
        host, mask = match.groups()
        if mask.startswith('0x'):
            mask = str(ipaddress.IPv4Address(int(mask, 16)))
        try:
            interface = ipaddress.IPv4Interface(host + '/' + mask)
        except ValueError:
            continue
        private = any(interface.network.subnet_of(ipaddress.ip_network(net))
                      for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
        if private:
            candidates.append((name != preferred, name, interface))
    if not candidates:
        raise ValueError('Connect this Mac to a private Wi-Fi or Ethernet network first.')
    _, name, interface = sorted(candidates)[0]
    if not 24 <= interface.network.prefixlen <= 30:
        raise ValueError('This network needs an explicit device allowlist in Advanced settings.')
    return dict(host=str(interface.ip), interface=name, subnet=str(interface.network),
                clients=[str(ip) for ip in interface.network.hosts() if ip != interface.ip])


def discover_lan() -> dict:
    if sys.platform != 'darwin':
        raise ValueError('Automatic LAN setup is currently available on macOS. Use Advanced settings on this platform.')
    try:
        route = subprocess.run(['/sbin/route', '-n', 'get', 'default'], capture_output=True, text=True, timeout=2).stdout
        match = re.search(r'interface:\s+(\S+)', route)
        output = subprocess.run(['/sbin/ifconfig', '-a'], capture_output=True, text=True, timeout=2, check=True).stdout
        return parse_interfaces(output, match.group(1) if match else '')
    except (OSError, subprocess.SubprocessError):
        raise ValueError('Could not read local network information. Use Advanced settings.') from None


def available_port(host: str, preferred: int, excluded=()) -> int:
    ports = dict.fromkeys([preferred, *range(10081, 10113), *range(18081, 18113)])
    for port in ports:
        if type(port) is not int or not 1024 <= port <= 65535 or port in excluded:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((host, port))
            except OSError:
                continue
        return port
    raise ValueError('No available proxy port was found. Close the conflicting application or use Advanced settings.')
