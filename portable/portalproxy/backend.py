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
    'max_connections', 'health_url', 'health_interval', 'health_timeout',
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
                    for line in sys.stdin:
                        if line.strip() == 'stop':
                            break
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
