"""Small local-only Tk desktop shell; the proxy stays in a child process.

Importing this module does not require a display or start network activity.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import atexit
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qsl, unquote, urlsplit

from . import config, backend as engine_backend, product_modes
from .runtime import MAX_STATUS_BYTES, MAX_EVENT, PREFIX

MAX_CONFIG_BYTES = 1024 * 1024
MAX_LOG_LINES = 500
FIELDS = (
    ('listen_host', 'LAN listener IPv4 (saved for Game / Mixed)'),
    ('listen_port', 'HTTP proxy port'),
    ('allowed_clients', 'Allowed device IPv4 addresses (comma-separated)'),
    ('engine_mode', 'Engine (embedded is experimental)'),
    ('core_path', 'Mihomo executable'),
    ('native_path', 'Embedded engine executable'),
    ('subscription_url', 'HTTPS subscription URL'),
    ('subscription_file', 'Local provider file (overrides URL)'),
    ('selection_mode', 'Node selection'),
    ('preferred_node', 'Preferred / fixed node name'),
    ('switch_threshold_ms', 'Fastest switch threshold (ms)'),
    ('idle_seconds', 'Idle timeout (seconds)'),
    ('backend_port', 'Local core port'),
    ('api_port', 'Local controller port'),
)
INTEGER_FIELDS = {'listen_port', 'backend_port', 'api_port', 'idle_seconds', 'switch_threshold_ms'}


def default_config_path() -> Path:
    """Use per-user storage rather than a potentially read-only app bundle."""
    if sys.platform == 'win32':
        root = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    elif sys.platform == 'darwin':
        root = Path.home() / 'Library' / 'Application Support'
    else:
        root = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    return root / 'PSPortalProxy' / 'config.json'


def read_config(path: Path) -> dict:
    with path.open('rb') as stream:
        raw = stream.read(MAX_CONFIG_BYTES + 1)
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError('Configuration is too large')
    result = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(result, dict):
        raise ValueError('Configuration must be a JSON object')
    return result


def _write_config(path: Path, values: dict, *, validate=False) -> None:
    """Atomically save a private draft, optionally validating a runnable config."""
    path = path.expanduser().absolute()
    if path.is_symlink():
        raise ValueError('Choose a regular configuration file, not a symbolic link')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.portal-config-', suffix='.json', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(values, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        if validate:
            config.load(temporary)  # Field validation only; no network or execution.
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_config(path: Path, values: dict) -> None:
    _write_config(path, values, validate=True)


def reusable_source(values: dict, source: str, url: str) -> bool:
    """A saved URL is editable configuration, never proof of an accepted import."""
    if not source:
        return False
    origin = values.get('source_provenance')
    if origin is None:
        # With no URL, a legacy local file is the sole explicit source.
        return not url
    if not isinstance(origin, dict) or origin.get('path') != source:
        return False
    return (origin.get('kind') == 'local'
            or origin.get('kind') == 'subscription' and origin.get('url') == url)


def secret_values(values: dict) -> tuple[str, ...]:
    secrets = set()
    sources = [values]
    previous = values.get('accelerator_previous_config')
    if isinstance(previous, dict):
        sources.extend(previous[key] for key in ('raw', 'values') if isinstance(previous.get(key), dict))
    for source in sources:
        for key in ('subscription_url', 'health_url'):
            value = source.get(key)
            if not isinstance(value, str) or not value:
                continue
            secrets.update((value, unquote(value)))
            try:
                secrets.update(v for _, v in parse_qsl(urlsplit(value).query) if v)
            except ValueError:
                pass
    return tuple(sorted(secrets, key=len, reverse=True))


def redact_log(message: str, secrets: tuple[str, ...] = ()) -> str:
    """Defense in depth: raw core output is suppressed by the backend too."""
    message = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', str(message))
    for secret in secrets:
        if secret:
            message = message.replace(secret, '[redacted]')
    message = re.sub(r'(?i)https?://[^\s<>\"\']+', '[URL redacted]', message)
    if re.search(r'(?i)\b(authorization|password|passwd|secret|token|api[-_ ]?key)\b\s*[:=]', message):
        return '[Sensitive diagnostic omitted]'
    message = ''.join(c for c in message if c in '\t' or ord(c) >= 32)
    return message[:1000]


def backend_command(path: Path) -> list[str]:
    return engine_backend.external_command(path)


class BackendProcess:
    """Single owned subprocess, bounded logs, and cooperative shutdown on all OSes."""

    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.events: queue.Queue[str] = queue.Queue(maxsize=500)
        self.updates = queue.Queue(maxsize=100)
        self._write_lock = threading.Lock()
        self.secrets: tuple[str, ...] = ()
        self.stopping_since: float | None = None
        self._signaled = False
        self.launch: engine_backend.Launch | None = None
        self.ready = False
        self.runtime = None
        self._state_lock = threading.Lock()
        atexit.register(self._at_exit)

    def log(self, text: str) -> None:
        try:
            self.events.put_nowait(redact_log(text, self.secrets))
        except queue.Full:
            pass

    def start(self, path: Path, values: dict) -> None:
        with self._state_lock:
            if self.process is not None and self.process.poll() is None:
                raise RuntimeError('The listener is already running')
            # Detach the exited owner before preparing/spawning a replacement.
            # Buffered output from its reader must not mark the new run ready.
            self.process = None
            self.ready = False
            self.runtime = None
        if self.launch is not None:
            self.launch.cleanup()
        self.secrets = secret_values(values)
        launch = (engine_backend.prepare_launch(path, values)
                  if values.get('engine_mode', 'external') != 'external'
                  else engine_backend.Launch(backend_command(path)))
        kwargs = dict(
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', bufsize=1,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        if sys.platform == 'win32':
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
            kwargs['startupinfo'] = startup
        else:
            kwargs['start_new_session'] = True
        try:
            process = engine_backend.spawn(launch, **kwargs)
        except BaseException:
            launch.cleanup()
            raise
        with self._state_lock:
            self.process = process
        self.launch = launch
        self.stopping_since = None
        while not self.updates.empty():
            try: self.updates.get_nowait()
            except queue.Empty: break
        self._signaled = False
        self.log(('Experimental embedded engine' if launch.embedded else 'External-Mihomo listener')
                 + ' process started. Waiting for listener readiness.')
        if launch.embedded:
            self.log('Embedded mode supports a restricted adapter subset and public node endpoints. Unsupported nodes are ignored; fixed mode never silently falls back.')
        threading.Thread(target=self._read_output, args=(self.process, launch, dict(values), self.secrets), daemon=True).start()

    def _read_output(self, process: subprocess.Popen, launch=None, values=None, secrets=None) -> None:
        assert process.stdout is not None
        def log(line):
            # Capture this child's secrets: a quick restart must not use the
            # replacement configuration's redaction set for old output.
            if values is not None and self.process is not process:
                return
            try:
                self.events.put_nowait(redact_log(line, self.secrets if secrets is None else secrets))
            except queue.Full:
                pass
        try:
            with process.stdout:
                while True:
                    line = process.stdout.readline(MAX_STATUS_BYTES + 1)
                    if not line:
                        break
                    if len(line) > MAX_STATUS_BYTES:
                        # Drop the entire oversized record, not split tokens.
                        while line and not line.endswith('\n'):
                            line = process.stdout.readline(MAX_STATUS_BYTES + 1)
                        log('[Oversized diagnostic omitted]')
                        continue
                    if line.startswith(PREFIX):
                        # Both protocols are emitted only by our owned child. A
                        # restart must never receive the previous child's data.
                        if len(line.encode('utf-8')) <= MAX_EVENT:
                            try:
                                event = json.loads(line[len(PREFIX):])
                                with self._state_lock:
                                    if (self.process is process and isinstance(event, dict)
                                            and event.get('kind') in ('statistics', 'nodes', 'control_error')):
                                        self.updates.put_nowait(event)
                            except (ValueError, queue.Full):
                                pass
                        continue
                    if values is not None:
                        status = engine_backend.parse_status(line.rstrip())
                        if status is not None:
                            # State and device counts must belong to this exact
                            # child/listener, never buffered output from a restart.
                            if (status.get('listen_host') == values.get('listen_host')
                                    and status.get('listen_port') == values.get('listen_port', 10081)):
                                with self._state_lock:
                                    if self.process is process:
                                        self.runtime = status
                            continue
                    if len(line) > 4096:
                        log('[Oversized diagnostic omitted]')
                        continue
                    if values is not None and engine_backend.is_ready(line.rstrip(), values):
                        with self._state_lock:
                            if self.process is process:
                                self.ready = True
                    log(line.rstrip())
        finally:
            if launch is not None:
                process.wait()
                if process.stdin is not None:
                    try:
                        process.stdin.close()
                    except (OSError, ValueError):
                        pass
                launch.cleanup()

    def snapshot(self):
        with self._state_lock:
            return self.runtime

    def command(self, command, action=None, **values):
        with self._state_lock:
            process = self.process
            if (process is None or process.poll() is not None
                    or self.stopping_since is not None):
                raise RuntimeError('The listener is not available')
            with self._write_lock:
                if action is None:
                    engine_backend.send_command(process, command, **values)
                else:
                    line = json.dumps(dict(id=command, action=action, **values), ensure_ascii=False) + '\n'
                    if len(line.encode('utf-8')) > 8192:
                        raise ValueError('Node command is too large')
                    if process.stdin is None:
                        raise RuntimeError('The listener control channel is closed')
                    process.stdin.write(line)
                    process.stdin.flush()

    def stop(self) -> None:
        process = self.process
        if process is None or process.poll() is not None or self.stopping_since is not None:
            return
        self.stopping_since = time.monotonic()
        self.log('Stopping listener and its core…')
        try:
            if process.stdin is not None:
                # EOF is also the parent-crash safety mechanism on Windows.
                process.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass

    def poll(self) -> int | None:
        process = self.process
        if process is None:
            return None
        result = process.poll()
        if result is not None:
            with self._state_lock:
                if self.process is process:
                    self.process = None
                    self.ready = False
                    self.runtime = None
                    # Records queued before EOF belong to the exited owner.
                    # Its reader cannot enqueue again after this locked detach.
                    while True:
                        try:
                            self.updates.get_nowait()
                        except queue.Empty:
                            break
            if self.launch is not None:
                self.launch.cleanup()
            return result
        if self.stopping_since is not None and not self._signaled and time.monotonic() - self.stopping_since > 10:
            self._signaled = True
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == 'win32' else signal.SIGTERM)
                self.log('Still stopping; requested graceful shutdown again.')
            except (OSError, ValueError):
                self.log('Shutdown is taking longer than expected. Keep this window open.')
        return None

    def _at_exit(self):
        self.stop()
        if self.process is not None:
            try:
                self.process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                return
        if self.launch is not None:
            self.launch.cleanup()


class DesktopApp:
    def __init__(self, root, path: Path):
        self.root, self.path = root, path.expanduser().absolute()
        self.backend = BackendProcess()
        self.raw: dict = {}
        self.vars = {}
        self.dirty = False
        self.loading = False
        self.closing = False
        self.importing = False
        self.quick_start_pending = False
        self.subscription_message = ''
        self.core_message = ''
        self.setting_up = False
        self.xianniu_checking = False
        self.xianniu_message = ''
        self.xianniu_events = queue.Queue()
        self._xianniu_generation = 0
        self.setup_events = queue.Queue()
        self.discovery_events = queue.Queue()
        self._discovery_pending = False
        self._next_discovery = 0
        self.import_events = queue.Queue()
        self.command_id = 0
        self.pending_command = None
        self.statistics = None
        self.node_state = None
        self._import_generation = 0
        self._import_lock = threading.Lock()
        self._active_import = None
        self._node_request = 0
        self._pending_node_request = None
        self._reported_command = None
        self._quick_rollback = None
        self.inputs = []
        self.engine_inputs = {}
        self.profile_selection_inputs = []
        self.games_hub = None
        self.workspace_hub = None
        self._workspace_network = None
        self._workspace_target = None
        self._workspace_network_allow_subnet = False
        from .subscription_monitor import AccountingMonitor
        self.subscription_monitor = AccountingMonitor()
        self.clash_subscription = None
        self._usage_source_path = None
        self._usage_cached = None
        self._shared_local_port = None
        from .existing_proxy import detect_system_proxy, read_clash_accounting
        self.existing_proxy = detect_system_proxy()
        self.clash_info = read_clash_accounting() if self.existing_proxy else None
        from .desktop_view import DesktopView
        self.view = DesktopView(self)
        self.load()
        root.after(150, self.poll)

    def show_app_updates(self):
        from .update_dialog import show
        show(self)

    def _changed(self, *_):
        if not self.loading:
            if _ and 'subscription_url' in self.vars and str(self.vars['subscription_url']) == _[0]:
                if self.subscription_ready():
                    self.subscription_message = 'Subscription imported. Start sharing when ready.'
                    self._read_source_accounting()
                else:
                    self.view.subscription_info = None
                    self.subscription_message = 'Link changed. Press Enter or paste to import before starting.'
            if _ and any(key in self.vars and str(self.vars[key]) == _[0]
                         for key in ('listen_host', 'allowed_clients')):
                self._lan_automatic = False
            self.dirty = True
            self.engine_controls()
            self.view.refresh()

    def _t(self, key, **values):
        return self.view.tr(key, **values)

    def _set_status(self, status):
        self.view.status = status
        if status in ('Stopped', 'Stopped with error'):
            self.view.core_state = 'stopped' if status == 'Stopped' else 'Not reported'
        self.view.refresh()

    def node_command(self, command):
        """One control surface for current and compatibility child protocols."""
        protocol = getattr(self, '_node_protocol', None)
        legacy = command in ('nodes', 'latency') or (command in ('select', 'test') and (
            protocol == 'legacy' or protocol is None and getattr(self, 'node_state', None) is not None))
        if legacy:
            return self._legacy_node_command(command)
        return self.send_runtime_command(command)

    def send_runtime_command(self, command):
        """Only explicit actions can wake/test/switch a managed subscription."""
        from tkinter import messagebox
        snapshot = self.backend.snapshot()
        if (self.closing or self.importing or self._pending_node_request is not None
                or not snapshot or not snapshot.get('node_management')
                or self.raw.get('existing_proxy_port') or not self.view._direct_subscription()
                or snapshot.get('busy') or self.backend.stopping_since is not None):
            return
        values = {}
        if self.vars.get('profile_file') and self.vars['profile_file'].get():
            group = self.view.selection_group_var.get()
            if group:
                values['selection_group'] = group
            elif command != 'prepare':
                return
        if command == 'select':
            selected = self.view.node_table.selection()
            if not selected:
                return
            values.update(selection_mode='fixed',
                          preferred_node=self.view.node_table.item(selected[0], 'values')[0])
        elif command == 'fastest':
            try:
                threshold = int(self.view.switch_threshold_var.get())
                if not 0 <= threshold <= 60000:
                    raise ValueError()
            except ValueError:
                messagebox.showerror(self._t('Check configuration'),
                    self._t('Enter a switch threshold from 0 to 60000 ms.'), parent=self.root)
                return
            command = 'select'
            values.update(selection_mode='fastest', preferred_node='', switch_threshold_ms=threshold)
        elif command not in ('prepare', 'test'):
            raise ValueError('unsupported node command')
        self._node_request = max(self._node_request, getattr(self, 'command_id', 0)) + 1
        self.command_id = request_id = self._node_request
        try:
            self.backend.command(command, request_id=request_id, **values)
        except (OSError, RuntimeError, ValueError):
            self.backend.log(self._t('The node command could not be sent. Check the listener status.'))
            return
        self._pending_node_request = (self.backend.process, request_id)
        self._node_protocol = 'runtime'
        self.view.node_message = ''
        self.pending_command = request_id
        self.view.refresh()

    def _save_node_policies(self, policies):
        if not isinstance(policies, dict) or not hasattr(self, 'path'):
            return
        from .nodes import validate_policies
        try:
            policies = validate_policies(policies)
            self.raw['node_policies'] = policies
            save_config(self.path, self.raw)
        except (OSError, ValueError):
            self.view.node_message = 'Selection applied; preference could not be saved.'

    def _poll_runtime(self):
        snapshot = self.backend.snapshot()
        pending = self._pending_node_request
        completed = bool(pending and snapshot and self.backend.process is pending[0]
                         and snapshot.get('last_command_id') == pending[1]
                         and not snapshot.get('busy'))
        if pending and (self.backend.process is not pending[0] or completed):
            self._pending_node_request = None
            self.pending_command = None
            if completed and not snapshot.get('command_error'):
                self._save_node_policies(snapshot.get('node_policies'))
        if snapshot:
            key = (self.backend.process, snapshot.get('last_command_id'))
            if snapshot.get('command_error') and key != self._reported_command:
                self._reported_command = key
                self.backend.log(redact_log(snapshot['command_error'], self.backend.secrets))
        self.view.runtime = snapshot
        if snapshot and snapshot.get('core_state') in ('starting', 'running', 'stopped', 'failed'):
            self.view.core_state = snapshot['core_state']

    def set_language(self, language):
        from .i18n import save_language
        self.view.set_language(language)
        self.engine_controls()
        try:
            save_language(self.path, language)
        except (OSError, ValueError):
            self.backend.log(self._t('Preferences could not be saved. Language changed for this session.'))

    def set_theme(self, theme, color=None):
        from .i18n import save_theme
        self.view.set_theme(theme, color)
        try:
            save_theme(self.path, theme, color)
        except (OSError, ValueError):
            self.backend.log('Appearance preference could not be saved.')

    def open_game_accelerator(self):
        if self.product_mode()!='accelerator':self.set_product_mode('accelerator')
        if self.product_mode()=='accelerator':self.view.show('Games')

    def open_workspace(self,key):
        hub=self.games_hub
        if self.backend.process is not None or (hub and hub.running):
            if self.workspace_hub:self.workspace_hub.state.set('请先停止当前通道，再切换用途。')
            return
        self.view.show('Workspaces')
        self.workspace_hub.select(key)

    def show_connection_result(self):
        self.view.show('Workspaces' if getattr(self,'workspace_hub',None) and getattr(self.view,'page',None)=='Workspaces' else 'Overview' if self.product_mode()=='clash' else 'LAN sharing')

    def set_product_mode(self, mode):
        previous = getattr(self, '_selected_product_mode', self.raw.get('product_mode', 'game'))
        hub=getattr(self,'games_hub',None)
        if mode!=previous and hub and hub.running:
            self.vars['product_mode'].set(previous)
            self.view.subtitle.set('请先停止鲜牛加速，再切换模式')
            return
        if (mode not in product_modes.MODES or self.closing or self.importing
                or getattr(self, 'setting_up', False) or getattr(self, 'xianniu_checking', False)
                or self.backend.process is not None):
            self.vars['product_mode'].set(previous)
            self.view.refresh()
            return
        if mode == 'accelerator' and previous != 'accelerator':
            if sys.platform != 'win32':
                self.vars['product_mode'].set(previous)
                return
            self._enter_accelerator(previous)
        elif previous == 'accelerator' and mode != 'accelerator':
            self._leave_accelerator()
        if mode != 'accelerator' and self.raw.get('existing_proxy_port') and mode not in ('game','mixed'):
            mode = 'game'
        self.vars['product_mode'].set(mode)
        self._selected_product_mode = mode
        self.dirty = True
        self.engine_controls()
        if mode!='accelerator' and getattr(self.view,'page',None)=='Games':
            self.view.show('Overview')
        self.view.refresh()

    def _accelerator_preferences(self):
        keys = ('listen_host', 'allowed_clients', 'listen_port', 'backend_port', 'api_port', 'idle_seconds')
        result = dict(values={key: self.vars[key].get() for key in keys if key in self.vars},
                      automatic=getattr(self, '_lan_automatic', False))
        if hasattr(self.view, 'accelerator_source_var'):
            result.update(transport=self.view.accelerator_source_var.get(), port=self.view.accelerator_port_var.get())
        return result

    def _enter_accelerator(self, previous):
        """Keep the complete normal configuration in the same private file."""
        old = copy.deepcopy(self.raw)
        old.pop('accelerator_previous_config', None)
        fields = {key: variable.get() for key, variable in self.vars.items()}
        fields['product_mode'] = previous
        saved = dict(raw=old, values=fields, automatic=getattr(self, '_lan_automatic', False))
        preferences = self.raw.get('accelerator_preferences')
        self.raw['accelerator_previous_config'] = saved
        for key in ('existing_proxy_port', 'existing_proxy_provider', 'source_provenance',
                    'node_policies', 'host_profile_overlay', 'linked_previous_source', 'accelerator_proxy'):
            self.raw.pop(key, None)
        self.raw.update(host_relay='steam', live_node_controls=False)
        self.loading = True
        try:
            if hasattr(self.view, 'load_accelerator_source'):
                self.view.load_accelerator_source({'accelerator_preferences': preferences})
            for key, value in (('engine_mode', 'external'), ('profile_file', ''),
                               ('subscription_file', ''), ('subscription_url', ''),
                               ('selection_mode', 'auto'), ('preferred_node', '')):
                if key in self.vars:
                    self.vars[key].set(value)
            if isinstance(preferences, dict) and isinstance(preferences.get('values'), dict):
                for key, value in preferences['values'].items():
                    if key in self._accelerator_preferences()['values'] and isinstance(value, str):
                        self.vars[key].set(value)
                self._lan_automatic = preferences.get('automatic') is True
        finally:
            self.loading = False
        self.view.preview = None
        self.view.subscription_info = None

    def _leave_accelerator(self):
        preferences = self._accelerator_preferences()
        saved = self.raw.pop('accelerator_previous_config', None)
        if isinstance(saved, dict) and isinstance(saved.get('raw'), dict) and isinstance(saved.get('values'), dict):
            self.raw = copy.deepcopy(saved['raw'])
            self.loading = True
            try:
                for key, value in saved['values'].items():
                    if key in self.vars and isinstance(value, str):
                        self.vars[key].set(value)
            finally:
                self.loading = False
            self._lan_automatic = saved.get('automatic') is True
        else:
            # Migrate the earlier preview's shared game/accelerator source.
            self.raw.pop('host_relay', None)
            self.raw.pop('accelerator_proxy', None)
            self.raw.pop('existing_proxy_port', None)
            self.raw.pop('existing_proxy_provider', None)
            previous = self.raw.pop('linked_previous_source', {})
            if isinstance(previous, dict):
                for key, value in previous.items():
                    if key in self.vars and isinstance(value, str):
                        self.vars[key].set(value)
                    elif key in ('source_provenance', 'node_policies', 'host_profile_overlay'):
                        self.raw[key] = copy.deepcopy(value)
        self.raw['accelerator_preferences'] = preferences
        self.view.preview = None
        self.view.subscription_info = None
        if self.subscription_ready():
            self._read_source_accounting()

    def unlink_proxy(self):
        if self.closing or self.importing or self.setting_up or self.backend.process is not None:
            return
        if self.product_mode() == 'accelerator':
            saved = self.raw.get('accelerator_previous_config', {})
            previous = saved.get('values', {}).get('product_mode', 'game') if isinstance(saved, dict) else 'game'
            self.set_product_mode(previous if previous in ('game', 'mixed', 'clash') else 'game')
            return
        self.raw.pop('existing_proxy_port', None)
        self.raw.pop('existing_proxy_provider', None)
        self.raw.pop('host_relay', None)
        self.raw.pop('accelerator_proxy', None)
        self.raw.pop('source_provenance', None)
        previous = self.raw.pop('linked_previous_source', None)
        if isinstance(previous, dict):
            for key in ('profile_file', 'subscription_file', 'subscription_url', 'engine_mode', 'product_mode'):
                value = previous.get(key)
                if not isinstance(value, str) or key not in self.vars:
                    continue
                if key == 'engine_mode' and value not in ('external', 'embedded'):
                    continue
                if key == 'product_mode' and value not in product_modes.MODES:
                    continue
                self.vars[key].set(value)
            for key in ('source_provenance', 'node_policies', 'host_profile_overlay', 'workspace_target', 'shared_core', 'local_proxy_port'):
                if key in previous:
                    self.raw[key] = copy.deepcopy(previous[key])
            self.raw['product_mode'] = self.product_mode()
            self.raw['engine_mode'] = self.vars['engine_mode'].get()
        self.view.subscription_info = None
        self.subscription_message = ('Subscription imported. Start sharing when ready.' if self.subscription_ready() else
            'Independent core selected. Paste a subscription or choose a local configuration.')
        if self.subscription_ready():
            self._read_source_accounting()
        try:
            self._persist_import()
        except (OSError, ValueError):
            self.subscription_message = 'Client unlinked for this session. Could not save; check file permissions.'
        self.engine_controls()
        self.view.refresh()

    def product_mode(self):
        variable = getattr(self, 'vars', {}).get('product_mode')
        return variable.get() if variable else product_modes.infer_mode(getattr(self, 'raw', {}))

    def engine_controls(self):
        running = ((self.backend.process is not None and self.backend.process.poll() is None)
                   or self.importing or getattr(self, 'setting_up', False))
        mode = self.vars['engine_mode'].get() if 'engine_mode' in self.vars else 'external'
        for key, widgets in self.engine_inputs.items():
            active = mode == ('embedded' if key == 'native_path' else 'external') and self.product_mode() != 'accelerator'
            for widget in widgets:
                widget.configure(state='normal' if active and not running else 'disabled')
        full_profile = bool(self.vars.get('profile_file') and self.vars['profile_file'].get().strip())
        for widget, normal in self.profile_selection_inputs:
            widget.configure(state='disabled' if running or full_profile else normal)
        if hasattr(self, 'mode_note_var'):
            self.mode_note_var.set(self._t(
                'Experimental embedded mode: restricted adapter subset, public-only node endpoints. Some subscriptions are unsupported; fixed mode never silently falls back. See desktop.md.'
                if mode == 'embedded' else
                'External mode: separate trusted Mihomo executable. This remains the default fallback.'))

    def load(self):
        from tkinter import messagebox
        self.view.preview = None
        self.view.subscription_info = None
        try:
            self.raw = read_config(self.path) if self.path.exists() else {}
            product_modes.infer_mode(self.raw)
        except (OSError, UnicodeError, ValueError):
            messagebox.showerror(self._t('Cannot open configuration'), self._t('The file could not be read as a JSON configuration. Choose a different file.'), parent=self.root)
            self.raw = {}
        defaults = dict(config.DEFAULTS, listen_host='', allowed_clients=[], core_path='', subscription_url='',
                        native_path=str(config.bundled_native_path() or ''))
        defaults.update(self.raw)
        # An empty saved field means bundled discovery, just as it does in
        # config.validate. Keep the visible field/readiness check consistent;
        # never replace a nonempty explicit path, even when it needs repair.
        if not defaults.get('native_path'):
            defaults['native_path'] = str(config.bundled_native_path() or '')
        defaults.update(product_modes.editable_config(defaults))
        if self.raw.get('host_relay') == 'steam' or self.raw.get('existing_proxy_provider') == 'xianniu':
            defaults['product_mode'] = 'accelerator'
        elif self.raw.get('existing_proxy_port'):
            defaults['product_mode'] = 'game'
        from .core_setup import discover_core
        discovered = discover_core(self.path, defaults.get('core_path', ''))
        if discovered:
            defaults['core_path'] = discovered
        self._auto_core_path = discovered if not self.raw.get('core_path') else None
        self.core_message = ''
        self.subscription_message = ''
        self._lan_automatic = product_modes.infer_automatic(self.raw)
        source = self.raw.get('profile_file') or self.raw.get('subscription_file')
        # Recognize source snapshots accepted by the earlier Windows PR only
        # when its saved URL fingerprint still matches; edited URLs must import.
        url = self.raw.get('subscription_url', '')
        if (source and not self.raw.get('source_provenance') and isinstance(url, str)
                and self.raw.get('desktop_import_url_sha256') == hashlib.sha256(url.encode('utf-8')).hexdigest()):
            self.raw['source_provenance'] = dict(kind='subscription', path=source, url=url)
        if source:
            try:
                metadata = Path(source).with_suffix(Path(source).suffix + '.info.json')
                if metadata.is_file() and metadata.stat().st_size <= 8192:
                    self.view.subscription_info = read_config(metadata)
            except (ValueError, OSError):
                pass
        elif self.raw.get('existing_proxy_port') and self.raw.get('existing_proxy_provider') != 'xianniu':
            self.view.subscription_info = self.clash_info
        self.loading = True
        self.view.load_accelerator_source(self.raw)
        for key, variable in self.vars.items():
            value = defaults.get(key, '')
            if key == 'allowed_clients':
                value = ', '.join(str(item) for item in value) if isinstance(value, list) else ''
            variable.set(str(value))
        self.loading = False
        self._selected_product_mode = defaults.get('product_mode', 'game')
        self.dirty = False
        if source and not self.subscription_ready():
            self.view.subscription_info = None
        self.view.switch_threshold_var.set(str(defaults.get('switch_threshold_ms', 50)))
        self.view.selection_group_var.set('')
        self.path_var.set(str(self.path))
        from .i18n import load_language
        self.view.set_language(load_language(self.path))
        from .i18n import load_theme, load_theme_color
        self.view.theme_color=load_theme_color(self.path)
        self.view.set_theme(load_theme(self.path))
        self.engine_controls()
        self.view.refresh()

    def subscription_ready(self):
        source = next((self.vars[key].get().strip() for key in ('profile_file', 'subscription_file')
                       if self.vars.get(key) and self.vars[key].get().strip()), '')
        url = self.vars['subscription_url'].get().strip() if 'subscription_url' in self.vars else ''
        return bool(source and Path(source).is_file() and reusable_source(self.raw, source, url))

    def _read_source_accounting(self):
        source = self.vars['profile_file'].get() or self.vars['subscription_file'].get()
        try:
            path = Path(source).with_suffix(Path(source).suffix + '.info.json')
            self.view.subscription_info = read_config(path) if path.is_file() and path.stat().st_size <= 8192 else None
        except (OSError, ValueError):
            self.view.subscription_info = None

    def paste_subscription(self, event=None):
        if self.product_mode() == 'accelerator':
            return 'break'
        if self.closing or self.importing or self.setting_up or self.backend.process is not None:
            return 'break'
        try:
            value = self.root.clipboard_get().strip()
        except Exception:
            self.subscription_message = 'The clipboard has no text. Paste an HTTPS subscription link.'
            self.view.refresh()
            return 'break'
        if self.vars['subscription_url'].get().strip() != value:
            self.vars['subscription_url'].set(value)
        self.import_subscription()
        return 'break'

    def _persist_import(self):
        """Save only accepted source fields; keep unrelated form edits unsaved."""
        values = dict(self.raw)
        for key in ('profile_file', 'subscription_file', 'subscription_url'):
            values[key] = self.vars[key].get().strip()
        if getattr(self, '_auto_core_path', None) and self.vars['core_path'].get() == self._auto_core_path:
            values['core_path'] = self._auto_core_path
        _write_config(self.path, values)
        self.raw = values
        defaults = dict(config.DEFAULTS, listen_host='', allowed_clients=[], core_path='',
                        native_path=str(config.bundled_native_path() or ''), subscription_url='')
        defaults.update(values)
        defaults.update(product_modes.editable_config(defaults))
        self.dirty = False
        for key, variable in self.vars.items():
            expected = defaults.get(key, '')
            if key == 'allowed_clients':
                expected = ', '.join(str(item) for item in expected) if isinstance(expected, list) else ''
            if variable.get().strip() != str(expected):
                self.dirty = True
                break
        from .i18n import save_language, save_theme
        try:
            save_language(self.path, self.view.language)
            save_theme(self.path, self.view.theme)
        except (OSError, ValueError):
            self.backend.log('Preferences could not be saved.')

    def setup_core(self, start_after=False):
        """Reuse one stable core, or explicitly download a verified Windows core."""
        if self.closing or self.importing or self.setting_up or self.backend.process is not None:
            return
        self._start_after_setup = start_after
        from .core_setup import discover_core, can_install, install_core, RELEASES
        found = discover_core(self.path)
        if found:
            self.vars['core_path'].set(found)
            self.core_message = 'Core selected automatically. Start sharing when ready.'
            self.view.refresh()
            self._resume_after_core_setup()
            return
        if not can_install():
            self._start_after_setup = False
            self.core_message = 'The default core is unavailable. Use the build for this system or check Advanced settings.'
            self.view.refresh()
            return
        self.setting_up = True
        self.core_message = 'Downloading and verifying Mihomo…'
        self.running_controls(True)
        self.stop_button.configure(state='disabled')
        path = self.path
        def worker():
            try:
                result = install_core(path)
            except Exception:
                self.setup_events.put((path, None))
            else:
                self.setup_events.put((path, result))
        threading.Thread(target=worker, daemon=True).start()

    def _resume_after_core_setup(self):
        action = getattr(self, '_start_after_setup', False)
        self._start_after_setup = False
        if action and not self.closing:
            if action=='workspace':
                if self.view.page=='Workspaces' and self.workspace_hub:self.workspace_hub.toggle()
            else:self.start() if action == 'manual' else self.quick_start()


    def open_clash(self):
        from .core_setup import discover_clash
        executable = discover_clash()
        if executable:
            try:
                subprocess.Popen([str(executable)], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except OSError:
                self.core_message = 'Could not open Clash. Open it manually and enable its system proxy.'
                self.view.refresh()
        else:
            import webbrowser
            webbrowser.open('https://github.com/clash-verge-rev/clash-verge-rev/releases')


    def _poll_setup(self):
        try:
            path, result = self.setup_events.get_nowait()
        except queue.Empty:
            return
        self.setting_up = False
        if path == self.path:
            if result:
                self.vars['core_path'].set(result)
                self.core_message = 'Core selected automatically. Start sharing when ready.'
            else:
                self._start_after_setup = False
                self.core_message = 'Default core preparation failed. Check the network and click Start sharing to retry.'
        self.running_controls(False)
        if result and path == self.path:
            self._resume_after_core_setup()


    def _poll_discovery(self):
        """Refresh cached Clash accounting off the Tk thread; never call its controller."""
        try:
            record = self.discovery_events.get_nowait()
            proxy, info = record[:2]
            if len(record)>2:self.clash_subscription=record[2]
        except queue.Empty:
            pass
        else:
            self._discovery_pending = False
            self.existing_proxy, self.clash_info = proxy, info
            if self.raw.get('existing_proxy_port') and self.raw.get('existing_proxy_provider') != 'xianniu':
                self.view.subscription_info = info
            self.view.refresh()
        if not self.closing and not self._discovery_pending and time.monotonic() >= self._next_discovery:
            self._discovery_pending = True
            self._next_discovery = time.monotonic() + 10
            def worker():
                from .existing_proxy import detect_system_proxy, read_clash_accounting, clash_subscription_source
                try:
                    proxy = detect_system_proxy()
                    info = read_clash_accounting() if proxy else None
                except Exception:
                    proxy, info = None, None
                source = clash_subscription_source() if proxy else None
                self.discovery_events.put((proxy, info, source))
            threading.Thread(target=worker, daemon=True).start()

    def refresh_subscription_usage(self):
        self._poll_subscription_usage(force=True)

    def _poll_subscription_usage(self, force=False):
        from .subscription_monitor import descriptor
        monitor=getattr(self,'subscription_monitor',None)
        if monitor is None:return
        home=getattr(self,'workspace_hub',None)
        chosen_link=home and self.view.page=='Workspaces' and (home.selected=='clash' or home.selected=='game' and home.game_source.get()=='跟随 Clash')
        linked=chosen_link or self.raw.get('existing_proxy_port') and self.raw.get('existing_proxy_provider')!='xianniu'
        if linked:
            source=self.clash_subscription or descriptor(cached=self.clash_info,identity='clash-unavailable',linked=True)
        else:
            path=next((self.vars[k].get().strip() for k in ('profile_file','subscription_file') if self.vars.get(k) and self.vars[k].get().strip()),'')
            ready=self.subscription_ready()
            if path!=self._usage_source_path:
                self._usage_source_path=path;self._usage_cached=None
                try:
                    sidecar=Path(path).with_suffix(Path(path).suffix+'.info.json')
                    if path and sidecar.is_file() and sidecar.stat().st_size<=8192:self._usage_cached=read_config(sidecar)
                except (OSError,ValueError):pass
            origin=self.raw.get('source_provenance',{})
            url=origin.get('url','') if ready and isinstance(origin,dict) and origin.get('kind')=='subscription' else ''
            source=descriptor(url,self._usage_cached if ready else None,identity=str(self.path)+':'+path)
        visible=self.view.page!='Games' and self.product_mode()!='accelerator'
        monitor.tick(source,visible=visible,force=force)
        if visible:self.view.subscription_info=monitor.info


    def choose_config(self):
        from tkinter import filedialog, messagebox
        if self.dirty and not messagebox.askyesno(self._t('Discard unsaved edits?'), self._t('Open another configuration and discard these unsaved edits?'), parent=self.root):
            return
        name = filedialog.askopenfilename(title=self._t('Open configuration'), initialdir=self.path.parent, filetypes=[('JSON configuration', '*.json'), ('All files', '*')], parent=self.root)
        if name:
            self.path = Path(name).absolute()
            self.load()

    def choose_core(self):
        from tkinter import filedialog
        name = filedialog.askopenfilename(title=self._t('Choose your verified Mihomo executable'), parent=self.root)
        if name:
            self.core_message = ''
            self.vars['core_path'].set(name)

    def choose_provider(self):
        if self.product_mode() == 'accelerator':
            return
        from tkinter import filedialog
        name = filedialog.askopenfilename(title=self._t('Choose local Clash/Mihomo provider YAML'), filetypes=[('YAML provider', '*.yaml *.yml'), ('All files', '*')], parent=self.root)
        if name:
            self._use_imported_file(Path(name))

    def choose_profile(self):
        if self.product_mode() == 'accelerator':
            return
        from tkinter import filedialog
        name = filedialog.askopenfilename(title=self._t('Complete Clash/Mihomo profile'),
            filetypes=[('YAML', '*.yaml *.yml *.json'), ('All files', '*')], parent=self.root)
        if name:
            self._use_imported_file(Path(name), full=True)

    def _use_imported_file(self, path, full=False, *, origin_url=None):
        if self.product_mode() == 'accelerator':
            return False
        from tkinter import messagebox
        from .profiles import inspect_profile, read_profile, validate_host_profile, host_overlay
        try:
            info = inspect_profile(path)
            full = full or info['kind'] == 'profile'
            if full:
                if self.vars['engine_mode'].get() == 'embedded':
                    raise ValueError('Complete profiles require the external Mihomo engine')
                validate_host_profile(host_overlay(read_profile(path)))
                self.raw['host_profile_overlay'] = True
                self.vars['profile_file'].set(str(path.absolute()))
                self.vars['subscription_file'].set('')
            else:
                self.vars['profile_file'].set('')
                self.vars['subscription_file'].set(str(path.absolute()))
            self.view.preview = info
            self.raw['shared_core'] = True
            if str(path.absolute()) != (self.raw.get('profile_file') or self.raw.get('subscription_file')):
                self.raw.pop('node_policies', None)
            self.raw.pop('existing_proxy_port', None)
            self.raw.pop('existing_proxy_provider', None)
            self.raw.pop('host_relay', None)
            self.raw['source_provenance'] = dict(kind='local', path=str(path.absolute()))
            if origin_url is not None:
                self.raw['source_provenance'].update(kind='subscription', url=origin_url)
            else:
                self.vars['subscription_url'].set('')
            try:
                metadata = path.with_suffix(path.suffix + '.info.json')
                self.view.subscription_info = read_config(metadata) if metadata.is_file() and metadata.stat().st_size <= 8192 else None
            except (OSError, ValueError):
                self.view.subscription_info = None
            self.view.refresh()
            return True
        except (ValueError, OSError) as error:
            messagebox.showerror(self._t('Cannot inspect provider'), self._t(str(error)), parent=self.root)
            return False

    def check_preparation(self):
        """Explain prerequisites without downloads, network changes or a launch."""
        from tkinter import messagebox
        from .onboarding import preparation_notes
        values = {key: variable.get().strip() for key, variable in self.vars.items()}
        values['existing_proxy_port'] = self.raw.get('existing_proxy_port')
        values['host_relay'] = self.raw.get('host_relay')
        messagebox.showinfo(self._t('Before you start'),
            '\n\n'.join(self._t(note) for note in preparation_notes(values)), parent=self.root)

    def quick_start(self):
        if self.importing or getattr(self, 'setting_up', False) or self.backend.process is not None:
            return
        if getattr(self, 'xianniu_checking', False): return
        if self.product_mode() == 'accelerator':
            self.start_accelerator()
            return
        if self.raw.get('host_relay') == 'steam' and not self.vars['subscription_url'].get().strip():
            self.use_steam_host()
            return
        if self.raw.get('existing_proxy_provider') == 'xianniu':
            self.use_xianniu_proxy()
            return
        current_url = self.vars['subscription_url'].get().strip()
        if self.raw.get('existing_proxy_port') and not current_url:
            self.use_existing_proxy()
            return
        if not self.subscription_ready():
            source = any(self.vars.get(key) and self.vars[key].get().strip()
                         for key in ('profile_file', 'subscription_file'))
            if not current_url and not source and getattr(self, 'existing_proxy', None):
                self.use_existing_proxy()
                return
            self.subscription_message = 'Paste a subscription first. Importing never starts sharing.'
            self.view.refresh()
            return
        if self.vars['engine_mode'].get() == 'external' and not Path(self.vars['core_path'].get()).is_file():
            self.setup_core(start_after='workspace' if getattr(self,'_workspace_target',None) else 'quick')
            return
        plan = self._configure_lan(commit=False)
        if not plan:
            return
        source = next((self.vars[key].get().strip() for key in ('profile_file', 'subscription_file')
                       if self.vars.get(key) and self.vars[key].get().strip()), '')
        current_url = self.vars['subscription_url'].get().strip()
        if reusable_source(self.raw, source, current_url) and 'product_mode' in self.vars:
            # Switching use cases reuses the accepted source and node choices.
            # Explicit import remains available for a subscription refresh.
            from .profiles import inspect_profile
            try:
                info = inspect_profile(Path(source))
                if not self.vars['profile_file'].get().strip() and info['kind'] != 'provider':
                    raise ValueError('The saved provider is now a full profile. Import it again before starting.')
            except (OSError, ValueError) as error:
                from tkinter import messagebox
                messagebox.showerror(self._t('Cannot inspect provider'), self._t(str(error)), parent=self.root)
                return
            try:
                self._quick_rollback = self._quick_snapshot(None)
            except (OSError, ValueError):
                from tkinter import messagebox
                messagebox.showerror(self._t('Cannot save configuration'),
                    self._t('The configuration could not be saved. Choose a writable location and check file permissions.'), parent=self.root)
                return
            self._apply_lan(plan)
            if self.start() is False:
                self._rollback_quick_start()
                return
            self.show_connection_result()
            return

    def _configure_lan(self, reserved=(), *, commit=True):
        from tkinter import messagebox
        from .setup import discover_lan, available_port
        try:
            mode = self.product_mode() if 'product_mode' in self.vars else None
            if mode == 'clash':
                network = dict(host='127.0.0.1', clients=['127.0.0.1'], subnet='')
            else:
                # Quick setup follows the currently active physical network.
                # Advanced Start still uses the manually configured bind host.
                network = getattr(self,'_workspace_network',None) or discover_lan()
                if mode:
                    clients = [part.strip() for part in self.vars['allowed_clients'].get().split(',') if part.strip()]
                    automatic = (not clients or getattr(self, '_lan_automatic', product_modes.infer_automatic(self.raw)))
                    if getattr(self,'_workspace_network',None) and getattr(self,'_workspace_network_allow_subnet',False):automatic=True
                    if clients and not automatic:
                        if getattr(self,'_workspace_network',None):
                            import ipaddress
                            if any(ipaddress.ip_address(c) not in ipaddress.ip_network(network['subnet']) for c in clients):
                                raise ValueError('原设备名单不属于这个网络；请更新设备名单，或明确勾选允许所选网络中的设备。')
                        network = dict(network, clients=clients)
            if mode:
                product_modes.listener_policy(mode, network['host'], network['clients'])
            chosen = set(reserved)
            values = {}
            for key, host, default in (('listen_port', network['host'], 10081),
                                       ('backend_port', '127.0.0.1', 10082),
                                       ('api_port', '127.0.0.1', 10090)):
                try:
                    preferred = int(self.vars[key].get())
                except ValueError:
                    preferred = default
                # Keep the standard listener away from compatibility ports.
                excluded = chosen | ({10082, 10090} if key == 'listen_port' else set())
                selected = available_port(host, preferred, excluded)
                chosen.add(selected)
                values[key] = str(selected)
            if self.raw.get('shared_core') and mode in ('game','mixed') and not self.raw.get('existing_proxy_port'):
                candidate=available_port('127.0.0.1',self.raw.get('local_proxy_port',10080),chosen)
                self._shared_local_port=(self.path,candidate)
            if mode != 'clash':
                values.update(listen_host=network['host'], allowed_clients=', '.join(network['clients']))
            plan = (values, network['subnet'])
            if mode and mode != 'clash':
                plan += (automatic,)
            if commit:
                self._apply_lan(plan)
                return True
            return plan
        except ValueError as error:
            messagebox.showerror(self._t('Check configuration'), self._t(str(error)), parent=self.root)
            return False

    def _apply_lan(self, plan):
        values, subnet = plan[:2]
        loading = self.loading if hasattr(self, 'loading') else False
        self.loading = True
        try:
            for key, value in values.items():
                self.vars[key].set(value)
        finally:
            self.loading = loading
        if len(plan) > 2:
            self._lan_automatic = plan[2]
        self.dirty = True
        self.view.setup_network = subnet
        self.view.refresh()

    def use_existing_proxy(self, mode=None):
        if self.importing or getattr(self, 'setting_up', False) or self.backend.process is not None: return
        if getattr(self, 'xianniu_checking', False): return
        from .existing_proxy import detect_system_proxy
        self.existing_proxy = detect_system_proxy()
        if not self.existing_proxy:
            from tkinter import messagebox
            messagebox.showinfo(self._t('Existing proxy'), self._t('No active loopback HTTP system proxy was detected.'), parent=self.root)
            return
        if mode is None:self._link_existing_proxy(self.existing_proxy)
        else:self._link_existing_proxy(self.existing_proxy,mode=mode)

    def use_steam_host(self):
        if hasattr(self.view, 'accelerator_source_var'):
            self.view.accelerator_source_var.set('host')
        return self.start_accelerator()

    def start_accelerator(self):
        """Share this Windows host's TCP network for Steam web destinations."""
        from tkinter import messagebox
        if (self.closing or self.importing or self.setting_up or self.backend.process is not None
                or getattr(self, 'xianniu_checking', False)):
            return
        if (self.raw.get('existing_proxy_provider') == 'xianniu'
                and hasattr(self.view, 'accelerator_source_var')
                and self.view.accelerator_source_var.get() == 'http'
                and self.view.accelerator_port_var.get().strip() == str(self.raw.get('existing_proxy_port'))):
            self.use_xianniu_proxy()
            return
        if sys.platform != 'win32':
            messagebox.showinfo(self._t('Steam mobile relay'),
                self._t('Steam mobile relay through the PC network requires Windows.'), parent=self.root)
            return
        try:
            snapshot = self._quick_snapshot(None)
        except (OSError, ValueError):
            messagebox.showerror(self._t('Cannot save configuration'),
                self._t('The configuration could not be saved. Choose a writable location and check file permissions.'), parent=self.root)
            return
        previous_mode = self.vars['product_mode'].get()
        self._quick_rollback = snapshot
        if previous_mode != 'accelerator':
            self.set_product_mode('accelerator')
        plan = self._configure_lan(commit=False)
        if not plan:
            self._rollback_quick_start()
            return
        self._apply_lan(plan)
        for key, value in (('engine_mode', 'external'), ('profile_file', ''),
                           ('subscription_file', ''), ('subscription_url', ''),
                           ('selection_mode', 'auto'), ('preferred_node', '')):
            self.vars[key].set(value)
        self.raw.pop('existing_proxy_port', None)
        self.raw.pop('existing_proxy_provider', None)
        self.raw.pop('accelerator_proxy', None)
        self.raw['host_relay'] = 'steam'
        self.raw['live_node_controls'] = False
        self.view.subscription_info = None
        self.view.preview = None
        self.xianniu_message = ''
        self.view.refresh()
        if self.start() is False:
            self._rollback_quick_start()
            return
        self.view.show('LAN sharing')

    def use_xianniu_proxy(self, action='link'):
        """Verify one identified client's proxy off the UI thread before sharing."""
        if (self.closing or self.importing or self.setting_up or self.backend.process is not None
                or getattr(self, 'xianniu_checking', False)):
            return
        self.xianniu_checking = True
        self._xianniu_generation = getattr(self, '_xianniu_generation', 0) + 1
        generation = self._xianniu_generation
        self.xianniu_message = 'Checking Xianniu proxy…'
        owner = self.path
        self.running_controls(True)
        def worker():
            from .windows_accelerator import detect_xianniu
            try:
                result = detect_xianniu(probe=True)
            except Exception:
                # Do not expose command output, application settings or credentials.
                result = {'reason': 'Xianniu inspection failed. Check the client and retry.'}
            self.xianniu_events.put((owner, generation, action, result))
        threading.Thread(target=worker, daemon=True).start()

    def _poll_xianniu(self):
        if not hasattr(self, 'xianniu_events'):
            return
        try:
            owner, generation, action, result = self.xianniu_events.get_nowait()
        except queue.Empty:
            return
        if generation != self._xianniu_generation:
            return
        self.xianniu_checking = False
        if self.closing:
            return
        self.running_controls(False)
        if owner != self.path or self.backend.process is not None:
            return
        endpoint = result.get('verified_endpoint')
        valid = (result.get('probe_passed') is True and isinstance(endpoint, dict)
                 and endpoint.get('host') == '127.0.0.1'
                 and type(endpoint.get('port')) is int and 1024 <= endpoint['port'] <= 65535)
        if not valid:
            from tkinter import messagebox
            self.xianniu_message = ('Start Xianniu and enable the intended game or console acceleration first.'
                if not result.get('running') else
                'No verified HTTP CONNECT proxy was found. Driver or SOCKS mode cannot be shared by this relay.')
            self.view.refresh()
            messagebox.showinfo(self._t('Xianniu LAN relay'), self._t(self.xianniu_message), parent=self.root)
            return
        self.xianniu_message = 'Proxy tunnel verified. TCP only; game acceleration and UDP are not verified.'
        self._xianniu_starting = True
        try:
            if action == 'manual':
                # Advanced Start preserves the selected LAN adapter and allowlist.
                from tkinter import messagebox
                try:
                    self._quick_rollback = self._quick_snapshot(None)
                except (OSError, ValueError):
                    messagebox.showerror(self._t('Cannot save configuration'),
                        self._t('The configuration could not be saved. Choose a writable location and check file permissions.'), parent=self.root)
                    return
                self.raw['existing_proxy_port'] = endpoint['port']
                if self.start() is False:
                    self._rollback_quick_start()
            else:
                self._link_existing_proxy(endpoint, provider='xianniu')
        finally:
            self._xianniu_starting = False

    def _link_existing_proxy(self, endpoint, provider='system', mode=None):
        from .existing_proxy import read_clash_accounting
        port = endpoint['port']
        try:
            snapshot = self._quick_snapshot(None)
        except (OSError, ValueError):
            from tkinter import messagebox
            messagebox.showerror(self._t('Cannot save configuration'), self._t('The configuration could not be saved. Choose a writable location and check file permissions.'), parent=self.root)
            return
        self._quick_rollback = snapshot
        previous_mode = self.vars['product_mode'].get() if 'product_mode' in self.vars else None
        if previous_mode is not None:
            target_mode = 'accelerator' if provider == 'xianniu' else 'mixed' if mode=='mixed' else 'game'
            if self.product_mode() != target_mode and hasattr(self, '_selected_product_mode'):
                self.set_product_mode(target_mode)
            else:
                self.vars['product_mode'].set(target_mode)
        plan = self._configure_lan((port,), commit=False)
        if not plan:
            self._rollback_quick_start()
            return
        self._quick_rollback = snapshot
        self._apply_lan(plan)
        if not (self.raw.get('existing_proxy_port') or self.raw.get('host_relay') == 'steam'):
            previous = {key: variable.get() for key, variable in self.vars.items()
                        if key in ('profile_file', 'subscription_file', 'subscription_url', 'engine_mode')}
            previous['product_mode'] = previous_mode or 'game'
            previous.update({key: copy.deepcopy(self.raw[key]) for key in
                             ('source_provenance', 'node_policies', 'host_profile_overlay', 'workspace_target', 'shared_core', 'local_proxy_port') if key in self.raw})
            self.raw['linked_previous_source'] = previous
        self.vars['engine_mode'].set('external')
        self.vars['profile_file'].set('')
        self.vars['subscription_file'].set('')
        self.vars['subscription_url'].set('')
        self.vars['selection_mode'].set('auto')
        self.vars['preferred_node'].set('')
        self.raw['existing_proxy_port'] = port
        self.raw.pop('host_relay', None)
        self.raw.pop('accelerator_proxy', None)
        self.raw['existing_proxy_provider'] = provider
        if provider == 'xianniu' and hasattr(self.view, 'accelerator_source_var'):
            self.view.accelerator_source_var.set('http')
            self.view.accelerator_port_var.set(str(port))
        self.clash_info = read_clash_accounting() if provider == 'system' else None
        self.view.subscription_info = self.clash_info
        self.view.refresh()
        if self.start() is False:
            self._rollback_quick_start()
            return
        self.show_connection_result()

    def inspect_provider(self):
        from tkinter import messagebox
        from .profiles import inspect_profile
        path = self.vars['profile_file'].get() or self.vars['subscription_file'].get()
        try:
            if not path:
                raise ValueError('Choose a local YAML file first.')
            self.view.preview = inspect_profile(Path(path))
            self.view.refresh()
        except (OSError, ValueError) as error:
            messagebox.showerror(self._t('Cannot inspect provider'), self._t(str(error)), parent=self.root)

    def import_subscription(self, force=False):
        if self.product_mode() == 'accelerator':
            self.subscription_message = 'Switch to a normal mode to import subscriptions. Accelerator settings are separate.'
            self.view.refresh()
            return
        if self.closing or self.importing or getattr(self, 'setting_up', False) or self.backend.process is not None:
            return
        from tkinter import messagebox
        from urllib.parse import urlsplit
        url = self.vars['subscription_url'].get().strip()
        if not force and self.subscription_ready():
            self.subscription_message = 'Already imported. Start sharing or refresh explicitly.'
            self.view.refresh()
            return
        try:
            parsed = urlsplit(url)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment
                    or len(url) > 8192 or not parsed.hostname.isascii()
                    or any(c in parsed.netloc for c in '\\%')
                    or parsed.port is not None and not 1 <= parsed.port <= 65535
                    or any(ord(c) <= 32 for c in url)):
                raise ValueError()
        except ValueError:
            self.subscription_message = 'Enter a valid HTTPS subscription URL.'
            self.view.refresh()
            return
        self.importing = True
        self._import_generation += 1
        generation = self._import_generation
        cancelled = threading.Event()
        # Never let a delayed download use a newly selected configuration path
        # or send the user back from a page they visited while it was running.
        owner_path = self.path
        navigation = self.view.navigation_generation
        self._active_import = (generation, cancelled, owner_path, navigation, url)
        self.running_controls(True)
        self._set_status('Preparing')
        self.backend.log(self._t('Importing subscription…'))
        def work():
            target = None
            try:
                from .core import download_subscription
                from .profiles import inspect_profile
                folder = owner_path.parent / 'profiles'
                folder.mkdir(mode=0o700, parents=True, exist_ok=True)
                fd, filename = tempfile.mkstemp(prefix='import-', suffix='.yaml', dir=folder)
                os.close(fd); target = Path(filename)
                metadata = download_subscription(url, target)
                inspect_profile(target)
                if isinstance(metadata, dict):
                    from .core import atomic_private
                    atomic_private(target.with_suffix(target.suffix + '.info.json'), json.dumps(metadata).encode())
                with self._import_lock:
                    if not cancelled.is_set():
                        self.import_events.put((generation, target, None))
                        return
                self._discard_import(target)
            except Exception:
                if target is not None:
                    self._discard_import(target)
                with self._import_lock:
                    if not cancelled.is_set():
                        self.import_events.put((generation, None, 'Subscription import failed. Check the URL and connection.'))
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _discard_import(path):
        if path is not None:
            for item in (path, path.with_suffix(path.suffix + '.info.json')):
                try:
                    item.unlink(missing_ok=True)
                except OSError:
                    pass

    def cancel_preparation(self):
        if not self.importing:
            return
        self._import_generation += 1
        with self._import_lock:
            if self._active_import:
                self._active_import[1].set()
            # A completed worker may have queued its result just before Cancel.
            # Clear owned files now, even if Close destroys the event loop next.
            while True:
                try:
                    _, path, _ = self.import_events.get_nowait()
                except queue.Empty:
                    break
                self._discard_import(path)
        self._active_import = None
        self.importing = False
        self.quick_start_pending = False
        self.subscription_message = 'Import cancelled. Paste again to retry.'
        self.running_controls(False)
        self._set_status('Stopped')
        self.backend.log(self._t('Preparation cancelled.'))

    def _poll_import(self):
        from tkinter import messagebox
        while True:
            try:
                generation, path, error = self.import_events.get_nowait()
            except queue.Empty:
                return
            active = self._active_import
            if (self.closing or not active or generation != active[0]
                    or active[2] != self.path):
                self._discard_import(path)
                continue
            break
        self._active_import = None
        self.importing = False
        self.running_controls(self.backend.process is not None)
        self.quick_start_pending = False
        if error:
            self._set_status('Stopped with error')
            self.subscription_message = ('Refresh failed. Previous import is still available.'
                                         if self.subscription_ready() else error)
            self.view.refresh()
        else:
            self._set_status('Stopped')
            # Import is independent of network setup and never starts a listener.
            # Refreshing the same URL must not discard its saved node choices
            # merely because the downloader uses a new private filename.
            previous_policies = copy.deepcopy(getattr(self, 'raw', {}).get('node_policies'))
            origin = getattr(self, 'raw', {}).get('source_provenance')
            current_source = next((self.vars[key].get().strip() for key in ('profile_file', 'subscription_file')
                                   if getattr(self, 'vars', {}).get(key) and self.vars[key].get().strip()), '')
            same_source = (len(active) > 4 and isinstance(origin, dict)
                           and origin.get('kind') == 'subscription' and origin.get('url') == active[4]
                           and origin.get('path') == current_source)
            if not self._use_imported_file(path, origin_url=active[4] if len(active) > 4 else None):
                self._discard_import(path)
                return
            if same_source and previous_policies is not None:
                self.raw['node_policies'] = previous_policies
            self.subscription_message = 'Subscription imported. Start sharing when ready.'
            try:
                self._persist_import()
            except (OSError, ValueError):
                self.subscription_message = 'Imported for this session. Could not save; check file permissions.'
            self.view.refresh()

    def _quick_snapshot(self, imported_path):
        previous = None
        if self.path.exists():
            if self.path.is_symlink():
                raise ValueError('Choose a regular configuration file, not a symbolic link')
            with self.path.open('rb') as stream:
                previous = stream.read(MAX_CONFIG_BYTES + 1)
            if len(previous) > MAX_CONFIG_BYTES:
                raise ValueError('Configuration is too large')
        return dict(path=self.path, previous=previous, raw=copy.deepcopy(self.raw),
                    values={key: variable.get() for key, variable in self.vars.items()},
                    preview=self.view.preview, subscription_info=self.view.subscription_info,
                    setup_network=self.view.setup_network, dirty=self.dirty, imported=imported_path,
                    automatic=getattr(self, '_lan_automatic', False),
                    selected_mode=getattr(self, '_selected_product_mode', self.product_mode()),
                    accelerator_ui=self._accelerator_preferences())

    def _rollback_quick_start(self):
        snapshot = getattr(self, '_quick_rollback', None)
        self._quick_rollback = None
        if not snapshot or snapshot['path'] != self.path:
            return
        restored = True
        try:
            if 'written' in snapshot:
                if self.path.is_symlink():
                    raise OSError('Configuration path changed')
                with self.path.open('rb') as stream:
                    current = stream.read(len(snapshot['written']) + 1)
                if current != snapshot['written']:
                    raise OSError('Configuration changed outside this start attempt')
                if snapshot['previous'] is None:
                    self.path.unlink(missing_ok=True)
                else:
                    from .core import atomic_private
                    atomic_private(self.path, snapshot['previous'])
        except OSError:
            restored = False
            self.backend.log(self._t('Previous settings could not be restored on disk. Review the configuration before restarting.'))
        self.raw = snapshot['raw']
        self.loading = True
        for key, value in snapshot['values'].items():
            self.vars[key].set(value)
        self.loading = False
        for key in ('preview', 'subscription_info', 'setup_network'):
            setattr(self.view, key, snapshot[key])
        self.dirty = snapshot['dirty']
        self._lan_automatic = snapshot['automatic']
        self._selected_product_mode = snapshot.get('selected_mode', self.product_mode())
        if hasattr(self.view, 'load_accelerator_source') and snapshot.get('accelerator_ui'):
            loading = self.loading
            self.loading = True
            try:
                self.view.load_accelerator_source({'accelerator_preferences': snapshot['accelerator_ui']})
            finally:
                self.loading = loading
        if restored:
            self._discard_import(snapshot['imported'])
        self.backend.secrets = secret_values(self.raw)
        self.engine_controls()
        self.view.refresh()

    def copy_address(self):
        from tkinter import messagebox
        from .profiles import connection_details
        try:
            info = connection_details(self.collect())
            self.root.clipboard_clear()
            self.root.clipboard_append(f"{info['host']}:{info['port']}")
            self.backend.log(self._t('Address copied.'))
        except ValueError as error:
            messagebox.showerror(self._t('Check configuration'), self._t(str(error)), parent=self.root)

    def _export(self, client=False):
        from tkinter import filedialog, messagebox
        from .profiles import connection_details, client_config
        try:
            values = self.collect()
            data = client_config(values) if client else connection_details(values)
            name = filedialog.asksaveasfilename(title=self._t('Export Clash client…' if client else 'Export connection guide…'),
                defaultextension='.yaml' if client else '.json', parent=self.root)
            if name:
                from .core import atomic_private
                atomic_private(Path(name), json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))
                self.backend.log(self._t('Connection guide exported.'))
        except (OSError, ValueError) as error:
            messagebox.showerror(self._t('Cannot export'), self._t(str(error)), parent=self.root)

    def export_guide(self):
        self._export()

    def export_client(self):
        self._export(client=True)

    def choose_native(self):
        from tkinter import filedialog
        name = filedialog.askopenfilename(title=self._t('Choose your verified PSPortal native engine executable'), parent=self.root)
        if name:
            self.vars['native_path'].set(name)

    def collect(self) -> dict:
        values = dict(self.raw)
        if self.raw.get('shared_core'):
            values['shared_core']=(self.product_mode() in ('game','mixed') and self.vars['engine_mode'].get()=='external'
                and not (self.raw.get('existing_proxy_port') or self.raw.get('host_relay') or self.raw.get('accelerator_proxy')))
            selected=getattr(self,'_shared_local_port',None)
            if values['shared_core'] and selected and selected[0]==self.path:values['local_proxy_port']=selected[1]
        if getattr(self,'_workspace_target',None) in ('lan','hotspot','local'):
            values['workspace_target']=self._workspace_target
        for key, variable in self.vars.items():
            value = variable.get().strip()
            if key in INTEGER_FIELDS:
                try:
                    value = int(value)
                except ValueError:
                    raise ValueError(key + ' must be an integer') from None
            elif key == 'allowed_clients':
                value = [part.strip() for part in value.split(',') if part.strip()]
            values[key] = value
        if values.get('product_mode') == 'accelerator':
            transport = self.view.accelerator_source_var.get() if hasattr(self.view, 'accelerator_source_var') else 'host'
            values['accelerator_preferences'] = self._accelerator_preferences()
            values['engine_mode'] = 'external'
            values['live_node_controls'] = False
            for key in ('subscription_url', 'subscription_file', 'profile_file'):
                values[key] = ''
            if transport == 'host':
                values['host_relay'] = 'steam'
                for key in ('accelerator_proxy', 'existing_proxy_port', 'existing_proxy_provider'):
                    values.pop(key, None)
            else:
                port_text = self.view.accelerator_port_var.get().strip()
                if (transport not in ('http', 'socks5') or not re.fullmatch(r'[0-9]{1,5}', port_text, re.ASCII)
                        or not 1024 <= int(port_text) <= 65535):
                    raise ValueError('Enter a local proxy port from 1024 to 65535.')
                port = int(port_text)
                values.pop('host_relay', None)
                if transport == 'http' and values.get('existing_proxy_provider') == 'xianniu' and values.get('existing_proxy_port') == port:
                    values.pop('accelerator_proxy', None)
                else:
                    values.pop('existing_proxy_port', None)
                    values.pop('existing_proxy_provider', None)
                    values['accelerator_proxy'] = dict(host='127.0.0.1', port=port, protocol=transport)
        if (values.get('engine_mode') == 'external' and not values.get('existing_proxy_port')
                and values.get('host_relay') != 'steam' and not values.get('accelerator_proxy')):
            values['live_node_controls'] = True
        if 'product_mode' in self.vars:
            allowed_modes = ('game', 'accelerator') if (values.get('host_relay') == 'steam'
                or values.get('existing_proxy_provider') == 'xianniu') else ('game','mixed')
            if (values.get('existing_proxy_port') or values.get('host_relay') == 'steam') and values.get('product_mode') not in allowed_modes:
                raise ValueError('Linked proxy supports Game and Mixed modes. Nodes remain managed in the existing client.')
            values['product_lan_automatic'] = getattr(self, '_lan_automatic', product_modes.infer_automatic(self.raw))
            values = product_modes.effective_config(values)
        return values

    def save(self) -> bool:
        from tkinter import messagebox
        try:
            values = self.collect()
            save_config(self.path, values)
        except ValueError as error:
            messagebox.showerror(self._t('Check configuration'), self._t(redact_log(str(error), secret_values(self.raw))), parent=self.root)
            return False
        except OSError:
            messagebox.showerror(self._t('Cannot save configuration'), self._t('The configuration could not be saved. Choose a writable location and check file permissions.'), parent=self.root)
            return False
        self.raw = values
        self.dirty = False
        self.backend.secrets = secret_values(values)
        self.backend.log('Configuration saved and validated. No connection was made.')
        return True

    def running_controls(self, running: bool):
        self.view.quick_button.configure(state='disabled' if running else 'normal')
        self.view.link_button.configure(state='disabled' if running else 'normal')
        if hasattr(self.view, 'xianniu_button'):
            self.view.xianniu_button.configure(state='disabled' if running else 'normal')
        if hasattr(self.view, 'steam_button'):
            self.view.steam_button.configure(state='disabled' if running else 'normal')
        self.start_button.configure(state='disabled' if running else 'normal')
        self.save_button.configure(state='disabled' if running else 'normal')
        self.choose_button.configure(state='disabled' if running else 'normal')
        self.stop_button.configure(state='normal' if running else 'disabled')
        for widget, normal in self.inputs:
            widget.configure(state='disabled' if running else normal)
        if not running:
            self.engine_controls()
        self.view.refresh()

    def start(self):
        from tkinter import messagebox
        if (self.closing or self.importing or getattr(self, 'setting_up', False)
                or getattr(self, 'xianniu_checking', False)):
            return False
        if self.backend.process is not None and self.backend.process.poll() is None:
            return False
        if self.raw.get('existing_proxy_provider') == 'xianniu' and not getattr(self, '_xianniu_starting', False):
            self.use_xianniu_proxy(action='manual')
            return False
        if self.vars['subscription_url'].get().strip() and not self.subscription_ready():
            self.subscription_message = 'Link changed. Press Enter or paste to import before starting.'
            self.view.refresh()
            return False
        if (self.vars.get('engine_mode') and self.vars['engine_mode'].get() == 'external'
                and not self.raw.get('existing_proxy_port') and self.raw.get('host_relay') != 'steam'
                and self.product_mode() != 'accelerator'
                and not Path(self.vars['core_path'].get()).is_file()):
            self.setup_core(start_after='manual')
            return False
        if not self.save():
            return False
        snapshot = getattr(self, '_quick_rollback', None)
        if snapshot and snapshot['path'] == self.path:
            snapshot['written'] = (json.dumps(self.raw, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        self.statistics = None
        self.node_state = None
        self.pending_command = None
        self.view.node_message = ''
        try:
            self.backend.start(self.path, self.raw)
        except (OSError, RuntimeError, ValueError):
            message = ('The experimental embedded engine could not start. Check its executable path, OS/CPU compatibility and permissions. No engine switch was made.'
                       if self.raw.get('engine_mode') == 'embedded' else
                       'The listener process could not start. Check the application files and executable permissions.')
            messagebox.showerror(self._t('Cannot start listener'), self._t(message), parent=self.root)
            self._set_status('Stopped with error')
            return False
        self.running_controls(True)
        self._pending_node_request = None
        self._reported_command = None
        self.view.runtime = None
        self._set_status('Preparing')
        return True

    def stop(self):
        if getattr(self, 'xianniu_checking', False):
            self._xianniu_generation += 1
            self.xianniu_checking = False
            self.xianniu_message = 'Xianniu check cancelled.'
            self.running_controls(False)
            return
        if self.importing:
            self.cancel_preparation()
            return
        if self.backend.process is None:
            return
        self.backend.stop()
        self.stop_button.configure(state='disabled')
        self._set_status('Stopping…')

    def _legacy_node_command(self, action):
        snapshot = self.backend.snapshot() or {}
        if (self.closing or self.importing or self.pending_command is not None
                or self._pending_node_request is not None or self.backend.stopping_since is not None
                or snapshot.get('busy')):
            return
        if self.raw.get('existing_proxy_port'):
            self.view.node_message = 'Node controls are managed by the existing Clash client.'
            self.view.refresh()
            return
        group = self.view.group_var.get()
        selected = self.view.live_node_table.selection()
        name = self.view.live_node_table.item(selected[0], 'values')[0] if selected else None
        if action == 'select' and not name:
            self.view.node_message = 'Choose a node, then click Switch node.'
            self.view.refresh()
            return
        self.command_id = max(self.command_id, self._node_request) + 1
        self._node_request = self.command_id
        try:
            self.backend.command(self.command_id, action, group=group, name=name)
            self.pending_command = self.command_id
            self._node_protocol = 'legacy'
            self._pending_node_request = (self.backend.process, self.command_id)
            self.view.node_message = 'Testing latency…' if action in ('test', 'latency') else 'Updating nodes…'
        except (OSError, ValueError, RuntimeError):
            self.view.node_message = 'Start the listener first.'
        self.view.refresh()

    def _poll_updates(self):
        for _ in range(100):
            try: event = self.backend.updates.get_nowait()
            except queue.Empty: break
            if event['kind'] == 'statistics':
                self.statistics = event
            elif event['kind'] == 'nodes':
                self.node_state = event
                if self.pending_command is None and getattr(self, '_node_protocol', None) == 'legacy' and event.get('message'):
                    self.view.node_message = event['message']
                if event.get('id') == self.pending_command and self.pending_command is not None:
                    self.pending_command = None
                    self._pending_node_request = None
                    self.view.node_message = event.get('message', '')
                    self._save_node_policies(event.get('policies'))
            elif event['kind'] == 'control_error' and event.get('id') == self.pending_command:
                self.pending_command = None
                self._pending_node_request = None
                self.view.node_message = event['message']
        self.view.refresh()

    def poll(self):
        self._poll_setup()
        self._poll_xianniu()
        self._poll_discovery()
        self._poll_subscription_usage()
        self._poll_import()
        self._poll_updates()
        self._poll_runtime()
        for _ in range(100):
            try:
                line = self.backend.events.get_nowait()
            except queue.Empty:
                break
            self.log_widget.configure(state='normal')
            self.log_widget.insert('end', line + '\n')
            self.view.observe(line)
            count = int(self.log_widget.index('end-1c').split('.')[0])
            if count > MAX_LOG_LINES:
                self.log_widget.delete('1.0', f'{count - MAX_LOG_LINES}.0')
            self.log_widget.see('end')
            self.log_widget.configure(state='disabled')
        if self.backend.ready and self.backend.stopping_since is None:
            self._quick_rollback = None
            states = {'preparing': 'Preparing', 'listening': 'Listening', 'waking': 'Waking',
                      'forwarding': 'Forwarding', 'error': 'Error', 'stopped': 'Stopped'}
            state = (self.view.runtime or {}).get('state')
            self._set_status(states.get(state, 'Listening'))
        process = self.backend.process
        if process is not None:
            result = self.backend.poll()
            if result is not None:
                self._rollback_quick_start()
                self._set_status('Stopped' if result == 0 else 'Stopped with error')
                self.statistics = None
                self.node_state = None
                self.pending_command = None
                self._poll_runtime()
                self.backend.log('Listener exited.' if result == 0 else f'Listener exited with code {result}.')
                self.running_controls(False)
        hub=getattr(self,'games_hub',None)
        games_done = not self.closing or hub is None or hub.shutdown_complete()
        if self.closing and self.backend.process is None and not self.importing and games_done:
            self.root.destroy()
            return
        self.root.after(150, self.poll)

    def close(self):
        from tkinter import messagebox
        if self.closing:
            return
        running = self.backend.process is not None and self.backend.process.poll() is None
        hub=getattr(self,'games_hub',None)
        games_running=bool(hub and hub.running)
        if not running and getattr(self, '_quick_rollback', None):
            # Close can arrive after the child exits but before the next poll.
            # Settle ownership now so destroying Tk cannot lose the rollback.
            if self.backend.ready:
                self._quick_rollback = None
            else:
                self._rollback_quick_start()
            if self.backend.process is not None:
                self.backend.poll()
        question = ('Stop sharing and game acceleration, then close?' if games_running else 'Stop the listener and its core, then close?' if running else
                    'Cancel preparation and close?' if self.importing else
                    'Close and discard unsaved configuration edits?')
        if (running or games_running or self.dirty or self.importing) and not messagebox.askyesno(self._t('Close StarPass?'), self._t(question), parent=self.root):
            return
        self.closing = True
        if hub:hub.close()
        if self.importing:
            self.cancel_preparation()
        if running:
            self.stop()
        elif not self.importing and hub is None:
            self.root.destroy()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='StarPass desktop application')
    parser.add_argument('--config', type=Path, default=default_config_path())
    parser.add_argument('--page',choices=('home','overview','games'),default='home')
    args = parser.parse_args(argv)
    try:
        import tkinter as tk
        root = tk.Tk()
    except (ImportError, RuntimeError) as error:
        print('Desktop UI requires Python with Tk and a graphical desktop.', file=sys.stderr)
        return 2
    except Exception as error:
        # TclError is unavailable if the import itself fails.
        if error.__class__.__name__ != 'TclError':
            raise
        print('Desktop UI could not open a display. Use the CLI on headless systems.', file=sys.stderr)
        return 2
    application=DesktopApp(root, args.config)
    if args.page=='games':application.open_game_accelerator()
    elif args.page=='home' and sys.platform=='win32':application.view.show('Workspaces')
    elif args.page=='home' and application.product_mode()=='accelerator':application.view.show('Games')
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
