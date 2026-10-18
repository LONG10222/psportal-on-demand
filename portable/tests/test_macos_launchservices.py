"""Opt-in final/extracted .app launch via LaunchServices, without OS grants.

Enable PSPORTAL_MACOS_APP_TEST=1 and PSPORTAL_MACOS_APP=exact extracted .app.
This proves a visible packaged window and normal quit while stopped; the source
Tk lifecycle tests separately exercise Start/Stop. Nothing bypasses Gatekeeper.
"""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from test_core import port


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('PSPORTAL_MACOS_APP_TEST') == '1'
    and os.environ.get('PSPORTAL_MACOS_APP'), 'Requires an extracted macOS app and explicit LaunchServices acceptance')
class MacOSLaunchServicesTests(unittest.TestCase):
    def test_extracted_app_launches_visible_and_quits_normally(self):
        app = Path(os.environ['PSPORTAL_MACOS_APP']).resolve(strict=True)
        binary = app / 'Contents/MacOS/PSPortalProxy'
        self.assertTrue(binary.is_file())
        with tempfile.TemporaryDirectory(prefix='portal launchservices ') as tmp:
            directory = Path(tmp)
            helper = directory / 'frozen-window-helper'
            compiled = subprocess.run(['xcrun', 'swiftc',
                str(Path(__file__).with_name('helpers') / 'frozen_window_mac.swift'),
                '-o', str(helper)], capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            provider = directory / 'empty provider.json'
            provider.write_text('{"proxies": []}', encoding='utf-8')
            ports = set()
            while len(ports) < 3:
                ports.add(port())
            listen, backend, api = sorted(ports)
            config = directory / 'config.json'
            config.write_text(json.dumps(dict(listen_host='127.0.0.1', listen_port=listen,
                allowed_clients=['127.0.0.1'], backend_port=backend, api_port=api,
                core_path=str(binary), subscription_file=str(provider),
                data_dir=str(directory / 'runtime'))), encoding='utf-8')

            def command(*args):
                result = subprocess.run([str(helper), *map(str, args)], capture_output=True,
                                        text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            def find_owned():
                pids = json.loads(command('find-app', app))['pids']
                self.assertLessEqual(len(pids), 1, 'More than one app owns the unique extraction path')
                return pids

            def assert_stopped():
                self.assertFalse((directory / 'runtime').exists(), 'Opening a window must not start the proxy')
                for number in ports:
                    try:
                        with socket.create_connection(('127.0.0.1', number), timeout=.2):
                            self.fail('LaunchServices window unexpectedly opened a proxy/backend/API port')
                    except OSError:
                        pass

            process = None
            pid = None
            self.assertEqual(find_owned(), [], 'The unique extracted app must not already be running')
            with (directory / 'open-output.txt').open('w+', encoding='utf-8') as output:
                try:
                    assert_stopped()
                    process = subprocess.Popen(['/usr/bin/open', '-W', '-n', str(app), '--args',
                        '--config', str(config)], stdout=output, stderr=subprocess.STDOUT)
                    deadline = time.monotonic() + 45
                    visible = False
                    while time.monotonic() < deadline:
                        pids = find_owned()
                        if pids:
                            pid = pids[0]
                            status = json.loads(command('inspect', pid, binary))
                            visible = status['executable_matched'] and bool(status['windows'])
                            if visible:
                                break
                        if process.poll() is not None:
                            output.seek(0)
                            self.fail('LaunchServices exited before the owned window appeared: ' + output.read())
                        time.sleep(.15)
                    self.assertTrue(visible, 'No owned visible window; no permissions or bypasses were requested')
                    assert_stopped()
                    command('quit', pid, binary)
                    self.assertEqual(process.wait(timeout=25), 0)
                    deadline = time.monotonic() + 10
                    while find_owned() and time.monotonic() < deadline:
                        time.sleep(.1)
                    self.assertEqual(find_owned(), [], 'Normal quit did not close the extracted app')
                    assert_stopped()
                finally:
                    # Failure cleanup is never acceptance evidence. Match both
                    # exact executable and PID before touching the app child.
                    for owned in find_owned():
                        if json.loads(command('inspect', owned, binary))['executable_matched']:
                            try:
                                os.kill(owned, signal.SIGTERM)
                            except ProcessLookupError:
                                continue
                            deadline = time.monotonic() + 5
                            while owned in find_owned() and time.monotonic() < deadline:
                                time.sleep(.1)
                            if owned in find_owned() and json.loads(command('inspect', owned, binary))['executable_matched']:
                                try:
                                    os.kill(owned, signal.SIGKILL)
                                except ProcessLookupError:
                                    pass
                    if process is not None and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
            print('PSPORTAL_LAUNCHSERVICES_RESULT=' + json.dumps(dict(app=str(app), visible=True,
                normal_quit=True, no_listener=True, open_exitcode=0), sort_keys=True))
