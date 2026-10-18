"""Read-only discovery and reuse of an existing local HTTP proxy endpoint."""
import re
import subprocess
import sys
from pathlib import Path


def detect_system_proxy() -> dict | None:
    if sys.platform != 'darwin': return None
    try:
        result = subprocess.run(['/usr/sbin/scutil', '--proxy'], capture_output=True, text=True, timeout=2)
        fields = dict(re.findall(r'^\s*(HTTPEnable|HTTPProxy|HTTPPort)\s*:\s*(\S+)', result.stdout, re.MULTILINE))
        if fields.get('HTTPEnable') == '1' and fields.get('HTTPProxy') in ('127.0.0.1', 'localhost'):
            port = int(fields.get('HTTPPort', '0'))
            if 1024 <= port <= 65535:
                return {'host': '127.0.0.1', 'port': port}
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def read_clash_accounting(path: Path | None = None) -> dict | None:
    """Read only the active profile's cached counters; never return its URL/token."""
    if path is None:
        if sys.platform != 'darwin': return None
        path = Path.home() / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/profiles.yaml'
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


class ExistingProxy:
    """Owns no core process and never calls another application's controller."""
    def __init__(self, config):
        self.port = config['existing_proxy_port']
        self.active = 0
        self.closing = False

    def start_monitor(self): pass

    async def acquire(self):
        if self.closing: raise RuntimeError('Proxy is stopping')
        self.active += 1
        return '127.0.0.1', self.port

    async def release(self): self.active = max(0, self.active-1)

    async def close(self): self.closing = True
