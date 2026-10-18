"""Portable configuration, independent of UCI, procd and system proxy settings."""
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

DEFAULTS = dict(listen_port=10081, backend_port=10082, api_port=10090,
    idle_seconds=60, wakeup_timeout=45, request_timeout=30, max_connections=128,
    selection_mode='auto', preferred_node='', health_url='https://www.gstatic.com/generate_204',
    health_interval=300, health_timeout=5000)


def load(path):
    with open(path, encoding='utf-8') as stream:
        raw = json.load(stream)
    if not isinstance(raw, dict):
        raise ValueError('Configuration must be an object')
    cfg = dict(DEFAULTS, **raw)
    for key in ('listen_port', 'backend_port', 'api_port'):
        if type(cfg[key]) is not int or not 1024 <= cfg[key] <= 65535:
            raise ValueError(key + ' must be an unprivileged TCP port')
    if len({cfg[k] for k in ('listen_port', 'backend_port', 'api_port')}) != 3:
        raise ValueError('Listener, backend and controller ports must differ')
    for key in ('idle_seconds', 'wakeup_timeout', 'request_timeout', 'health_interval', 'health_timeout', 'max_connections'):
        if type(cfg[key]) not in (int, float) or not 1 <= cfg[key] <= 86400:
            raise ValueError(key + ' is outside its allowed range')
    if type(cfg['max_connections']) is not int:
        raise ValueError('max_connections must be an integer')
    private = [ipaddress.ip_network(x) for x in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
    def lan(value):
        try:
            ip = ipaddress.IPv4Address(value)
            return any(ip in net for net in private)
        except (ValueError, TypeError):
            return False
    clients = cfg.get('allowed_clients')
    local_only = cfg.get('listen_host') == '127.0.0.1' and clients == ['127.0.0.1']
    if not local_only:
        if not lan(cfg.get('listen_host')):
            raise ValueError('listen_host must be an RFC1918 address, or 127.0.0.1 with only the localhost client')
        if not isinstance(clients, list) or not clients or not all(lan(x) for x in clients):
            raise ValueError('allowed_clients must contain specific RFC1918 IPv4 addresses')
    if cfg['selection_mode'] == 'preferred':
        cfg['selection_mode'] = 'prefer'
    if cfg['selection_mode'] not in ('auto', 'prefer', 'fixed'):
        raise ValueError('selection_mode must be auto, prefer or fixed')
    if not isinstance(cfg['preferred_node'], str) or len(cfg['preferred_node']) > 256 or any(ord(c) < 32 for c in cfg['preferred_node']):
        raise ValueError('Invalid preferred_node')
    if re.sub(r'[\s_-]', '', cfg['preferred_node']).lower() in ('direct','reject','rejectdrop','compatible','pass','dns','global','portal','auto') or '`' in cfg['preferred_node']:
        raise ValueError('Reserved or invalid preferred_node')
    if cfg['selection_mode'] != 'auto' and not cfg['preferred_node']:
        raise ValueError('preferred_node is required for prefer/fixed mode')
    seed = cfg.get('subscription_file')
    if seed is not None:
        seed = Path(seed).expanduser()
        if not seed.is_absolute() or not seed.is_file() or seed.stat().st_size > 10 * 1024 * 1024:
            raise ValueError('subscription_file must be an existing absolute file no larger than 10 MiB')
        cfg['subscription_file'] = str(seed)
    for key in (('health_url',) if seed else ('subscription_url', 'health_url')):
        value = cfg.get(key)
        try:
            url = urlsplit(value)
            valid = url.scheme == 'https' and url.hostname and not url.username and not url.password and not url.fragment
            valid = valid and (url.port is None or 1 <= url.port <= 65535) and not any(c in url.netloc for c in '\\%')
            valid = valid and url.hostname.isascii()
            valid = valid and not any(ord(c) <= 32 for c in value)
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError(key + ' must be an HTTPS URL without userinfo or fragment')
    core = Path(cfg.get('core_path', '')).expanduser()
    if not core.is_absolute() or not core.is_file():
        raise ValueError('core_path must be an absolute path to an existing Mihomo executable')
    cfg['core_path'] = str(core)
    cfg['data_dir'] = str(Path(cfg.get('data_dir', Path(path).resolve().parent / 'runtime')).expanduser().resolve())
    return cfg


def render(cfg, secret):
    # JSON is a YAML subset accepted by Mihomo. No unsafe YAML interpolation.
    denied4 = ['0.0.0.0/8','10.0.0.0/8','100.64.0.0/10','127.0.0.0/8','169.254.0.0/16',
        '172.16.0.0/12','192.0.0.0/24','192.0.2.0/24','192.88.99.0/24','192.168.0.0/16',
        '198.18.0.0/15','198.51.100.0/24','203.0.113.0/24','224.0.0.0/3']
    denied6 = ['::/3','4000::/2','8000::/1','2001::/23','2001:db8::/32','2002::/16','3fff::/20']
    order = r'(?i)香港|🇭🇰|\bHK\b|Hong[ -]?Kong`(?i)日本|东京|大阪|🇯🇵|\bJP\b|Japan`^(?!REJECT$).*`^REJECT$'
    mode = cfg['selection_mode']
    exact = '^' + re.escape(cfg['preferred_node']) + '$'
    if mode == 'prefer':
        order = exact + '`' + order
    elif mode == 'fixed':
        order = exact + '`^REJECT$'
    groups = [{'name':'PORTAL','type':'select' if mode == 'fixed' else 'fallback',
        'use':['SUBSCRIPTION'],'proxies':['REJECT'],'filter':order,
        'url':cfg['health_url'],'interval':cfg['health_interval'],
        'timeout':cfg['health_timeout'],'lazy':False,'expected-status':204,
        'exclude-type':'Direct|Compatible|Pass|Dns','max-failed-times':2,
        'empty-fallback':'REJECT','disable-udp':True}]
    return {'port':cfg['backend_port'],'allow-lan':False,'bind-address':'127.0.0.1',
        'mode':'rule','log-level':'silent','ipv6':False,'find-process-mode':'off',
        'external-controller':f"127.0.0.1:{cfg['api_port']}",'secret':secret,
        'tun':{'enable':False},'sniffer':{'enable':False},
        'profile':{'store-selected':False,'store-fake-ip':False},
        'proxy-providers':{'SUBSCRIPTION':{'type':'file','path':'./providers/subscription.yaml',
            'exclude-type':'direct|compatible|pass|dns','health-check':{'enable':True,
                'url':cfg['health_url'],'interval':cfg['health_interval'],'timeout':cfg['health_timeout'],'lazy':False}}},
        'proxy-groups':groups,'rules':['DOMAIN-SUFFIX,localhost,REJECT'] +
            ['IP-CIDR,'+x+',REJECT' for x in denied4] + ['IP-CIDR6,'+x+',REJECT' for x in denied6]+['MATCH,PORTAL']}
