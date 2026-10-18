"""Small local-only Tk desktop shell; the proxy stays in a child process.

Importing this module does not require a display or start network activity.
"""
from __future__ import annotations

import argparse
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

from . import config, backend as engine_backend

MAX_CONFIG_BYTES = 1024 * 1024
MAX_LOG_LINES = 500
FIELDS = (
    ('listen_host', 'Listener IPv4 (LAN for Portal)'),
    ('listen_port', 'Portal proxy port'),
    ('allowed_clients', 'Portal IPv4 addresses (comma-separated)'),
    ('engine_mode', 'Engine (embedded is experimental)'),
    ('core_path', 'Mihomo executable'),
    ('native_path', 'Embedded engine executable'),
    ('subscription_url', 'HTTPS subscription URL'),
    ('subscription_file', 'Local provider file (overrides URL)'),
    ('selection_mode', 'Node selection'),
    ('preferred_node', 'Preferred / fixed node name'),
    ('idle_seconds', 'Idle timeout (seconds)'),
    ('backend_port', 'Local core port'),
    ('api_port', 'Local controller port'),
)
INTEGER_FIELDS = {'listen_port', 'backend_port', 'api_port', 'idle_seconds'}


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


def save_config(path: Path, values: dict) -> None:
    """Validate and atomically replace a private file; never leave partial JSON."""
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
        config.load(temporary)  # Field-only validation messages; no network or execution.
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def secret_values(values: dict) -> tuple[str, ...]:
    secrets = set()
    for key in ('subscription_url', 'health_url'):
        value = values.get(key)
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
            try:
                self.events.put_nowait(redact_log(line, self.secrets if secrets is None else secrets))
            except queue.Full:
                pass
        try:
            with process.stdout:
                while True:
                    from .runtime import PREFIX, MAX_EVENT
                    line = process.stdout.readline(MAX_EVENT + 1)
                    if not line:
                        break
                    if line.startswith(PREFIX) and len(line.encode('utf-8')) <= MAX_EVENT:
                        try:
                            event = json.loads(line[len(PREFIX):])
                            with self._state_lock:
                                owned = self.process is process
                            if owned and isinstance(event, dict) and event.get('kind') in ('statistics', 'nodes', 'control_error'):
                                self.updates.put_nowait(event)
                        except (ValueError, queue.Full):
                            pass
                        continue
                    if len(line) > 4096:
                        # Drop the entire oversized record, not split tokens.
                        while line and not line.endswith('\n'):
                            line = process.stdout.readline(4097)
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

    def command(self, request_id, action, **values):
        process = self.process
        if process is None or process.poll() is not None or self.stopping_since is not None:
            raise RuntimeError('Start the listener first.')
        line = json.dumps(dict(id=request_id, action=action, **values), ensure_ascii=False) + '\n'
        if len(line.encode('utf-8')) > 8192:
            raise ValueError('Node command is too large')
        with self._write_lock:
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
        self.import_events = queue.Queue()
        self.command_id = 0
        self.pending_command = None
        self.statistics = None
        self.node_state = None
        self.inputs = []
        self.engine_inputs = {}
        self.profile_selection_inputs = []
        from .existing_proxy import detect_system_proxy, read_clash_accounting
        self.existing_proxy = detect_system_proxy()
        self.clash_info = read_clash_accounting() if self.existing_proxy else None
        from .desktop_view import DesktopView
        self.view = DesktopView(self)
        self.load()
        root.after(150, self.poll)

    def _changed(self, *_):
        if not self.loading:
            if _ and 'subscription_url' in self.vars and str(self.vars['subscription_url']) == _[0]:
                self.view.subscription_info = None
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

    def set_language(self, language):
        from .i18n import save_language
        self.view.set_language(language)
        self.engine_controls()
        try:
            save_language(self.path, language)
        except (OSError, ValueError):
            self.backend.log(self._t('Preferences could not be saved. Language changed for this session.'))

    def set_theme(self, theme):
        from .i18n import save_theme
        self.view.set_theme(theme)
        try:
            save_theme(self.path, theme)
        except (OSError, ValueError):
            self.backend.log('Appearance preference could not be saved.')

    def engine_controls(self):
        running = (self.backend.process is not None and self.backend.process.poll() is None) or self.importing
        mode = self.vars['engine_mode'].get() if 'engine_mode' in self.vars else 'external'
        for key, widgets in self.engine_inputs.items():
            active = mode == ('embedded' if key == 'native_path' else 'external')
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
        except (OSError, UnicodeError, ValueError):
            messagebox.showerror(self._t('Cannot open configuration'), self._t('The file could not be read as a JSON configuration. Choose a different file.'), parent=self.root)
            self.raw = {}
        defaults = dict(config.DEFAULTS, listen_host='', allowed_clients=[], core_path='', subscription_url='',
                        native_path=str(config.bundled_native_path() or ''))
        defaults.update(self.raw)
        source = self.raw.get('profile_file') or self.raw.get('subscription_file')
        if source:
            try:
                metadata = Path(source).with_suffix(Path(source).suffix + '.info.json')
                if metadata.is_file() and metadata.stat().st_size <= 8192:
                    self.view.subscription_info = read_config(metadata)
            except (ValueError, OSError):
                pass
        elif self.raw.get('existing_proxy_port') or not self.raw.get('subscription_url'):
            self.view.subscription_info = self.clash_info
        self.loading = True
        for key, variable in self.vars.items():
            value = defaults.get(key, '')
            if key == 'allowed_clients':
                value = ', '.join(str(item) for item in value) if isinstance(value, list) else ''
            variable.set(str(value))
        self.loading = False
        self.dirty = False
        self.path_var.set(str(self.path))
        from .i18n import load_language
        self.view.set_language(load_language(self.path))
        from .i18n import load_theme
        self.view.set_theme(load_theme(self.path))
        self.engine_controls()
        self.view.refresh()

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
            self.vars['core_path'].set(name)

    def choose_provider(self):
        from tkinter import filedialog
        name = filedialog.askopenfilename(title=self._t('Choose local Clash/Mihomo provider YAML'), filetypes=[('YAML provider', '*.yaml *.yml'), ('All files', '*')], parent=self.root)
        if name:
            self._use_imported_file(Path(name))

    def choose_profile(self):
        from tkinter import filedialog
        name = filedialog.askopenfilename(title=self._t('Complete Clash/Mihomo profile'),
            filetypes=[('YAML', '*.yaml *.yml *.json'), ('All files', '*')], parent=self.root)
        if name:
            self._use_imported_file(Path(name), full=True)

    def _use_imported_file(self, path, full=False):
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
            if str(path.absolute()) != (self.raw.get('profile_file') or self.raw.get('subscription_file')):
                self.raw.pop('node_policies', None)
            self.raw.pop('existing_proxy_port', None)
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

    def quick_start(self):
        if self.importing or self.backend.process is not None:
            return
        self.raw.pop('existing_proxy_port', None)
        if not self._configure_lan(): return
        self.quick_start_pending = True
        self.import_subscription()
        if not self.importing:
            self.quick_start_pending = False

    def _configure_lan(self, reserved=()):
        from tkinter import messagebox
        from .setup import discover_lan, available_port
        try:
            network = discover_lan()
            chosen = set(reserved)
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
                self.vars[key].set(str(selected))
            self.vars['listen_host'].set(network['host'])
            self.vars['allowed_clients'].set(', '.join(network['clients']))
            self.view.setup_network = network['subnet']
            self.view.refresh()
            return True
        except ValueError as error:
            messagebox.showerror(self._t('Check configuration'), self._t(str(error)), parent=self.root)
            return False

    def use_existing_proxy(self):
        if self.importing or self.backend.process is not None: return
        from .existing_proxy import detect_system_proxy, read_clash_accounting
        self.existing_proxy = detect_system_proxy()
        if not self.existing_proxy:
            from tkinter import messagebox
            messagebox.showinfo(self._t('Existing proxy'), self._t('No active loopback HTTP system proxy was detected.'), parent=self.root)
            return
        port = self.existing_proxy['port']
        if not self._configure_lan((port,)): return
        self.vars['engine_mode'].set('external')
        self.vars['profile_file'].set('')
        self.vars['subscription_file'].set('')
        self.vars['selection_mode'].set('auto')
        self.vars['preferred_node'].set('')
        self.raw['existing_proxy_port'] = port
        self.clash_info = read_clash_accounting()
        self.view.subscription_info = self.clash_info
        self.view.refresh()
        self.start()
        self.view.show('LAN sharing')

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

    def import_subscription(self):
        if self.importing or self.backend.process is not None:
            return
        from tkinter import messagebox
        from urllib.parse import urlsplit
        url = self.vars['subscription_url'].get().strip()
        try:
            parsed = urlsplit(url)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment
                    or any(ord(c) <= 32 for c in url)):
                raise ValueError()
        except ValueError:
            messagebox.showerror(self._t('Check configuration'), self._t('Enter a valid HTTPS subscription URL.'), parent=self.root)
            return
        self.importing = True
        self._set_status('Importing subscription…')
        self.view.quick_button.configure(state='disabled')
        self.view.link_button.configure(state='disabled')
        for widget, _ in self.inputs:
            widget.configure(state='disabled')
        self.start_button.configure(state='disabled')
        self.save_button.configure(state='disabled')
        self.choose_button.configure(state='disabled')
        self.backend.log(self._t('Importing subscription…'))
        def work():
            target = None
            try:
                from .core import download_subscription
                from .profiles import inspect_profile
                folder = self.path.parent / 'profiles'
                folder.mkdir(mode=0o700, parents=True, exist_ok=True)
                fd, filename = tempfile.mkstemp(prefix='import-', suffix='.yaml', dir=folder)
                os.close(fd); target = Path(filename)
                metadata = download_subscription(url, target)
                inspect_profile(target)
                if isinstance(metadata, dict):
                    from .core import atomic_private
                    atomic_private(target.with_suffix(target.suffix + '.info.json'), json.dumps(metadata).encode())
                self.import_events.put((target, None))
            except Exception:
                if target is not None:
                    target.unlink(missing_ok=True)
                self.import_events.put((None, 'Subscription import failed. Check the URL and connection.'))
        threading.Thread(target=work, daemon=True).start()

    def _poll_import(self):
        from tkinter import messagebox
        try:
            path, error = self.import_events.get_nowait()
        except queue.Empty:
            return
        self.importing = False
        self.running_controls(self.backend.process is not None)
        if self.closing:
            return
        pending, self.quick_start_pending = self.quick_start_pending, False
        if error:
            self._set_status('Stopped with error')
            messagebox.showerror(self._t('Cannot inspect provider'), self._t(error), parent=self.root)
        else:
            self._set_status('Stopped')
            if self._use_imported_file(path) and pending and self._configure_lan():
                self.start()
                self.view.show('LAN sharing')

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
        if values.get('engine_mode') == 'external' and not values.get('existing_proxy_port'):
            values['live_node_controls'] = True
        return values

    def save(self) -> bool:
        from tkinter import messagebox
        try:
            values = self.collect()
            save_config(self.path, values)
        except ValueError as error:
            messagebox.showerror(self._t('Check configuration'), redact_log(str(error), secret_values(self.raw)), parent=self.root)
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
        self.start_button.configure(state='disabled' if running else 'normal')
        self.save_button.configure(state='disabled' if running else 'normal')
        self.choose_button.configure(state='disabled' if running else 'normal')
        self.stop_button.configure(state='normal' if running else 'disabled')
        for widget, normal in self.inputs:
            widget.configure(state='disabled' if running else normal)
        if not running:
            self.engine_controls()

    def start(self):
        from tkinter import messagebox
        if self.backend.process is not None and self.backend.process.poll() is None:
            return
        if not self.save():
            return
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
            return
        self.running_controls(True)
        self._set_status('Process running')

    def stop(self):
        self.backend.stop()
        self.stop_button.configure(state='disabled')
        self._set_status('Stopping…')

    def node_command(self, action):
        if self.pending_command is not None:
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
        self.command_id += 1
        try:
            self.backend.command(self.command_id, action, group=group, name=name)
            self.pending_command = self.command_id
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
                if self.pending_command is None and event.get('message'):
                    self.view.node_message = event['message']
                if event.get('id') == self.pending_command and self.pending_command is not None:
                    self.pending_command = None
                    self.view.node_message = event.get('message', '')
                    self.raw['node_policies'] = event.get('policies', {})
                    try: save_config(self.path, self.raw)
                    except (OSError, ValueError):
                        self.view.node_message = 'Selection applied; preference could not be saved.'
            elif event['kind'] == 'control_error' and event.get('id') == self.pending_command:
                self.pending_command = None
                self.view.node_message = event['message']
        self.view.refresh()

    def poll(self):
        self._poll_import()
        self._poll_updates()
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
            self._set_status('Listening')
        process = self.backend.process
        if process is not None:
            result = self.backend.poll()
            if result is not None:
                self._set_status('Stopped' if result == 0 else 'Stopped with error')
                self.statistics = None
                self.node_state = None
                self.pending_command = None
                self.backend.log('Listener exited.' if result == 0 else f'Listener exited with code {result}.')
                self.running_controls(False)
        if self.closing and self.backend.process is None and not self.importing:
            self.root.destroy()
            return
        self.root.after(150, self.poll)

    def close(self):
        from tkinter import messagebox
        if self.closing:
            return
        running = self.backend.process is not None and self.backend.process.poll() is None
        question = 'Stop the listener and its core, then close?' if running else 'Close and discard unsaved configuration edits?'
        if (running or self.dirty or self.importing) and not messagebox.askyesno(self._t('Close PS Portal On-Demand?'), self._t(question), parent=self.root):
            return
        self.closing = True
        if running:
            self.stop()
        elif not self.importing:
            self.root.destroy()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='PS Portal On-Demand desktop application')
    parser.add_argument('--config', type=Path, default=default_config_path())
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
    DesktopApp(root, args.config)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
