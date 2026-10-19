"""Portable configuration, independent of UCI, procd and system proxy settings."""
import ipaddress
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

DEFAULTS = dict(listen_port=10081, backend_port=10082, api_port=10090,
    idle_seconds=60, wakeup_timeout=45, request_timeout=30, max_connections=128,
    selection_mode='auto', preferred_node='', health_url='https://www.gstatic.com/generate_204',
    health_interval=300, health_timeout=5000, switch_threshold_ms=50, engine_mode='external')


def bundled_native_path():
    """Look only inside this app's bundle, never search PATH or download a core."""
    name = 'psportal-native.exe' if sys.platform == 'win32' else 'psportal-native'
    if not getattr(sys, 'frozen', False):
        return None
    roots = [Path(sys.executable).resolve().parent]
    if getattr(sys, '_MEIPASS', None):
        roots.append(Path(sys._MEIPASS))
    for root in roots:
        candidate = root / 'native' / name
        if candidate.is_file():
            return candidate
    return None


def load(path):
    with open(path, encoding='utf-8') as stream:
        raw = json.load(stream)
    return validate(raw, path)


def validate(raw, path):
    """Validate without network access or executing either engine."""
    if not isinstance(raw, dict):
        raise ValueError('Configuration must be an object')
    cfg = dict(DEFAULTS, **raw)
    from .nodes import validate_policies
    cfg['node_policies'] = validate_policies(cfg.get('node_policies', {}))
    if type(cfg.get('live_node_controls', False)) is not bool:
        raise ValueError('live_node_controls must be a boolean')
    existing = cfg.get('existing_proxy_port')
    if existing is not None:
        if type(existing) is not int or not 1024 <= existing <= 65535 or existing == cfg['listen_port']:
            raise ValueError('Existing proxy must use a distinct unprivileged loopback port')
        if cfg['engine_mode'] != 'external':
            raise ValueError('Existing proxy sharing requires external mode')
    if cfg['engine_mode'] not in ('external', 'embedded'):
        raise ValueError('engine_mode must be external or embedded')
    profile = cfg.get('profile_file')
    if profile:
        from .profiles import read_profile, validate_host_profile, host_overlay
        if cfg['engine_mode'] != 'external':
            raise ValueError('Complete profiles require the external Mihomo engine')
        if not isinstance(profile, str):
            raise ValueError('profile_file must be an existing absolute YAML file')
        profile = Path(profile).expanduser()
        if not profile.is_absolute() or not profile.is_file():
            raise ValueError('profile_file must be an existing absolute YAML file')
        if type(cfg.get('host_profile_overlay', False)) is not bool:
            raise ValueError('host_profile_overlay must be a boolean')
        data = read_profile(profile)
        validate_host_profile(host_overlay(data) if cfg.get('host_profile_overlay') else data)
        cfg['profile_file'] = str(profile)
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
    from .product_modes import validate_effective
    validate_effective(cfg)
    if profile:
        # Provider-only selection settings do not override a complete profile.
        cfg['selection_mode'], cfg['preferred_node'] = 'auto', ''
    if cfg['selection_mode'] == 'preferred':
        cfg['selection_mode'] = 'prefer'
    if cfg['selection_mode'] not in ('auto', 'prefer', 'fixed', 'fastest'):
        raise ValueError('selection_mode must be auto, prefer, fixed or fastest')
    if not isinstance(cfg['preferred_node'], str) or len(cfg['preferred_node']) > 256 or any(ord(c) < 32 for c in cfg['preferred_node']):
        raise ValueError('Invalid preferred_node')
    if re.sub(r'[\s_-]', '', cfg['preferred_node']).lower() in ('direct','reject','rejectdrop','compatible','pass','dns','global','portal','auto') or '`' in cfg['preferred_node']:
        raise ValueError('Reserved or invalid preferred_node')
    if type(cfg['switch_threshold_ms']) is not int or not 0 <= cfg['switch_threshold_ms'] <= 60000:
        raise ValueError('switch_threshold_ms must be an integer from 0 to 60000')
    if cfg['selection_mode'] in ('prefer', 'fixed') and not cfg['preferred_node']:
        raise ValueError('preferred_node is required for prefer/fixed mode')
    seed = None if profile else cfg.get('subscription_file')
    if seed not in (None, ''):
        if not isinstance(seed, str):
            raise ValueError('subscription_file must be an existing absolute file no larger than 10 MiB')
        seed = Path(seed).expanduser()
        if not seed.is_absolute() or not seed.is_file() or seed.stat().st_size > 10 * 1024 * 1024:
            raise ValueError('subscription_file must be an existing absolute file no larger than 10 MiB')
        cfg['subscription_file'] = str(seed)
    else:
        seed = None
        cfg.pop('subscription_file', None)
    for key in (('health_url',) if seed or profile or existing else ('subscription_url', 'health_url')):
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
    if cfg['engine_mode'] == 'external' and not existing:
        core = Path(cfg.get('core_path', '')).expanduser()
        if not core.is_absolute() or not core.is_file():
            raise ValueError('core_path must be an absolute path to an existing Mihomo executable')
        cfg['core_path'] = str(core)
    elif cfg['engine_mode'] == 'embedded':
        _validate_embedded(cfg, bool(seed))
    cfg['data_dir'] = str(Path(cfg.get('data_dir', Path(path).resolve().parent / 'runtime')).expanduser().resolve())
    return cfg


def _validate_embedded(cfg, has_local_provider):
    # Match the native schema's tighter limits without changing the established
    # external-Mihomo fallback. Native --check remains the authoritative check.
    for key in ('idle_seconds', 'wakeup_timeout', 'request_timeout', 'health_interval', 'health_timeout', 'max_connections'):
        if type(cfg[key]) is not int:
            raise ValueError(key + ' must be an integer for the embedded engine')
    clients = cfg['allowed_clients']
    if len(clients) > 256 or len(set(clients)) != len(clients):
        raise ValueError('Embedded engine requires at most 256 unique allowed_clients')
    if cfg['max_connections'] > 4096:
        raise ValueError('Embedded max_connections must not exceed 4096')
    name = cfg['preferred_node']
    if (len(name.encode('utf-8')) > 256 or name.strip() != name
            or any(unicodedata.category(c) in ('Cc', 'Cf') for c in name)
            or re.sub(r'[\s_-]', '', name).lower() in ('rematch', 'passrule')):
        raise ValueError('Invalid preferred_node for the embedded engine')
    from .policy import destination
    for key in (('health_url',) if has_local_provider else ('subscription_url', 'health_url')):
        value = cfg[key]
        url = urlsplit(value)
        if (len(value.encode('utf-8')) > 8192 or url.port not in (None, 443)
                or any(c.isspace() or unicodedata.category(c) == 'Cc' for c in value)
                or destination(url.hostname) not in ('external', 'name')):
            raise ValueError(key + ' must be a public HTTPS URL on port 443 for the embedded engine')
    value = cfg.get('native_path') or bundled_native_path()
    if not isinstance(value, (str, Path)):
        raise ValueError('native_path must identify an existing PSPortal native executable')
    native = Path(value).expanduser()
    if sys.platform == 'win32' and native.suffix.lower() != '.exe':
        raise ValueError('native_path must identify a native Windows .exe, not a script')
    if (not native.is_absolute() or not native.is_file()
            or (os.name != 'nt' and not os.access(native, os.X_OK))):
        raise ValueError('native_path must be an absolute path to an executable PSPortal native engine')
    cfg['native_path'] = str(native)


def render(cfg, secret):
    # JSON is a YAML subset accepted by Mihomo. No unsafe YAML interpolation.
    denied4 = ['0.0.0.0/8','10.0.0.0/8','100.64.0.0/10','127.0.0.0/8','169.254.0.0/16',
        '172.16.0.0/12','192.0.0.0/24','192.0.2.0/24','192.88.99.0/24','192.168.0.0/16',
        '198.18.0.0/15','198.51.100.0/24','203.0.113.0/24','224.0.0.0/3']
    denied6 = ['::/3','4000::/2','8000::/1','2001::/23','2001:db8::/32','2002::/16','3fff::/20']
    order = r'(?i)香港|🇭🇰|\bHK\b|Hong[ -]?Kong`(?i)日本|东京|大阪|🇯🇵|\bJP\b|Japan`^(?!REJECT$).*`^REJECT$'
    # The owned outer selector keeps the complete provider pool available for
    # live manual selection. The legacy region-first policy stays a fallback
    # group; fastest is selected from actual delay probes by CoreManager.
    groups = [{'name':'PORTAL','type':'select','use':['SUBSCRIPTION'],
        'proxies':['PORTAL-AUTO','REJECT'],'exclude-type':'Direct|Compatible|Pass|Dns',
        'empty-fallback':'REJECT','disable-udp':True},
        {'name':'PORTAL-AUTO','type':'fallback','use':['SUBSCRIPTION'],
        'proxies':['REJECT'],'filter':order,
        'url':cfg['health_url'],'interval':cfg['health_interval'],
        'timeout':cfg['health_timeout'],'lazy':False,'expected-status':204,
        'exclude-type':'Direct|Compatible|Pass|Dns','max-failed-times':2,
        'empty-fallback':'REJECT','disable-udp':True}]
    # live_node_controls remains accepted for existing saved configurations;
    # the owned PORTAL selector now always exposes the complete provider pool.
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
