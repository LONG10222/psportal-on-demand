"""Local interface discovery and predictable ports; never changes networking."""
from __future__ import annotations
import ipaddress
import json
import re
import socket
import subprocess
import sys
from pathlib import Path


_READ_ERROR = 'Could not read local network information. Use Advanced settings.'
_AMBIGUOUS = 'Could not safely identify one active physical LAN interface. Use Advanced settings.'
_NO_LAN = 'Connect this computer to a private Wi-Fi or Ethernet network first.'
_ALLOWLIST = 'This network needs an explicit device allowlist in Advanced settings.'
_PRIVATE = tuple(ipaddress.ip_network(net) for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))

# Constant, read-only commands: no interface names or other discovered data are
# ever interpolated into PowerShell. Numeric CIM enums are locale-independent.
_WINDOWS_LAN_QUERY = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$metrics = @{}
Get-NetIPInterface -AddressFamily IPv4 | ForEach-Object { $metrics[[int]$_.InterfaceIndex] = $_.InterfaceMetric }
$adapters = @(Get-NetAdapter -Physical | ForEach-Object {
    @{index=[int]$_.ifIndex; name=[string]$_.Name; up=([int]$_.InterfaceOperationalStatus -eq 1);
      hardware=[bool]$_.HardwareInterface; virtual=[bool]$_.Virtual; type=[int]$_.InterfaceType}
})
$addresses = @(Get-NetIPAddress -AddressFamily IPv4 | ForEach-Object {
    @{index=[int]$_.InterfaceIndex; address=[string]$_.IPAddress; prefix=[int]$_.PrefixLength;
      preferred=([int]$_.AddressState -eq 4); skip=[bool]$_.SkipAsSource}
})
$routes = @(Get-NetRoute -AddressFamily IPv4 -PolicyStore ActiveStore | ForEach-Object {
    @{index=[int]$_.InterfaceIndex; destination=[string]$_.DestinationPrefix; gateway=[string]$_.NextHop;
      metric=$_.RouteMetric; interface_metric=$metrics[[int]$_.InterfaceIndex]}
})
@{adapters=$adapters; addresses=$addresses; routes=$routes} | ConvertTo-Json -Depth 5 -Compress
'''


def _bounded_json(output: str):
    """Reject oversized, duplicate-key, deeply nested or non-JSON command data."""
    def object_pairs(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                raise ValueError(_READ_ERROR)
            data[key] = value
        return data

    if not isinstance(output, str) or not 0 < len(output) <= 262144:
        raise ValueError(_READ_ERROR)
    try:
        data = json.loads(output.lstrip('\ufeff'), object_pairs_hook=object_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(_READ_ERROR)))
        pending = [(data, 0)]
        count = 0
        while pending:
            value, depth = pending.pop()
            count += 1
            if count > 16384 or depth > 12 or (isinstance(value, str) and len(value) > 4096):
                raise ValueError(_READ_ERROR)
            if isinstance(value, (list, dict)):
                pending.extend((item, depth + 1) for item in (value.values() if isinstance(value, dict) else value))
        return data
    except (ValueError, RecursionError):
        raise ValueError(_READ_ERROR) from None


def _rows(value, maximum=1024):
    if not isinstance(value, list) or len(value) > maximum or any(not isinstance(row, dict) for row in value):
        raise ValueError(_READ_ERROR)
    return value


def _integer(value, minimum=0, maximum=2**32 - 1):
    return type(value) is int and minimum <= value <= maximum


def _lan_result(name, host, prefix):
    if not isinstance(host, str) or not _integer(prefix, 0, 32):
        raise ValueError(_AMBIGUOUS)
    try:
        address = ipaddress.IPv4Address(host)
        interface = ipaddress.IPv4Interface((address, prefix))
    except ValueError:
        raise ValueError(_AMBIGUOUS) from None
    if not any(interface.network.subnet_of(network) for network in _PRIVATE):
        raise ValueError(_NO_LAN)
    if not 24 <= prefix <= 30:
        raise ValueError(_ALLOWLIST)
    if address in (interface.network.network_address, interface.network.broadcast_address):
        raise ValueError(_AMBIGUOUS)
    return dict(host=str(address), interface=name, subnet=str(interface.network),
                clients=[str(ip) for ip in interface.network.hosts() if ip != address])


def _preferred_route(routes):
    if not routes:
        raise ValueError(_NO_LAN)
    minimum = min(route['metric'] for route in routes)
    best = [route for route in routes if route['metric'] == minimum]
    if len(best) != 1:
        raise ValueError(_AMBIGUOUS)
    return best[0]


def _check_gateway(route, result):
    try:
        if not isinstance(route.get('gateway'), str):
            raise ValueError()
        gateway = ipaddress.IPv4Address(route['gateway'])
        network = ipaddress.IPv4Network(result['subnet'])
        if gateway not in network or str(gateway) == result['host'] or gateway in (network.network_address, network.broadcast_address):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError(_AMBIGUOUS) from None
    return result


def parse_windows_interfaces(output: str) -> dict:
    """Select one physical Windows LAN from locale-independent CIM JSON."""
    data = _bounded_json(output)
    if not isinstance(data, dict):
        raise ValueError(_READ_ERROR)
    adapters = _rows(data.get('adapters'), 256)
    addresses = _rows(data.get('addresses'))
    routes = []
    for row in _rows(data.get('routes')):
        # A split default often belongs to a VPN; do not silently choose a LAN.
        if row.get('destination') in ('0.0.0.0/1', '128.0.0.0/1'):
            raise ValueError(_AMBIGUOUS)
        if row.get('destination') != '0.0.0.0/0':
            continue
        if not all(_integer(row.get(key)) for key in ('metric', 'interface_metric')) or not _integer(row.get('index'), 1):
            raise ValueError(_AMBIGUOUS)
        routes.append(dict(row, metric=row['metric'] + row['interface_metric']))
    route = _preferred_route(routes)
    matches = [row for row in adapters if _integer(row.get('index'), 1) and row['index'] == route['index']]
    if len(matches) != 1:
        raise ValueError(_AMBIGUOUS)
    adapter = matches[0]
    name = adapter.get('name')
    if (adapter.get('up') is not True or adapter.get('hardware') is not True or adapter.get('virtual') is not False
            or not _integer(adapter.get('type')) or adapter['type'] not in (6, 71)
            or not isinstance(name, str) or not name or len(name) > 256 or any(ord(c) < 32 for c in name)):
        raise ValueError(_AMBIGUOUS)
    matches = [row for row in addresses if _integer(row.get('index'), 1) and row['index'] == route['index']
               and row.get('preferred') is True and row.get('skip') is False]
    if len(matches) != 1:
        raise ValueError(_AMBIGUOUS)
    return _check_gateway(route, _lan_result(name, matches[0].get('address'), matches[0].get('prefix')))


def _linux_physical(name: str, sysfs_root: Path) -> bool:
    """Verify a real sysfs hardware device, not a guessed interface-name prefix."""
    if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}', name) or name in ('.', '..'):
        return False
    try:
        entry = sysfs_root / name
        devices = (sysfs_root.parents[1] / 'devices').resolve(strict=True)
        device = (entry / 'device').resolve(strict=True)
        resolved = entry.resolve(strict=True)
        def scalar(filename):
            with (entry / filename).open() as stream:
                return stream.read(33).strip()
        return (device.is_dir() and device.is_relative_to(devices)
                and resolved.is_relative_to(devices) and not resolved.is_relative_to(devices / 'virtual')
                and not device.is_relative_to(devices / 'virtual')
                and scalar('type') == '1' and scalar('operstate') == 'up')
    except (OSError, RuntimeError, ValueError):
        return False


def _linux_main_routing(rule_output: str):
    # WireGuard and other VPNs can use policy tables while retaining the main
    # table's physical default. Require ordinary routing before relying on it.
    expected = {0: ('local', 255), 32766: ('main', 254), 32767: ('default', 253)}
    seen = set()
    for rule in _rows(_bounded_json(rule_output), 256):
        priority = rule.get('priority')
        if (not _integer(priority) or priority not in expected or priority in seen
                or rule.get('src') != 'all' or rule.get('table') not in expected[priority]
                or set(rule) - {'priority', 'src', 'table', 'protocol'}):
            raise ValueError(_AMBIGUOUS)
        seen.add(priority)
    if not {0, 32766}.issubset(seen):
        raise ValueError(_AMBIGUOUS)


def parse_linux_interfaces(address_output: str, route_output: str, sysfs_root: Path = Path('/sys/class/net'),
                           *, rule_output: str | None = None) -> dict:
    """Read iproute2 JSON plus sysfs; never infer a prefix or trust a virtual NIC."""
    if rule_output is not None:
        _linux_main_routing(rule_output)
    interfaces = _rows(_bounded_json(address_output), 256)
    routes = []
    for row in _rows(_bounded_json(route_output)):
        if row.get('dst') in ('0.0.0.0/1', '128.0.0.0/1'):
            raise ValueError(_AMBIGUOUS)
        if row.get('dst') not in ('default', '0.0.0.0/0'):
            continue
        metric = row.get('metric', 0)  # iproute2 omits an actual zero metric.
        if (not _integer(metric) or row.get('type', 'unicast') != 'unicast'
                or row.get('nexthops') or row.get('flags', []) or not isinstance(row.get('dev'), str)):
            raise ValueError(_AMBIGUOUS)
        routes.append(dict(row, metric=metric))
    route = _preferred_route(routes)
    name = route['dev']
    matches = [row for row in interfaces if row.get('ifname') == name]
    if len(matches) != 1 or not _linux_physical(name, Path(sysfs_root)):
        raise ValueError(_AMBIGUOUS)
    row = matches[0]
    flags = row.get('flags')
    if (row.get('operstate') != 'UP' or row.get('link_type') != 'ether' or row.get('master')
            or not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags)
            or not {'UP', 'LOWER_UP'}.issubset(flags)
            or {'LOOPBACK', 'POINTOPOINT'}.intersection(flags) or row.get('linkinfo')):
        raise ValueError(_AMBIGUOUS)
    addresses = [item for item in _rows(row.get('addr_info'), 256) if item.get('family') == 'inet'
                 and item.get('scope') == 'global' and not any(item.get(key) for key in ('tentative', 'deprecated', 'dadfailed', 'secondary'))
                 and item.get('preferred_life_time') != 0 and item.get('valid_life_time') != 0]
    if 'prefsrc' in route:
        addresses = [item for item in addresses if item.get('local') == route['prefsrc']]
    if len(addresses) != 1:
        raise ValueError(_AMBIGUOUS)
    return _check_gateway(route, _lan_result(name, addresses[0].get('local'), addresses[0].get('prefixlen')))


def parse_interfaces(output: str, preferred: str = '') -> dict:
    """Use only the verified, active default interface; never guess a fallback."""
    if not isinstance(output, str) or not 0 < len(output) <= 262144:
        raise ValueError(_READ_ERROR)
    if not isinstance(preferred, str) or not re.fullmatch(r'(?:en|eth|wlan)\d+', preferred):
        raise ValueError(_AMBIGUOUS)
    interfaces = []
    current = None
    for line in output.splitlines():
        if line and not line[0].isspace():
            current = None
            header = re.match(r'^([^:]+): flags=([0-9a-fA-F]+)(?:<[^>]*>)?\s', line)
            if header and header.group(1) == preferred:
                current = dict(flags=int(header.group(2), 16), addresses=[], states=[])
                interfaces.append(current)
        if current is None:
            continue
        state = re.fullmatch(r'\s*status:\s*(\S+)\s*', line)
        if state:
            current['states'].append(state.group(1))
        match = re.match(r'\s*inet (\S+) netmask (\S+)(?:\s|$)', line)
        if match:
            current['addresses'].append(match.groups())
    if len(interfaces) != 1:
        raise ValueError(_AMBIGUOUS)
    interface = interfaces[0]
    # IFF_UP and IFF_RUNNING are required. Loopback/point-to-point interfaces,
    # missing carrier status and multiple IPv4 aliases need explicit settings.
    flags = interface['flags']
    if (flags & 0x41 != 0x41 or flags & 0x18 or interface['states'] != ['active']
            or len(interface['addresses']) != 1):
        raise ValueError(_AMBIGUOUS)
    host, mask = interface['addresses'][0]
    try:
        if mask.startswith('0x'):
            mask = str(ipaddress.IPv4Address(int(mask, 16)))
        address = ipaddress.IPv4Interface(host + '/' + mask)
    except ValueError:
        raise ValueError(_AMBIGUOUS) from None
    return _lan_result(preferred, str(address.ip), address.network.prefixlen)


def discover_lan() -> dict:
    if sys.platform == 'win32' or sys.platform.startswith('linux'):
        try:
            def read(command):
                return subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                      timeout=5, check=True, shell=False).stdout
            if sys.platform == 'win32':
                return parse_windows_interfaces(read(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', _WINDOWS_LAN_QUERY]))
            return parse_linux_interfaces(read(['ip', '-j', '-4', 'address', 'show']),
                                          read(['ip', '-j', '-4', 'route', 'show', 'table', 'main']),
                                          rule_output=read(['ip', '-j', '-4', 'rule', 'show']))
        except (OSError, UnicodeError, subprocess.SubprocessError):
            raise ValueError(_READ_ERROR) from None
    if sys.platform != 'darwin':
        raise ValueError('Automatic LAN setup is unavailable on this platform. Use Advanced settings.')
    try:
        route = subprocess.run(['/sbin/route', '-n', 'get', 'default'], capture_output=True,
                               text=True, encoding='utf-8', timeout=2, check=True, shell=False).stdout
        interfaces = re.findall(r'^\s*interface:\s*(\S+)\s*$', route, re.MULTILINE)
        if len(interfaces) != 1:
            raise ValueError(_AMBIGUOUS)
        output = subprocess.run(['/sbin/ifconfig', '-a'], capture_output=True, text=True,
                                encoding='utf-8', timeout=2, check=True, shell=False).stdout
        return parse_interfaces(output, interfaces[0])
    except (OSError, UnicodeError, subprocess.SubprocessError):
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
