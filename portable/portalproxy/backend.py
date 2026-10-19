"""Explicit desktop engine dispatch; external remains the default.

The experimental child embeds Mihomo adapters in one native process. It does not
receive Python-only settings, core paths, or an unused subscription URL.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading

from . import config
from .process_env import external_environment


NATIVE_FIELDS = frozenset((
    'listen_host', 'listen_port', 'allowed_clients', 'subscription_url',
    'subscription_file', 'selection_mode', 'preferred_node', 'backend_port',
    'api_port', 'idle_seconds', 'wakeup_timeout', 'request_timeout',
    'max_connections', 'health_url', 'health_interval', 'health_timeout', 'switch_threshold_ms',
))


def external_command(path: Path) -> list[str]:
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--backend', '--config', str(path), '--desktop-child']
    return [sys.executable, '-u', '-m', 'portalproxy', '--config', str(path), '--desktop-child']


def native_values(values: dict) -> dict:
    """Project only the documented native schema, never copy unknown fields."""
    result = {key: values[key] for key in NATIVE_FIELDS if key in values}
    if result.get('subscription_file'):
        result.pop('subscription_url', None)
    else:
        result.pop('subscription_file', None)
    return result


@dataclass
class Launch:
    command: list[str]
    embedded: bool = False
    temporary: tempfile.TemporaryDirectory | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def cleanup(self):
        with self._lock:
            if self.temporary is not None:
                self.temporary.cleanup()
                self.temporary = None


def prepare_launch(path: Path, values: dict, *, check=False) -> Launch:
    if values.get('engine_mode', 'external') == 'external':
        command = external_command(path)
        if check:
            command.append('--check')
        return Launch(command)
    cfg = config.validate(values, path)
    temporary = tempfile.TemporaryDirectory(prefix='psportal-native-')
    launch = Launch([], embedded=True, temporary=temporary)
    try:
        session_path = Path(temporary.name) / 'config.json'
        descriptor = os.open(session_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(native_values(cfg), stream, ensure_ascii=False)
            stream.write('\n')
        launch.command = [cfg['native_path'], '--config', str(session_path),
                          '--check' if check else '--desktop-child']
        return launch
    except BaseException:
        launch.cleanup()
        raise


@contextmanager
def native_library_path():
    """Temporarily restore Windows' DLL path when spawning outside a bundle."""
    setter = None
    if sys.platform == 'win32' and getattr(sys, 'frozen', False):
        import ctypes
        setter = ctypes.windll.kernel32.SetDllDirectoryW
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_int
        if not setter(None):
            raise OSError('Unable to prepare native engine library search path')
    try:
        yield
    finally:
        if setter is not None:
            setter(getattr(sys, '_MEIPASS', None))


def spawn(launch: Launch, **kwargs) -> subprocess.Popen:
    """Never invoke a shell or let frozen library overrides reach native code."""
    if launch.embedded:
        kwargs['env'] = external_environment()
        with native_library_path():
            return subprocess.Popen(launch.command, **kwargs)
    return subprocess.Popen(launch.command, **kwargs)


def is_ready(line: str, values: dict) -> bool:
    if values.get('engine_mode', 'external') != 'embedded':
        return line.startswith(f"Proxy ready at {values.get('listen_host')}:{values.get('listen_port', 10081)};")
    try:
        event = json.loads(line)
    except (TypeError, ValueError):
        return False
    return (isinstance(event, dict) and event.get('event') == 'ready'
            and event.get('engine') == 'mihomo-adapters'
            and event.get('listen_host') == values.get('listen_host')
            and type(event.get('listen_port')) is int
            and event['listen_port'] == values.get('listen_port', 10081))


def run_native(path: Path, values: dict, *, check=False, desktop_child=False) -> int:
    """CLI bridge with the same EOF lifetime contract as the desktop window."""
    launch = prepare_launch(path, values, check=check)
    process = None
    handlers = {}
    stop_lock = threading.Lock()

    def stop(*_):
        with stop_lock:
            if process is not None and process.stdin is not None:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass

    try:
        process = spawn(launch, stdin=subprocess.PIPE)
        for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
            sig = getattr(signal, name, None)
            if sig is not None:
                handlers[sig] = signal.signal(sig, stop)
        if check:
            stop()
        elif desktop_child:
            def watch_parent():
                try:
                    while True:
                        line = sys.stdin.readline(4097)
                        if not line:
                            break
                        if line.strip() == 'stop':
                            break
                        if len(line.encode('utf-8')) > 4096:
                            break
                        if process.stdin is not None:
                            process.stdin.write(line.encode('utf-8'))
                            process.stdin.flush()
                finally:
                    stop()
            threading.Thread(target=watch_parent, daemon=True).start()
        return process.wait()
    finally:
        stop()
        if process is not None and process.poll() is None:
            # Wait for the single native owner to finish; do not abandon it.
            process.wait()
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        launch.cleanup()


def parse_status(line: str) -> dict | None:
    """Type-check bounded runtime records before they reach any UI widget."""
    import ipaddress
    import math
    from .runtime import MAX_STATUS_BYTES
    def string(value, limit, empty=True):
        return (isinstance(value, str) and (empty or bool(value))
                and len(value.encode('utf-8')) <= limit and not any(ord(c) < 32 for c in value))
    def integer(value, maximum=86400):
        return type(value) is int and 0 <= value <= maximum
    try:
        if not isinstance(line, str) or len(line.encode('utf-8')) > MAX_STATUS_BYTES:
            return None
        value = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict) or value.get('event') != 'status':
            return None
        if value.get('state') not in ('preparing','listening','waking','forwarding','error','stopped'):
            return None
        for key in ('connected_clients', 'active_connections'):
            if not integer(value.get(key)):
                return None
        if value['connected_clients'] > value['active_connections']:
            return None
        for key in ('running', 'busy', 'node_management', 'preparing', 'probe_complete'):
            if key in value and type(value[key]) is not bool:
                return None
        for key in ('selected_node', 'selection_group'):
            if key in value and not string(value[key], 256):
                return None
        for key in ('error', 'command_error'):
            if key in value and not string(value[key], 1024):
                return None
        for key in ('address', 'listen_host', 'core_state', 'engine', 'engine_version'):
            if key in value and not string(value[key], 128):
                return None
        if 'listen_port' in value and (not integer(value['listen_port'], 65535) or value['listen_port'] == 0):
            return None
        if 'last_command_id' in value and not integer(value['last_command_id'], 2**31 - 1):
            return None
        for key in ('probe_tested', 'probe_total'):
            if key in value and not integer(value[key], 1000): return None
        if 'switch_threshold_ms' in value and not integer(value['switch_threshold_ms'], 60000):
            return None
        if value.get('selection_mode', 'auto') not in ('auto','prefer','fixed','fastest','profile','delegated'):
            return None
        if 'client_ips' in value:
            ips = value['client_ips']
            if not isinstance(ips, list) or len(ips) != value['connected_clients'] or len(set(ips)) != len(ips):
                return None
            for ip in ips:
                if not isinstance(ip, str) or str(ipaddress.IPv4Address(ip)) != ip:
                    return None
        nodes = value.get('nodes', [])
        if not isinstance(nodes, list) or len(nodes) > 1000:
            return None
        clean_nodes = []
        names = set()
        for node in nodes:
            if not isinstance(node, dict) or not string(node.get('name'), 256, False):
                return None
            if node['name'] in names: return None
            names.add(node['name'])
            if node.get('healthy') is not None and type(node['healthy']) is not bool:
                return None
            delay = node.get('delay_ms')
            if delay is not None and (type(delay) not in (int, float) or not math.isfinite(delay) or not 0 <= delay <= 86400000):
                return None
            clean_nodes.append({key: node[key] for key in ('name','healthy','delay_ms') if key in node})
        groups = value.get('groups', [])
        if not isinstance(groups, list) or len(groups) > 1000:
            return None
        clean_groups = []
        names = set()
        for group in groups:
            if not isinstance(group, dict) or not string(group.get('name'), 256, False) or not string(group.get('selected', ''), 256):
                return None
            if group['name'] in names: return None
            names.add(group['name'])
            item = {'name': group['name'], 'selected': group.get('selected', '')}
            if 'eligible_node_count' in group:
                if not integer(group['eligible_node_count'], 1000): return None
                item['eligible_node_count'] = group['eligible_node_count']
            if 'members' in group:
                if not isinstance(group['members'], list) or len(group['members']) > 1000 or not all(string(name, 256, False) for name in group['members']):
                    return None
                item['members'] = list(group['members'])
            clean_groups.append(item)
        allowed = {'event','state','core_state','running','engine','engine_version','listen_host','listen_port',
                   'address','connected_clients','active_connections','client_ips','selection_mode',
                   'switch_threshold_ms','selection_group','selected_node','error','node_management','preparing',
                   'busy','last_command_id','command_error','probe_complete','probe_tested','probe_total'}
        result = {key: item for key, item in value.items() if key in allowed}
        result.update(nodes=clean_nodes, groups=clean_groups)
        return result
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        return None


def send_command(process, command: str, **values) -> None:
    from .runtime import validate_command, MAX_COMMAND_BYTES
    value = validate_command(dict(values, command=command))
    line = json.dumps(value, ensure_ascii=True, separators=(',', ':')) + '\n'
    if len(line.encode('utf-8')) > MAX_COMMAND_BYTES:
        raise ValueError('Runtime command is too large')
    if process is None or process.stdin is None or process.poll() is not None:
        raise RuntimeError('Proxy is not running')
    try:
        process.stdin.write(line)
        process.stdin.flush()
    except (OSError, ValueError) as exc:
        raise RuntimeError('Proxy control channel is closed') from exc
