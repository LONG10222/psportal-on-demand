"""Bounded, local YAML import; preserve complete outbound/group/rule semantics.

The LAN host owns its listener/controller. A profile requesting OS integration
is rejected explicitly instead of being silently converted to a node provider.
"""
from __future__ import annotations
import copy
import ipaddress
import json
from pathlib import Path

MAX_BYTES = 10 * 1024 * 1024


class ProfileError(ValueError):
    pass


def read_profile(path: Path) -> dict:
    try:
        import yaml
        if not Path(path).is_file():
            raise ProfileError('Profile must be a regular file')
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if not raw or len(raw) > MAX_BYTES:
            raise ProfileError('Profile must contain 1 byte to 10 MiB')
        raw = raw.decode('utf-8-sig')
        depth = aliases = events = 0
        for event in yaml.parse(raw):
            events += 1
            if isinstance(event, (yaml.SequenceStartEvent, yaml.MappingStartEvent)):
                depth += 1
            elif isinstance(event, (yaml.SequenceEndEvent, yaml.MappingEndEvent)):
                depth -= 1
            elif isinstance(event, yaml.AliasEvent):
                aliases += 1
            if depth > 64 or aliases > 128 or events > 100_000:
                raise ProfileError('Profile structure exceeds import limits')

        class Loader(yaml.SafeLoader):
            def construct_mapping(self, node, deep=False):
                keys = set()
                for key_node, _ in node.value:
                    if key_node.tag == 'tag:yaml.org,2002:merge':
                        continue
                    key = self.construct_object(key_node, deep=False)
                    if not isinstance(key, str) or key in keys:
                        raise ProfileError('Profile has duplicate or non-string keys')
                    keys.add(key)
                return super().construct_mapping(node, deep)

        data = yaml.load(raw, Loader=Loader)
        _bounded_json_tree(data)
        if not isinstance(data, dict):
            raise ProfileError('Profile must be a YAML object')
        for name in ('proxies', 'proxy-groups', 'rules'):
            if name in data and not isinstance(data[name], list):
                raise ProfileError('Invalid profile collection: ' + name)
        for name in ('proxy-providers', 'rule-providers', 'dns', 'tun'):
            if name in data and not isinstance(data[name], dict):
                raise ProfileError('Invalid profile collection: ' + name)
        return data
    except ProfileError:
        raise
    except ImportError:
        raise ProfileError('Install the pinned YAML runtime dependency') from None
    except Exception:
        # YAML parser exceptions can contain secret values and source fragments.
        raise ProfileError('Profile could not be read as supported YAML') from None


def _bounded_json_tree(data):
    active = set()
    count = size = 0

    def walk(value, depth=0):
        nonlocal count, size
        count += 1
        if count > 100_000 or depth > 64:
            raise ProfileError('Profile structure exceeds import limits')
        if isinstance(value, (dict, list)):
            if id(value) in active:
                raise ProfileError('Recursive YAML aliases are unsupported')
            active.add(id(value))
            items = value.items() if isinstance(value, dict) else enumerate(value)
            for key, item in items:
                if isinstance(value, dict):
                    if not isinstance(key, str):
                        raise ProfileError('Profile keys must be strings')
                    size += len(key.encode('utf-8'))
                walk(item, depth + 1)
            active.remove(id(value))
        elif isinstance(value, str):
            size += len(value.encode('utf-8'))
        elif type(value) not in (type(None), bool, int, float):
            raise ProfileError('Profile contains a non-JSON YAML value')
        if size > MAX_BYTES:
            raise ProfileError('Expanded profile exceeds import limits')
    walk(data)
    try:
        json.dumps(data, allow_nan=False)
    except (ValueError, TypeError):
        raise ProfileError('Profile contains invalid numeric values') from None


def inspect_profile(path: Path) -> dict:
    data = read_profile(path)
    return dict(nodes=len(data.get('proxies', [])), groups=len(data.get('proxy-groups', [])),
                rules=len(data.get('rules', [])),
                kind='profile' if any(k in data for k in ('proxy-groups', 'proxy-providers', 'rules', 'rule-providers', 'dns', 'tun', 'listeners', 'tunnels', 'tunnel', 'iptables')) else 'provider',
                node_rows=[(str(n.get('name', '')), str(n.get('type', ''))) for n in data.get('proxies', [])[:500] if isinstance(n, dict)],
                rule_rows=[str(rule) for rule in data.get('rules', [])[:500]],
                node_names=[str(n.get('name', '')) for n in data.get('proxies', []) if isinstance(n, dict)])


def validate_host_profile(data: dict) -> None:
    for key in ('tun', 'iptables'):
        section = data.get(key, {})
        if not isinstance(section, dict) or section.get('enable'):
            raise ProfileError('This profile requests system integration: ' + key)
    if data.get('dns', {}).get('listen'):
        raise ProfileError('This profile requests an additional DNS listener')
    if data.get('listeners') or data.get('tunnels') or data.get('tunnel'):
        raise ProfileError('Additional profile listeners require a separate supported mode')
    for kind in ('proxy-providers', 'rule-providers'):
        for provider in data.get(kind, {}).values():
            if not isinstance(provider, dict):
                raise ProfileError('Invalid provider entry')
            if provider.get('type') not in ('file', 'http', 'inline'):
                raise ProfileError('Unsupported provider source type')


def host_overlay(data: dict) -> dict:
    data = copy.deepcopy(data)
    data['tun'] = dict(data.get('tun', {}), enable=False)
    data['iptables'] = {'enable': False}
    if 'dns' in data:
        data['dns']['listen'] = ''  # Keep the internal resolver and its upstreams.
    if 'ntp' in data:
        data['ntp'] = {'enable': False, 'write-to-system': False}
    for key in ('listeners', 'tunnels', 'tunnel', 'authentication'):
        data.pop(key, None)
    return data


def render_profile(cfg: dict, secret: str, runtime: Path) -> dict:
    source = Path(cfg['profile_file'])
    data = read_profile(source)
    if cfg.get('host_profile_overlay'):
        data = host_overlay(data)
    validate_host_profile(data)
    data = copy.deepcopy(data)
    # Preserve node options, groups, rules and supported DNS resolution options.
    # Never modify the user's original file. Network-entry overrides are explicit.
    data.update({'port': cfg['backend_port'], 'socks-port': 0, 'mixed-port': 0,
                 'redir-port': 0, 'tproxy-port': 0, 'allow-lan': False,
                 'bind-address': '127.0.0.1', 'external-controller': f"127.0.0.1:{cfg['api_port']}",
                 'secret': secret, 'log-level': 'silent'})
    for key in ('external-controller-unix', 'external-controller-pipe', 'external-controller-tls',
                'external-ui', 'external-ui-url', 'external-doh-server'):
        data.pop(key, None)
    (runtime / 'imported').mkdir(mode=0o700, exist_ok=True)
    total_bytes = 0
    for kind in ('proxy-providers', 'rule-providers'):
        for index, provider in enumerate(data.get(kind, {}).values()):
            relative = f'imported/{kind}-{index}.yaml'
            if provider.get('type') == 'file':
                path = provider.get('path')
                if not isinstance(path, str):
                    raise ProfileError('A local provider requires a relative path')
                origin = (source.parent / path).resolve()
                if Path(path).is_absolute() or not origin.is_relative_to(source.parent.resolve()):
                    raise ProfileError('Local provider must stay inside the imported profile directory')
                if not origin.is_file():
                    raise ProfileError('Local provider must be a regular file')
                with origin.open('rb') as stream:
                    raw = stream.read(MAX_BYTES + 1)
                if not raw or len(raw) > MAX_BYTES:
                    raise ProfileError('Local provider is empty or oversized')
                total_bytes += len(raw)
                if total_bytes > 5 * MAX_BYTES:
                    raise ProfileError('Imported provider bundle exceeds 50 MiB')
                from .core import atomic_private
                atomic_private(runtime / relative, raw)
            if provider.get('type') in ('file', 'http'):
                provider['path'] = './' + relative
    return data


def connection_details(values: dict) -> dict:
    try:
        host = str(ipaddress.IPv4Address(values['listen_host']))
        port = values['listen_port']
        private = any(ipaddress.IPv4Address(host) in ipaddress.ip_network(net)
                      for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '127.0.0.0/8'))
        if not private or type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        raise ProfileError('Configure an address and port first.') from None
    return dict(protocol='http', host=host, port=port, local_test_only=host.startswith('127.'),
                allowed_clients=list(values.get('allowed_clients', [])))


def client_config(values: dict) -> dict:
    details = connection_details(values)
    return {'proxies': [{'name': 'OnDemand LAN', 'type': 'http', 'server': details['host'], 'port': details['port']}],
            'proxy-groups': [{'name': 'LAN Proxy', 'type': 'select', 'proxies': ['OnDemand LAN', 'DIRECT']}],
            'rules': ['IP-CIDR,10.0.0.0/8,DIRECT', 'IP-CIDR,172.16.0.0/12,DIRECT',
                      'IP-CIDR,192.168.0.0/16,DIRECT', 'MATCH,LAN Proxy']}
