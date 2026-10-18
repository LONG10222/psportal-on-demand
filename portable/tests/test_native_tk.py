"""Opt-in real source-Tk widgets on native Windows/macOS/Linux runners.

PSPORTAL_TK_TEST=1 plus PSPORTAL_NATIVE_BINARY enables two actual window tests.
They invoke the real DesktopApp widgets and run real child processes, without
mocking Tk, subscriptions, or application callbacks. Only empty local-provider
fixtures and request-free loopback probes are used. No accessibility, screenshot,
system-proxy, or firewall permissions are requested.

This establishes source GUI lifecycle with native child runtimes. It does NOT
claim that the frozen GUI executable itself opened a window on these platforms;
the independent X11 packaged-window acceptance remains in test_gui.py.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from portalproxy.desktop import DesktopApp
from test_core import port


@unittest.skipUnless(os.environ.get('PSPORTAL_TK_TEST') == '1' and os.environ.get('PSPORTAL_NATIVE_BINARY'),
    'Set PSPORTAL_TK_TEST=1 and PSPORTAL_NATIVE_BINARY on a native graphical runner')
class NativeTkWindowTests(unittest.TestCase):
    def test_source_tk_external_start_stop_restart_close(self):
        self.exercise_window('external')

    def test_source_tk_embedded_start_stop_restart_close(self):
        self.exercise_window('embedded')

    def exercise_window(self, mode):
        import tkinter as tk
        # An explicit opt-in must fail if Tk cannot actually initialize. Never
        # downgrade a failed native graphical run into a headless skip.
        root = tk.Tk()
        app = None
        try:
            with tempfile.TemporaryDirectory(prefix='portal native Tk ') as tmp:
                directory = Path(tmp)
                provider = directory / 'empty provider.json'
                provider.write_text('{"proxies": []}', encoding='utf-8')
                ports = set()
                while len(ports) < 3:
                    ports.add(port())
                listen, backend, api = sorted(ports)
                values = dict(engine_mode=mode, listen_host='127.0.0.1', listen_port=listen,
                    allowed_clients=['127.0.0.1'], backend_port=backend, api_port=api,
                    # Existing trusted executable only; no accepted HTTP
                    # request is sent, so an external core must never start.
                    core_path=sys.executable,
                    native_path=str(Path(os.environ['PSPORTAL_NATIVE_BINARY']).resolve()),
                    subscription_file=str(provider), data_dir=str(directory / 'runtime'))
                path = directory / 'config.json'
                path.write_text(json.dumps(values), encoding='utf-8')
                app = DesktopApp(root, path)

                def wait_for(predicate, state, timeout=25):
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        root.update()
                        if predicate():
                            return
                        time.sleep(.02)
                    self.fail('Timed out waiting for ' + state + '\n' + app.log_widget.get('1.0', 'end'))

                def listening(number):
                    try:
                        with socket.create_connection(('127.0.0.1', number), timeout=.2):
                            return True
                    except OSError:
                        return False

                def assert_idle_core():
                    self.assertFalse(listening(backend), 'The external core must remain asleep')
                    self.assertFalse(listening(api))
                    self.assertFalse(list((directory / 'runtime').glob('session-*/config.json')))
                    self.assertFalse(list((directory / 'runtime').glob('session-*/providers/subscription.yaml')))
                    self.assertNotIn('Core: starting', app.log_widget.get('1.0', 'end'))

                wait_for(root.winfo_viewable, 'a real mapped Tk window')
                self.assertEqual(root.title(), 'PS Portal On-Demand')
                self.assertEqual(app.vars['engine_mode'].get(), mode)
                self.assertEqual(app.status_var.get(), 'Stopped')
                self.assertFalse((directory / 'runtime').exists(), 'Opening the window must not start a listener')
                self.assertFalse(listening(listen))
                first_pid = None
                for _ in range(2):
                    app.start_button.invoke()
                    wait_for(lambda: app.status_var.get() == 'Listening', 'visible Listening status')
                    self.assertTrue(listening(listen))
                    self.assertIsNotNone(app.backend.process)
                    if first_pid is not None:
                        self.assertNotEqual(app.backend.process.pid, first_pid)
                    first_pid = app.backend.process.pid
                    self.assertEqual(str(app.start_button.cget('state')), 'disabled')
                    self.assertEqual(str(app.save_button.cget('state')), 'disabled')
                    self.assertEqual(str(app.stop_button.cget('state')), 'normal')
                    for widget, _ in app.inputs:
                        self.assertEqual(str(widget.cget('state')), 'disabled')
                    private = None
                    if mode == 'embedded':
                        private = Path(app.backend.launch.command[2])
                        self.assertTrue(private.is_file())
                        self.assertEqual(json.loads(private.read_text())['subscription_file'], str(provider))
                    assert_idle_core()
                    app.stop_button.invoke()
                    wait_for(lambda: app.status_var.get() == 'Stopped' and app.backend.process is None,
                             'Stopped status after owned-child exit')
                    self.assertEqual(str(app.start_button.cget('state')), 'normal')
                    self.assertEqual(str(app.save_button.cget('state')), 'normal')
                    self.assertEqual(str(app.stop_button.cget('state')), 'disabled')
                    self.assertFalse(listening(listen))
                    self.assertFalse((directory / 'runtime' / 'owner.lock').exists())
                    self.assertFalse(list((directory / 'runtime').glob('session-*')))
                    if private is not None:
                        self.assertFalse(private.parent.exists(), 'Stop must remove the native private config')
                    assert_idle_core()

                # Invoke the window manager's real close callback while stopped.
                # Native OS modal confirmation dialogs require separate acceptance;
                # no monkeypatch or accessibility automation is used here.
                root.tk.eval(root.protocol('WM_DELETE_WINDOW'))
                self.assertTrue(app.closing)
                self.assertIsNone(app.backend.process)
                try:
                    exists = root.winfo_exists()
                except tk.TclError:
                    exists = False
                self.assertFalse(exists)
                self.assertFalse(listening(listen))
                self.assertFalse(listening(backend))
                self.assertFalse(listening(api))
        finally:
            if app is not None:
                app.backend.stop()
                process = app.backend.process
                if process is not None:
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        process.wait(timeout=10)
                    app.backend.poll()
            # Tcl's event queue can outlive a destroyed Tk root when another
            # test creates a fresh interpreter in this same process. Remove
            # only this test interpreter's leftover timers after app shutdown.
            for callback in root.tk.splitlist(root.tk.call('after', 'info')):
                root.tk.call('after', 'cancel', callback)
            try:
                root.destroy()
            except tk.TclError:
                pass
