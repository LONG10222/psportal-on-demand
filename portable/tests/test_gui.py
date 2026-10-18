"""Opt-in actual frozen Tk window tests on an isolated X11 display.

The controller uses Tk's X11 send command to inspect and invoke real widgets in
the packaged application. No application mocks, real core, or Internet traffic.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest

from test_core import port


@unittest.skipUnless(os.environ.get('PSPORTAL_GUI_TEST') == '1' and os.environ.get('PSPORTAL_BINARY'),
    'Set PSPORTAL_GUI_TEST=1 and PSPORTAL_BINARY under an isolated X11 display')
class FrozenGuiTests(unittest.TestCase):
    def test_actual_window_start_stop_restart_and_close(self):
        import tkinter as tk
        controller = tk.Tk()
        controller.withdraw()
        process = None
        try:
            previous = set(controller.tk.splitlist(controller.tk.call('winfo', 'interps')))
            with tempfile.TemporaryDirectory(prefix='portal gui test ') as tmp:
                root = Path(tmp)
                binary = str(Path(os.environ['PSPORTAL_BINARY']).resolve())
                provider = root / 'provider.json'
                provider.write_text('{"proxies": []}', encoding='utf-8')
                ports = set()
                while len(ports) < 3:
                    ports.add(port())
                listen, backend, api = sorted(ports)
                cfg = dict(listen_host='127.0.0.1', listen_port=listen,
                    allowed_clients=['127.0.0.1'], backend_port=backend, api_port=api,
                    core_path=binary, subscription_file=str(provider), data_dir=str(root / 'runtime'))
                path = root / 'config.json'
                path.write_text(json.dumps(cfg), encoding='utf-8')
                with (root / 'gui-output.txt').open('w+', encoding='utf-8') as output:
                    process = subprocess.Popen([binary, '--config', str(path)], stdout=output, stderr=subprocess.STDOUT)

                    def wait_for(predicate, timeout=20):
                        deadline = time.monotonic() + timeout
                        while time.monotonic() < deadline:
                            controller.update()
                            result = predicate()
                            if result:
                                return result
                            if process.poll() is not None:
                                output.seek(0)
                                self.fail('Frozen GUI exited early: ' + output.read())
                            time.sleep(.05)
                        self.fail('Timed out waiting for frozen GUI state')

                    target = wait_for(lambda: next(iter(set(controller.tk.splitlist(
                        controller.tk.call('winfo', 'interps'))) - previous), None))

                    def remote(*args):
                        return controller.tk.call('send', target, *args)

                    wait_for(lambda: int(remote('winfo', 'viewable', '.')))
                    self.assertEqual(remote('wm', 'title', '.'), 'PS Portal On-Demand')
                    widgets = []
                    def walk(parent):
                        for widget in controller.tk.splitlist(remote('winfo', 'children', parent)):
                            widgets.append(widget)
                            walk(widget)
                    walk('.')
                    buttons = {str(remote(widget, 'cget', '-text')): widget for widget in widgets
                        if remote('winfo', 'class', widget) == 'TButton'}
                    log = next(widget for widget in widgets if remote('winfo', 'class', widget) == 'Text')
                    self.assertIn('Start listener', buttons)
                    self.assertIn('Stop', buttons)
                    self.assertFalse((root / 'runtime').exists(), 'Opening GUI must not start the listener')

                    def listening(number):
                        try:
                            with socket.create_connection(('127.0.0.1', number), timeout=.2):
                                return True
                        except OSError:
                            return False

                    for cycle in range(2):
                        remote(buttons['Start listener'], 'invoke')
                        wait_for(lambda: str(remote(log, 'get', '1.0', 'end')).count('Proxy ready at ') >= cycle + 1)
                        self.assertTrue(listening(listen))
                        self.assertFalse(listening(backend), 'No client traffic must leave the core stopped')
                        self.assertFalse(listening(api))
                        self.assertEqual(str(remote(buttons['Start listener'], 'cget', '-state')), 'disabled')
                        self.assertEqual(str(remote(buttons['Save / validate'], 'cget', '-state')), 'disabled')
                        remote(buttons['Stop'], 'invoke')
                        wait_for(lambda: str(remote(buttons['Start listener'], 'cget', '-state')) == 'normal')
                        self.assertFalse(listening(listen))
                        self.assertFalse((root / 'runtime' / 'owner.lock').exists())
                        self.assertFalse(list((root / 'runtime').glob('session-*')))

                    close_command = remote('wm', 'protocol', '.', 'WM_DELETE_WINDOW')
                    remote('eval', close_command)
                    self.assertEqual(process.wait(timeout=10), 0)
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            controller.destroy()
