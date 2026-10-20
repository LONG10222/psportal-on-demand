"""Opt-in actual frozen Tk window tests on an isolated X11 display.

The controller uses Tk's X11 send command to inspect and invoke real widgets in
the packaged application. No application mocks, external core, provider fetch,
or Internet traffic. Socket probes send no HTTP request and cannot wake a core.

Enable the original external case with PSPORTAL_GUI_TEST=1 and PSPORTAL_BINARY.
Also set PSPORTAL_DUAL_BINARY to a bundle containing native/psportal-native to
exercise experimental embedded mode on the same isolated X11 display.
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


def ready_records(contents, mode, host, number):
    """Count this listener's records; a stale or unrelated event is not ready."""
    if mode == 'external':
        return sum(line.startswith(f'Proxy ready at {host}:{number};')
                   for line in contents.splitlines())
    count = 0
    for line in contents.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if (isinstance(event, dict) and event.get('event') == 'ready'
                and event.get('engine') == 'mihomo-adapters'
                and event.get('listen_host') == host
                and type(event.get('listen_port')) is int
                and event['listen_port'] == number):
            count += 1
    return count


class GuiReadinessRecordTests(unittest.TestCase):
    """Display-free checks for the acceptance harness's independent oracle."""

    def test_embedded_matches_exact_listener_with_either_json_spacing(self):
        event = dict(event='ready', engine='mihomo-adapters',
                     listen_host='127.0.0.1', listen_port=10081)
        contents = json.dumps(event) + '\n' + json.dumps(event, separators=(',', ':'))
        self.assertEqual(ready_records(contents, 'embedded', '127.0.0.1', 10081), 2)

    def test_embedded_rejects_unrelated_or_malformed_records(self):
        event = dict(event='ready', engine='mihomo-adapters',
                     listen_host='127.0.0.1', listen_port=10081)
        invalid = ['ready', '[]', 'null', '{invalid',
                   'Proxy ready at 127.0.0.1:10081; core starts on demand']
        for change in ({'event': 'status'}, {'engine': 'other'},
                       {'listen_host': '192.168.1.1'}, {'listen_port': 1},
                       {'listen_port': '10081'}):
            invalid.append(json.dumps(dict(event, **change)))
        self.assertEqual(ready_records('\n'.join(invalid), 'embedded', '127.0.0.1', 10081), 0)

    def test_external_matches_complete_listener_prefix(self):
        contents = '\n'.join(('Proxy ready at 127.0.0.1:10081; core starts on demand',
                              'Proxy ready at 127.0.0.1:100810; wrong port',
                              'Proxy ready at 192.168.1.1:10081; wrong host'))
        self.assertEqual(ready_records(contents, 'external', '127.0.0.1', 10081), 1)


@unittest.skipUnless(os.environ.get('PSPORTAL_GUI_TEST') == '1' and os.environ.get('PSPORTAL_BINARY'),
    'Set PSPORTAL_GUI_TEST=1 and PSPORTAL_BINARY under an isolated X11 display')
class FrozenGuiTests(unittest.TestCase):
    def test_actual_window_start_stop_restart_and_close(self):
        self.exercise_window('external')

    @unittest.skipUnless(os.environ.get('PSPORTAL_DUAL_BINARY'), 'Set PSPORTAL_DUAL_BINARY for bundled-native GUI checks')
    def test_embedded_window_start_stop_restart_and_close(self):
        self.exercise_window('embedded')

    def exercise_window(self, mode):
        import tkinter as tk
        controller = tk.Tk()
        controller.withdraw()
        process = None
        try:
            previous = set(controller.tk.splitlist(controller.tk.call('winfo', 'interps')))
            with tempfile.TemporaryDirectory(prefix='portal gui test ') as tmp:
                root = Path(tmp)
                binary = str(Path(os.environ['PSPORTAL_DUAL_BINARY' if mode == 'embedded' else 'PSPORTAL_BINARY']).resolve())
                if mode == 'embedded':
                    self.assertTrue((Path(binary).parent / 'native' / 'psportal-native').is_file(),
                        'PSPORTAL_DUAL_BINARY must have a bundled native/psportal-native')
                provider = root / 'provider.json'
                provider.write_text('{"proxies": []}', encoding='utf-8')
                ports = set()
                while len(ports) < 3:
                    ports.add(port())
                listen, backend, api = sorted(ports)
                cfg = dict(listen_host='127.0.0.1', listen_port=listen,
                    allowed_clients=['127.0.0.1'], backend_port=backend, api_port=api,
                    core_path=binary, subscription_file=str(provider), data_dir=str(root / 'runtime'))
                if mode == 'embedded':
                    # Exercise fixed-location discovery inside the distributed
                    # application, rather than a separately configured core.
                    cfg.update(engine_mode='embedded', native_path='')
                path = root / 'config.json'
                path.write_text(json.dumps(cfg), encoding='utf-8')
                child_tmp = root / 'child temporary files'
                child_tmp.mkdir()
                child_env = dict(os.environ, TMPDIR=str(child_tmp), TEMP=str(child_tmp), TMP=str(child_tmp))
                with (root / 'gui-output.txt').open('w+', encoding='utf-8') as output:
                    process = subprocess.Popen([binary, '--config', str(path)],
                        stdout=output, stderr=subprocess.STDOUT, env=child_env)

                    def wait_for(predicate, timeout=20, state='frozen GUI state'):
                        deadline = time.monotonic() + timeout
                        while time.monotonic() < deadline:
                            controller.update()
                            if process.poll() is not None:
                                output.seek(0)
                                self.fail('Frozen GUI exited early: ' + output.read())
                            result = predicate()
                            if result:
                                return result
                            time.sleep(.05)
                        output.seek(0)
                        self.fail(f'Timed out waiting for {state}: ' + output.read())

                    target = wait_for(lambda: next(iter(set(controller.tk.splitlist(
                        controller.tk.call('winfo', 'interps'))) - previous), None))

                    def remote(*args):
                        return controller.tk.call('send', target, *args)

                    wait_for(lambda: int(remote('winfo', 'viewable', '.')))
                    self.assertEqual(remote('wm', 'title', '.'), '星渡 StarPass')
                    widgets = []
                    def walk(parent):
                        for widget in controller.tk.splitlist(remote('winfo', 'children', parent)):
                            widgets.append(widget)
                            walk(widget)
                    walk('.')
                    buttons = {str(remote(widget, 'cget', '-text')): widget for widget in widgets
                        if remote('winfo', 'class', widget) == 'TButton'}
                    log = next(widget for widget in widgets if remote('winfo', 'class', widget) == 'Text')
                    status = next(widget for widget in widgets
                        if remote('winfo', 'class', widget) == 'TLabel'
                        and str(remote(widget, 'cget', '-text')) == 'Stopped')
                    self.assertIn('Start sharing', buttons)
                    self.assertIn('Stop', buttons)
                    self.assertFalse((root / 'runtime').exists(), 'Opening GUI must not start the listener')
                    self.assertFalse(list(child_tmp.glob('psportal-native-*')))

                    def listening(number):
                        try:
                            with socket.create_connection(('127.0.0.1', number), timeout=.2):
                                return True
                        except OSError:
                            return False

                    def assert_stopped():
                        self.assertFalse(listening(listen))
                        self.assertFalse(listening(backend))
                        self.assertFalse(listening(api))
                        self.assertFalse((root / 'runtime' / 'owner.lock').exists())
                        self.assertFalse(list((root / 'runtime').glob('session-*')))
                        self.assertFalse(list(child_tmp.glob('psportal-native-*')),
                            'Stopping must remove the native private configuration')

                    def start(cycle):
                        remote(buttons['Start sharing'], 'invoke')
                        wait_for(lambda: ready_records(str(remote(log, 'get', '1.0', 'end')),
                            mode, '127.0.0.1', listen) >= cycle + 1, state=f'{mode} readiness record')
                        if mode == 'embedded':
                            wait_for(lambda: str(remote(status, 'cget', '-text')) == 'Listening',
                                state='visible Listening status')
                            private = list(child_tmp.glob('psportal-native-*/config.json'))
                            self.assertEqual(len(private), 1, 'Exactly one native child configuration is owned')
                            self.assertEqual(json.loads(private[0].read_text())['subscription_file'], str(provider))
                        self.assertTrue(listening(listen))
                        self.assertFalse(listening(backend), 'No client traffic must leave the core stopped')
                        self.assertFalse(listening(api))
                        self.assertFalse(list((root / 'runtime').glob('session-*/config.json')),
                            'Socket probes must not create an external core configuration')
                        self.assertFalse(list((root / 'runtime').glob('session-*/providers/subscription.yaml')),
                            'Socket probes must not load an external provider')
                        self.assertNotIn('Core: starting', str(remote(log, 'get', '1.0', 'end')))
                        self.assertEqual(str(remote(buttons['Start sharing'], 'cget', '-state')), 'disabled')
                        self.assertEqual(str(remote(buttons['Save / validate'], 'cget', '-state')), 'disabled')
                        self.assertEqual(str(remote(buttons['Stop'], 'cget', '-state')), 'normal')

                    assert_stopped()
                    for cycle in range(2):
                        start(cycle)
                        remote(buttons['Stop'], 'invoke')
                        wait_for(lambda: str(remote(buttons['Start sharing'], 'cget', '-state')) == 'normal',
                            state='re-enabled Start sharing button')
                        self.assertEqual(str(remote(status, 'cget', '-text')), 'Stopped')
                        self.assertEqual(str(remote(buttons['Stop'], 'cget', '-state')), 'disabled')
                        self.assertEqual(str(remote(buttons['Save / validate'], 'cget', '-state')), 'normal')
                        assert_stopped()

                    close_command = remote('wm', 'protocol', '.', 'WM_DELETE_WINDOW')
                    if mode == 'embedded':
                        # Exercise the real modal dialog without replacing its
                        # callback: cancel leaves the live listener untouched,
                        # then Yes must stop the owned child before GUI exit.
                        start(2)
                        dialog = '.__tk__messagebox'
                        for answer in ('no', 'yes'):
                            remote('after', '0', close_command)
                            wait_for(lambda: int(remote('winfo', 'exists', dialog)),
                                state='native Tk close confirmation')
                            self.assertEqual(remote('wm', 'title', dialog), 'Close StarPass?')
                            self.assertEqual(remote(dialog + '.msg', 'cget', '-text'),
                                'Stop the listener and its core, then close?')
                            remote(dialog + '.' + answer, 'invoke')
                            if answer == 'no':
                                wait_for(lambda: not int(remote('winfo', 'exists', dialog)),
                                    state='dismissed close confirmation')
                                self.assertIsNone(process.poll())
                                self.assertEqual(str(remote(status, 'cget', '-text')), 'Listening')
                                self.assertTrue(listening(listen))
                    else:
                        remote('eval', close_command)
                    self.assertEqual(process.wait(timeout=10), 0)
                    assert_stopped()
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            controller.destroy()
