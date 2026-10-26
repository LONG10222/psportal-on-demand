"""Read-only discovery and reuse of an existing local HTTP proxy endpoint."""
import os
import re
import subprocess
import sys
from pathlib import Path


def _local_http_proxy(value: str) -> dict | None:
    """Accept a literal loopback HTTP endpoint only; never resolve localhost."""
    if not isinstance(value, str) or len(value) > 256:
        return None
    match = re.fullmatch(r'(?:http://)?(?:127\.0\.0\.1|localhost):([0-9]{1,5})/?', value, re.IGNORECASE | re.ASCII)
    if match and 1024 <= int(match.group(1)) <= 65535:
        return {'host': '127.0.0.1', 'port': int(match.group(1))}
    return None


def _windows_proxy_server(value: str) -> dict | None:
    if not isinstance(value, str) or not value or len(value) > 4096:
        return None
    if '=' not in value:
        return _local_http_proxy(value)
    entries = {}
    for part in value.split(';'):
        match = re.fullmatch(r'(http|https|ftp|socks)=([^;\s]+)', part, re.IGNORECASE | re.ASCII)
        if not match or match.group(1).lower() in entries:
            return None
        entries[match.group(1).lower()] = match.group(2)
    return _local_http_proxy(entries.get('http'))


def _detect_windows_proxy() -> dict | None:
    # HKCU only; never write Internet Settings, inspect machine policies or run PAC.
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Internet Settings',
                            0, winreg.KEY_READ) as key:
            enabled, kind = winreg.QueryValueEx(key, 'ProxyEnable')
            if kind != winreg.REG_DWORD or type(enabled) is not int or enabled != 1:
                return None
            try:
                pac, _ = winreg.QueryValueEx(key, 'AutoConfigURL')
                if pac:
                    return None
            except FileNotFoundError:
                pass
            server, kind = winreg.QueryValueEx(key, 'ProxyServer')
            if kind == winreg.REG_SZ:
                return _windows_proxy_server(server)
    except (ImportError, OSError, ValueError, TypeError):
        pass
    return None


def _detect_linux_proxy() -> dict | None:
    # A process's HTTP proxy is explicit configuration. Conflicting/malformed
    # variables fail closed rather than silently choosing a different proxy.
    values = [os.environ[key] for key in ('http_proxy', 'HTTP_PROXY') if os.environ.get(key)]
    if values:
        # CGI treats HTTP_PROXY as untrusted request input.
        if os.environ.get('REQUEST_METHOD'):
            return None
        proxies = [_local_http_proxy(value) for value in values]
        return proxies[0] if proxies[0] is not None and all(proxy == proxies[0] for proxy in proxies) else None
    try:
        def get(schema, key):
            result = subprocess.run(['gsettings', 'get', schema, key], capture_output=True,
                                    text=True, encoding='utf-8', timeout=2, check=True, shell=False)
            if not isinstance(result.stdout, str) or len(result.stdout) > 512:
                raise ValueError()
            return result.stdout.strip()
        # Parse only fixed scalar values, never eval GVariant, a shell or a PAC.
        if get('org.gnome.system.proxy', 'mode') != "'manual'":
            return None
        if get('org.gnome.system.proxy.http', 'use-authentication') != 'false':
            return None
        host = get('org.gnome.system.proxy.http', 'host')
        if host not in ("'127.0.0.1'", "'localhost'"):
            return None
        port = get('org.gnome.system.proxy.http', 'port')
        return _local_http_proxy(host[1:-1] + ':' + port)
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        return None


def _macos_global_proxy(output: str) -> dict | None:
    """Read only scutil's top-level HTTP proxy, ignoring scoped dictionaries."""
    if not isinstance(output, str) or not 0 < len(output) <= 262144:
        return None
    fields = {}
    depth = 0
    seen_root = False
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not seen_root:
            if line != '<dictionary> {':
                return None
            seen_root, depth = True, 1
            continue
        if depth == 0:
            return None
        if line == '}':
            depth -= 1
            continue
        if re.fullmatch(r'[^:]+\s*:\s*<(?:dictionary|array)>\s*\{', line):
            depth += 1
            if depth > 16:
                return None
            continue
        if depth == 1:
            match = re.fullmatch(r'(HTTPEnable|HTTPProxy|HTTPPort|ProxyAutoConfigEnable|ProxyAutoDiscoveryEnable)\s*:\s*(\S+)', line)
            if match:
                key, value = match.groups()
                if key in fields:
                    return None
                fields[key] = value
    if not seen_root or depth != 0 or fields.get('HTTPEnable') != '1':
        return None
    if (fields.get('HTTPProxy') not in ('127.0.0.1', 'localhost')
            or any(fields.get(key, '0') != '0' for key in ('ProxyAutoConfigEnable', 'ProxyAutoDiscoveryEnable'))):
        return None
    return _local_http_proxy(fields.get('HTTPProxy', '') + ':' + fields.get('HTTPPort', ''))


def detect_system_proxy() -> dict | None:
    if sys.platform == 'win32': return _detect_windows_proxy()
    if sys.platform.startswith('linux'): return _detect_linux_proxy()
    if sys.platform != 'darwin': return None
    try:
        result = subprocess.run(['/usr/sbin/scutil', '--proxy'], capture_output=True, text=True,
                                encoding='utf-8', timeout=2, check=True, shell=False)
        return _macos_global_proxy(result.stdout)
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        pass
    return None


def clash_accounting_path() -> Path | None:
    """Standard upstream app-data path only; do not search profiles or secrets.

    Verified against clash-verge-rev/src-tauri/src/utils/dirs.rs (app_home_dir,
    PROFILE_YAML) and dirs-rs data_dir: RoamingAppData on Windows; XDG data on
    Linux. Portable/custom/dev installations intentionally need an explicit path.
    """
    identifier = 'io.github.clash-verge-rev.clash-verge-rev'
    if sys.platform == 'darwin':
        root = Path.home() / 'Library/Application Support'
    elif sys.platform == 'win32':
        value = os.environ.get('APPDATA', '')
        if not value or not Path(value).is_absolute(): return None
        root = Path(value)
    elif sys.platform.startswith('linux'):
        value = os.environ.get('XDG_DATA_HOME', '')
        root = Path(value) if value and Path(value).is_absolute() else Path.home() / '.local/share'
    else:
        return None
    return root / identifier / 'profiles.yaml'


def read_clash_accounting(path: Path | None = None) -> dict | None:
    """Read only the active profile's cached counters; never return its URL/token."""
    if path is None:
        path = clash_accounting_path()
        if path is None: return None
    try:
        from .profiles import read_profile
        data = read_profile(path)
        current = data.get('current')
        items = data.get('items')
        if not isinstance(current, str) or not isinstance(items, list): return None
        for entry in items:
            if not isinstance(entry, dict) or entry.get('uid') != current: continue
            extra = entry.get('extra')
            if not isinstance(extra, dict): return None
            info = {key: extra[key] for key in ('upload', 'download', 'total', 'expire')
                    if type(extra.get(key)) is int and 0 <= extra[key] <= (253402300799 if key == 'expire' else 2**63-1)}
            if not info: return None
            info['source_kind'] = 'clash-cache'
            if isinstance(entry.get('name'), str):
                info['provider_name'] = ''.join(c for c in entry['name'] if ord(c) >= 32)[:120]
            updated = entry.get('updated')
            if type(updated) is int and 0 < updated <= 253402300799: info['updated_at'] = updated
            return info
    except (ValueError, OSError):
        pass
    return None


def clash_subscription_source(path=None):
    """Private descriptor for the current profile only; no controller mutations."""
    from .subscription_monitor import descriptor
    path = path or clash_accounting_path()
    cached = read_clash_accounting(path) if path else None
    try:
        from .profiles import read_profile
        data = read_profile(path)
        current = data.get('current')
        if isinstance(current, str):
            for entry in data.get('items', []):
                if isinstance(entry, dict) and entry.get('uid') == current:
                    name = entry.get('name') if isinstance(entry.get('name'), str) else ''
                    return descriptor(entry.get('url',''), cached, identity='clash:'+current, name=name, linked=True)
    except (OSError, ValueError, TypeError): pass
    return descriptor(cached=cached, identity='clash-unavailable', linked=True)


class ExistingProxy:
    """Owns no core process and never calls another application's controller."""
    def __init__(self, config):
        self.port = config['existing_proxy_port']
        self.active = 0
        self.closing = False

    def status(self):
        return {'core_state': 'external', 'node_management': False,
                'selection_mode': 'delegated', 'selected_node': '', 'nodes': [],
                'error': '', 'preparing': False}

    def start_monitor(self): pass

    async def acquire(self):
        if self.closing: raise RuntimeError('Proxy is stopping')
        self.active += 1
        return '127.0.0.1', self.port

    async def release(self): self.active = max(0, self.active-1)

    async def close(self): self.closing = True
