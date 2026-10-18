"""Opt-in Windows/macOS frozen-window initialization and normal-close smoke.

Enable PSPORTAL_FROZEN_WINDOW_TEST=1 and PSPORTAL_BINARY on that native runner.
Only windows owned by our launched child are inspected. Windows uses PID-bound
Win32 metadata/WM_CLOSE; macOS uses PID/executable-bound Core Graphics metadata
and NSRunningApplication normal quit. Neither path reads other window titles,
captures pixels, requests permissions, uses accessibility, or changes app code.

This proves packaged window launch/close while stopped, separately from the
source Tk Start/Stop lifecycle in test_native_tk.py. No listener is started.
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

from test_core import port


def windows_for_pid(pid):
    """Return only visible, nonempty top-level windows owned by this PID."""
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows.restype = wintypes.BOOL
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsWindowVisible.restype = wintypes.BOOL
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowRect.restype = wintypes.BOOL
    result = []
    @callback_type
    def visit(window, _):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value != pid or not user.IsWindowVisible(window):
            return True
        bounds = wintypes.RECT()
        if user.GetWindowRect(window, ctypes.byref(bounds)):
            width, height = bounds.right - bounds.left, bounds.bottom - bounds.top
            if width > 0 and height > 0:
                result.append(dict(window_id=int(window), width=width, height=height))
        return True
    if not user.EnumWindows(visit, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return result


def close_windows_window(window, pid):
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    owner = wintypes.DWORD()
    user.GetWindowThreadProcessId(window, ctypes.byref(owner))
    if owner.value != pid:
        raise RuntimeError('The window no longer belongs to the test-owned process')
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.PostMessageW.restype = wintypes.BOOL
    if not user.PostMessageW(window, 0x0010, 0, 0):  # WM_CLOSE, not forced termination.
        raise ctypes.WinError(ctypes.get_last_error())


@unittest.skipUnless(sys.platform in ('win32', 'darwin') and
    os.environ.get('PSPORTAL_FROZEN_WINDOW_TEST') == '1' and os.environ.get('PSPORTAL_BINARY'),
    'Set PSPORTAL_FROZEN_WINDOW_TEST=1 and PSPORTAL_BINARY on native Windows/macOS')
class FrozenNativeWindowTests(unittest.TestCase):
    def test_frozen_window_initializes_and_closes_normally_while_stopped(self):
        binary = Path(os.environ['PSPORTAL_BINARY']).resolve()
        self.assertTrue(binary.is_file())
        with tempfile.TemporaryDirectory(prefix='portal frozen window ') as tmp:
            directory = Path(tmp)
            provider = directory / 'empty provider.json'
            provider.write_text('{"proxies": []}', encoding='utf-8')
            ports = set()
            while len(ports) < 3:
                ports.add(port())
            listen, backend, api = sorted(ports)
            cfg = dict(listen_host='127.0.0.1', listen_port=listen,
                allowed_clients=['127.0.0.1'], backend_port=backend, api_port=api,
                core_path=str(binary), subscription_file=str(provider),
                data_dir=str(directory / 'runtime'))
            path = directory / 'config.json'
            path.write_text(json.dumps(cfg), encoding='utf-8')
            helper = None
            if sys.platform == 'darwin':
                helper = directory / 'frozen-window-helper'
                compiled = subprocess.run(['xcrun', 'swiftc',
                    str(Path(__file__).with_name('helpers') / 'frozen_window_mac.swift'),
                    '-o', str(helper)], capture_output=True, text=True, timeout=120)
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)

            def assert_no_listener():
                self.assertFalse((directory / 'runtime').exists(), 'Opening a window must not start a listener')
                for number in ports:
                    try:
                        with socket.create_connection(('127.0.0.1', number), timeout=.2):
                            self.fail('Stopped frozen window unexpectedly opened port ' + str(number))
                    except OSError:
                        pass

            def mac_command(action, pid):
                result = subprocess.run([str(helper), action, str(pid), str(binary)],
                    capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            process = None
            with (directory / 'frozen-window-output.txt').open('w+', encoding='utf-8') as output:
                try:
                    assert_no_listener()
                    process = subprocess.Popen([str(binary), '--config', str(path)],
                        stdout=output, stderr=subprocess.STDOUT)
                    deadline = time.monotonic() + 30
                    visible = []
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            output.seek(0)
                            self.fail('Frozen application exited before a visible window: ' + output.read())
                        visible = (windows_for_pid(process.pid) if sys.platform == 'win32' else
                                   json.loads(mac_command('inspect', process.pid))['windows'])
                        if visible:
                            break
                        time.sleep(.1)
                    if not visible:
                        output.seek(0)
                        self.fail('No test-owned frozen window was visible; no permissions were requested: ' + output.read())
                    assert_no_listener()
                    self.assertIsNone(process.poll())
                    if sys.platform == 'win32':
                        main = max(visible, key=lambda item: item['width'] * item['height'])
                        close_windows_window(main['window_id'], process.pid)
                    else:
                        mac_command('quit', process.pid)
                    code = process.wait(timeout=20)
                    output.seek(0)
                    self.assertEqual(code, 0, 'Normal close failed: ' + output.read())
                    assert_no_listener()
                finally:
                    # Failure cleanup is not normal-close evidence. Always reap
                    # only the exact subprocess this test launched.
                    if process is not None and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=10)
