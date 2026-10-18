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

from . import config

MAX_CONFIG_BYTES = 1024 * 1024
MAX_LOG_LINES = 500
FIELDS = (
    ('listen_host', 'Listener IPv4 (LAN for Portal)'),
    ('listen_port', 'Portal proxy port'),
    ('allowed_clients', 'Portal IPv4 addresses (comma-separated)'),
    ('core_path', 'Mihomo executable'),
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
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--backend', '--config', str(path), '--desktop-child']
    return [sys.executable, '-u', '-m', 'portalproxy', '--config', str(path), '--desktop-child']


class BackendProcess:
    """Single owned subprocess, bounded logs, and cooperative shutdown on all OSes."""

    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.events: queue.Queue[str] = queue.Queue(maxsize=500)
        self.secrets: tuple[str, ...] = ()
        self.stopping_since: float | None = None
        self._signaled = False
        atexit.register(self.stop)

    def log(self, text: str) -> None:
        try:
            self.events.put_nowait(redact_log(text, self.secrets))
        except queue.Full:
            pass

    def start(self, path: Path, values: dict) -> None:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError('The listener is already running')
        self.secrets = secret_values(values)
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
        self.process = subprocess.Popen(backend_command(path), **kwargs)
        self.stopping_since = None
        self._signaled = False
        self.log('Listener process started. The core wakes only for external traffic.')
        threading.Thread(target=self._read_output, args=(self.process,), daemon=True).start()

    def _read_output(self, process: subprocess.Popen) -> None:
        assert process.stdout is not None
        with process.stdout:
            while True:
                line = process.stdout.readline(4097)
                if not line:
                    break
                if len(line) > 4096:
                    # Drop the entire oversized record, rather than leaking split tokens.
                    while line and not line.endswith('\n'):
                        line = process.stdout.readline(4097)
                    self.log('[Oversized diagnostic omitted]')
                    continue
                self.log(line.rstrip())

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
            return result
        if self.stopping_since is not None and not self._signaled and time.monotonic() - self.stopping_since > 10:
            self._signaled = True
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == 'win32' else signal.SIGTERM)
                self.log('Still stopping; requested graceful shutdown again.')
            except (OSError, ValueError):
                self.log('Shutdown is taking longer than expected. Keep this window open.')
        return None


class DesktopApp:
    def __init__(self, root, path: Path):
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText

        self.root, self.path = root, path.expanduser().absolute()
        self.backend = BackendProcess()
        self.raw: dict = {}
        self.vars = {}
        self.dirty = False
        self.loading = False
        self.closing = False
        self.inputs = []
        root.title('PS Portal On-Demand')
        root.minsize(740, 650)
        root.protocol('WM_DELETE_WINDOW', self.close)
        outer = ttk.Frame(root, padding=16)
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(1, weight=1)
        ttk.Label(outer, text='PS Portal On-Demand', font=('TkDefaultFont', 17, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(outer, text='A local HTTP proxy for your Portal. No system proxy or router changes.').grid(row=1, column=0, columnspan=3, sticky='w', pady=(4, 12))
        self.path_var = tk.StringVar(value=str(self.path))
        ttk.Label(outer, textvariable=self.path_var, wraplength=550).grid(row=2, column=0, columnspan=2, sticky='w')
        self.choose_button = ttk.Button(outer, text='Choose config…', command=self.choose_config)
        self.choose_button.grid(row=2, column=2, sticky='e', pady=(0, 10))
        for row, (key, title) in enumerate(FIELDS, start=3):
            ttk.Label(outer, text=title).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=4)
            variable = tk.StringVar()
            variable.trace_add('write', self._changed)
            self.vars[key] = variable
            if key == 'selection_mode':
                widget = ttk.Combobox(outer, textvariable=variable, values=('auto', 'prefer', 'fixed'), state='readonly')
            else:
                widget = ttk.Entry(outer, textvariable=variable, show='•' if key == 'subscription_url' else '')
            widget.grid(row=row, column=1, columnspan=1 if key in ('core_path', 'subscription_file') else 2, sticky='ew', pady=4)
            self.inputs.append((widget, 'readonly' if key == 'selection_mode' else 'normal'))
            if key in ('core_path', 'subscription_file'):
                browse = ttk.Button(outer, text='Browse…', command=self.choose_core if key == 'core_path' else self.choose_provider)
                browse.grid(row=row, column=2, padx=(8, 0))
                self.inputs.append((browse, 'normal'))
        controls_row = 3 + len(FIELDS)
        controls = ttk.Frame(outer)
        controls.grid(row=controls_row, column=0, columnspan=3, sticky='ew', pady=(12, 8))
        self.save_button = ttk.Button(controls, text='Save / validate', command=self.save)
        self.save_button.pack(side='left')
        self.start_button = ttk.Button(controls, text='Start listener', command=self.start)
        self.start_button.pack(side='left', padx=8)
        self.stop_button = ttk.Button(controls, text='Stop', command=self.stop, state='disabled')
        self.stop_button.pack(side='left')
        self.status_var = tk.StringVar(value='Stopped')
        ttk.Label(controls, textvariable=self.status_var).pack(side='right')
        ttk.Label(outer, text='Keep this computer awake and on the same LAN. Configure the Portal with the LAN IPv4 and proxy port above.', wraplength=680).grid(row=controls_row + 1, column=0, columnspan=3, sticky='w', pady=(0, 8))
        self.log_widget = ScrolledText(outer, height=9, state='disabled', wrap='word')
        self.log_widget.grid(row=controls_row + 2, column=0, columnspan=3, sticky='nsew')
        outer.rowconfigure(controls_row + 2, weight=1)
        self.load()
        root.after(150, self.poll)

    def _changed(self, *_):
        if not self.loading:
            self.dirty = True

    def load(self):
        from tkinter import messagebox
        try:
            self.raw = read_config(self.path) if self.path.exists() else {}
        except (OSError, UnicodeError, ValueError):
            messagebox.showerror('Cannot open configuration', 'The file could not be read as a JSON configuration. Choose a different file.', parent=self.root)
            self.raw = {}
        defaults = dict(config.DEFAULTS, listen_host='', allowed_clients=[], core_path='', subscription_url='')
        defaults.update(self.raw)
        self.loading = True
        for key, variable in self.vars.items():
            value = defaults.get(key, '')
            if key == 'allowed_clients':
                value = ', '.join(str(item) for item in value) if isinstance(value, list) else ''
            variable.set(str(value))
        self.loading = False
        self.dirty = False
        self.path_var.set(str(self.path))

    def choose_config(self):
        from tkinter import filedialog, messagebox
        if self.dirty and not messagebox.askyesno('Discard unsaved edits?', 'Open another configuration and discard these unsaved edits?', parent=self.root):
            return
        name = filedialog.askopenfilename(title='Open configuration', initialdir=self.path.parent, filetypes=[('JSON configuration', '*.json'), ('All files', '*')], parent=self.root)
        if name:
            self.path = Path(name).absolute()
            self.load()

    def choose_core(self):
        from tkinter import filedialog
        name = filedialog.askopenfilename(title='Choose your verified Mihomo executable', parent=self.root)
        if name:
            self.vars['core_path'].set(name)

    def choose_provider(self):
        from tkinter import filedialog
        name = filedialog.askopenfilename(title='Choose local Clash/Mihomo provider YAML', filetypes=[('YAML provider', '*.yaml *.yml'), ('All files', '*')], parent=self.root)
        if name:
            self.vars['subscription_file'].set(name)

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
        return values

    def save(self) -> bool:
        from tkinter import messagebox
        try:
            values = self.collect()
            save_config(self.path, values)
        except ValueError as error:
            messagebox.showerror('Check configuration', redact_log(str(error), secret_values(self.raw)), parent=self.root)
            return False
        except OSError:
            messagebox.showerror('Cannot save configuration', 'The configuration could not be saved. Choose a writable location and check file permissions.', parent=self.root)
            return False
        self.raw = values
        self.dirty = False
        self.backend.secrets = secret_values(values)
        self.backend.log('Configuration saved and validated. No connection was made.')
        return True

    def running_controls(self, running: bool):
        self.start_button.configure(state='disabled' if running else 'normal')
        self.save_button.configure(state='disabled' if running else 'normal')
        self.choose_button.configure(state='disabled' if running else 'normal')
        self.stop_button.configure(state='normal' if running else 'disabled')
        for widget, normal in self.inputs:
            widget.configure(state='disabled' if running else normal)

    def start(self):
        from tkinter import messagebox
        if self.backend.process is not None and self.backend.process.poll() is None:
            return
        if not self.save():
            return
        try:
            self.backend.start(self.path, self.raw)
        except (OSError, RuntimeError):
            messagebox.showerror('Cannot start listener', 'The listener process could not start. Check the application files and executable permissions.', parent=self.root)
            return
        self.running_controls(True)
        self.status_var.set('Process running')

    def stop(self):
        self.backend.stop()
        self.stop_button.configure(state='disabled')
        self.status_var.set('Stopping…')

    def poll(self):
        for _ in range(100):
            try:
                line = self.backend.events.get_nowait()
            except queue.Empty:
                break
            if line.startswith('Proxy ready at ') and self.backend.stopping_since is None:
                self.status_var.set('Listening')
            self.log_widget.configure(state='normal')
            self.log_widget.insert('end', line + '\n')
            count = int(self.log_widget.index('end-1c').split('.')[0])
            if count > MAX_LOG_LINES:
                self.log_widget.delete('1.0', f'{count - MAX_LOG_LINES}.0')
            self.log_widget.see('end')
            self.log_widget.configure(state='disabled')
        process = self.backend.process
        if process is not None:
            result = self.backend.poll()
            if result is not None:
                self.backend.process = None
                self.status_var.set('Stopped' if result == 0 else 'Stopped with error')
                self.backend.log('Listener exited.' if result == 0 else f'Listener exited with code {result}.')
                self.running_controls(False)
        if self.closing and self.backend.process is None:
            self.root.destroy()
            return
        self.root.after(150, self.poll)

    def close(self):
        from tkinter import messagebox
        if self.closing:
            return
        running = self.backend.process is not None and self.backend.process.poll() is None
        question = 'Stop the listener and its core, then close?' if running else 'Close and discard unsaved configuration edits?'
        if (running or self.dirty) and not messagebox.askyesno('Close PS Portal On-Demand?', question, parent=self.root):
            return
        self.closing = True
        if running:
            self.stop()
        else:
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
