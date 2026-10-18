"""Engine dispatch tests; real native checks are explicitly opt-in."""
import io
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import Mock

from portalproxy import backend, config, desktop


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def values(native):
    ports = set()
    while len(ports) < 3:
        ports.add(free_port())
    listen, core, api = sorted(ports)
    return dict(config.DEFAULTS, engine_mode='embedded', native_path=str(native),
                listen_host='127.0.0.1', listen_port=listen,
                allowed_clients=['127.0.0.1'], backend_port=core, api_port=api,
                subscription_url='https://example.com/provider?token=opaque-test-token')


class EmbeddedDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='portal dispatch ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.native = self.root / ('native engine.exe' if sys.platform == 'win32' else 'native engine')
        self.native.write_text('fixture; not executed', encoding='utf-8')
        self.native.chmod(0o700)
        self.path = self.root / 'config.json'
        self.cfg = values(self.native)

    def test_external_is_default_and_still_requires_mihomo(self):
        original = dict(self.cfg, engine_mode='external', core_path=str(self.native))
        original.pop('engine_mode')
        checked = config.validate(original, self.path)
        self.assertEqual(checked['engine_mode'], 'external')
        original.pop('core_path')
        with self.assertRaisesRegex(ValueError, 'core_path'):
            config.validate(original, self.path)

    def test_embedded_does_not_require_external_core(self):
        checked = config.validate(self.cfg, self.path)
        self.assertEqual(checked['native_path'], str(self.native))
        self.assertNotIn('core_path', checked)
        self.cfg['core_path'] = '/missing unused fallback'
        self.assertEqual(config.validate(self.cfg, self.path)['engine_mode'], 'embedded')

    def test_invalid_engine_and_executable_rejected(self):
        for changes in ({'engine_mode': 'unknown'}, {'native_path': '/missing engine'}, {'native_path': str(self.root)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                config.validate(dict(self.cfg, **changes), self.path)

    def test_windows_native_rejects_batch_scripts(self):
        script = self.root / 'unsafe.cmd'
        script.write_text('fixture; never executed'); script.chmod(0o700)
        with patch.object(sys, 'platform', 'win32'), self.assertRaisesRegex(ValueError, 'native Windows .exe'):
            config.validate(dict(self.cfg, native_path=str(script)), self.path)

    @unittest.skipIf(os.name == 'nt', 'POSIX executable modes')
    def test_native_requires_executable_permission(self):
        self.native.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'executable'):
            config.validate(self.cfg, self.path)

    def test_native_strict_limits_do_not_change_external_validation(self):
        for changes in ({'max_connections': 4097}, {'idle_seconds': 1.5},
                        {'allowed_clients': ['192.168.1.3'] * 2, 'listen_host': '192.168.1.2'},
                        {'health_url': 'https://example.com:8443/check'},
                        {'health_url': 'https://127.0.0.1/check'},
                        {'preferred_node': ' passrule'}, {'preferred_node': 'ab\u200bcd'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                config.validate(dict(self.cfg, **changes), self.path)
            external = dict(self.cfg, **changes)
            external.update(engine_mode='external', core_path=str(self.native))
            config.validate(external, self.path)

    def test_blank_local_provider_means_url(self):
        checked = config.validate(dict(self.cfg, subscription_file=''), self.path)
        self.assertNotIn('subscription_file', checked)
        self.assertEqual(backend.native_values(checked)['subscription_url'], self.cfg['subscription_url'])

    def test_native_config_allowlist_and_unused_token_omission(self):
        provider = self.root / 'provider.json'
        provider.write_text('{"proxies": []}', encoding='utf-8')
        cfg = dict(self.cfg, subscription_file=str(provider), core_path='/fallback',
                   data_dir='/runtime', unknown_sensitive='not-for-native')
        original = dict(cfg)
        launch = backend.prepare_launch(self.path, cfg)
        try:
            private_path = Path(launch.command[2])
            self.assertEqual(launch.command, [str(self.native), '--config', str(private_path), '--desktop-child'])
            payload = json.loads(private_path.read_text())
            self.assertEqual(payload['subscription_file'], str(provider))
            self.assertTrue(set(payload) <= backend.NATIVE_FIELDS)
            for key in ('subscription_url', 'core_path', 'data_dir', 'unknown_sensitive', 'native_path', 'engine_mode'):
                self.assertNotIn(key, payload)
            self.assertNotIn('opaque-test-token', private_path.read_text())
            self.assertNotIn('opaque-test-token', ' '.join(launch.command))
            self.assertEqual(cfg, original)
            if os.name != 'nt':
                self.assertEqual(private_path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(private_path.parent.stat().st_mode & 0o777, 0o700)
        finally:
            launch.cleanup()
        self.assertFalse(private_path.parent.exists())
        launch.cleanup()

    def test_source_and_frozen_native_commands_are_identical(self):
        for frozen in (False, True):
            with self.subTest(frozen=frozen), patch.object(sys, 'frozen', frozen, create=True):
                launch = backend.prepare_launch(self.path, self.cfg, check=True)
                try:
                    self.assertEqual(launch.command[0], str(self.native))
                    self.assertEqual(launch.command[-1], '--check')
                    self.assertNotIn('--backend', launch.command)
                finally:
                    launch.cleanup()

    def test_only_fixed_bundle_location_is_discovered(self):
        folder = self.root / 'bundle' / 'native'
        folder.mkdir(parents=True)
        filename = 'psportal-native.exe' if sys.platform == 'win32' else 'psportal-native'
        binary = folder / filename
        binary.write_text('bundled fixture'); binary.chmod(0o700)
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(folder.parent / 'PSPortalProxy')):
            self.assertEqual(config.bundled_native_path(), binary.resolve())
            checked = config.validate(dict(self.cfg, native_path=''), self.path)
            self.assertEqual(checked['native_path'], str(binary.resolve()))
        with patch.object(sys, 'frozen', False, create=True):
            self.assertIsNone(config.bundled_native_path())

    def test_json_readiness_matches_exact_engine_listener(self):
        event = dict(event='ready', engine='mihomo-adapters', listen_host='127.0.0.1', listen_port=self.cfg['listen_port'])
        self.assertTrue(backend.is_ready(json.dumps(event), self.cfg))
        for update in ({'event': 'status'}, {'engine': 'other'}, {'listen_host': '192.168.1.1'}, {'listen_port': 1}, {'listen_port': str(event['listen_port'])}):
            self.assertFalse(backend.is_ready(json.dumps(dict(event, **update)), self.cfg))
        for line in ('ready', '[]', 'null', 'Proxy ready at 127.0.0.1:10081; core starts on demand'):
            self.assertFalse(backend.is_ready(line, self.cfg))

    def test_external_readiness_uses_original_message(self):
        cfg = dict(self.cfg, engine_mode='external')
        self.assertTrue(backend.is_ready(f"Proxy ready at 127.0.0.1:{cfg['listen_port']}; core starts on demand", cfg))
        self.assertFalse(backend.is_ready('Proxy ready at 127.0.0.1:1; core starts on demand', cfg))

    def test_failed_spawn_removes_private_config(self):
        process = desktop.BackendProcess()
        seen = []
        def fail(launch, **_):
            seen.append(Path(launch.command[2]))
            self.assertTrue(seen[0].is_file())
            raise OSError('controlled spawn failure')
        with patch('portalproxy.backend.spawn', side_effect=fail):
            with self.assertRaises(OSError):
                process.start(self.path, self.cfg)
        self.assertFalse(seen[0].parent.exists())

    def test_native_spawn_sanitizes_only_child_environment(self):
        launch = backend.Launch([str(self.native)], embedded=True)
        with patch('portalproxy.backend.external_environment', return_value={'SAFE': 'value'}), patch('portalproxy.backend.subprocess.Popen') as popen:
            backend.spawn(launch, stdin=subprocess.PIPE)
            popen.assert_called_once_with([str(self.native)], stdin=subprocess.PIPE, env={'SAFE': 'value'})

    def test_old_child_uses_original_secret_snapshot(self):
        class Process:
            stdout = io.StringIO('old-token\n')
        process = desktop.BackendProcess()
        process.secrets = ('new-token',)
        process._read_output(Process(), secrets=('old-token',))
        self.assertEqual(process.events.get_nowait(), '[redacted]')

    def test_old_readiness_during_restart_cannot_mark_replacement_ready(self):
        cfg = dict(self.cfg, engine_mode='external')
        class Old:
            stdout = io.StringIO(f"Proxy ready at 127.0.0.1:{cfg['listen_port']}; core starts on demand\n")
            def poll(self): return 0
        process = desktop.BackendProcess()
        old = Old()
        process.process = old
        actual_spawn = backend.spawn
        command = [sys.executable, '-u', '-c', 'import sys; sys.stdin.read()']
        def during_spawn(launch, **kwargs):
            process._read_output(old, values=cfg, secrets=())
            return actual_spawn(launch, **kwargs)
        try:
            with patch('portalproxy.desktop.backend_command', return_value=command), patch('portalproxy.backend.spawn', side_effect=during_spawn):
                process.start(self.path, cfg)
            self.assertFalse(process.ready)
        finally:
            process.stop()
            if process.process is not None:
                process.process.wait(timeout=5)
                process.poll()

    def test_exited_child_cannot_mark_stopped_controller_ready(self):
        cfg = dict(self.cfg, engine_mode='external')
        class Old:
            stdout = io.StringIO(f"Proxy ready at 127.0.0.1:{cfg['listen_port']}; core starts on demand\n")
            def poll(self): return 0
        process = desktop.BackendProcess()
        old = Old()
        process.process = old
        self.assertEqual(process.poll(), 0)
        process._read_output(old, values=cfg, secrets=())
        self.assertIsNone(process.process)
        self.assertFalse(process.ready)


class EngineFormTests(unittest.TestCase):
    """Display-free control logic tests; not visual/native desktop acceptance."""
    def app(self):
        app = object.__new__(desktop.DesktopApp)
        app.root = Mock()
        app.backend = Mock(process=None)
        app.vars = {'engine_mode': Mock(), 'core_path': Mock(), 'native_path': Mock()}
        app.vars['engine_mode'].get.return_value = 'external'
        app.engine_inputs = {name: [Mock()] for name in ('core_path', 'native_path', 'backend_port', 'api_port')}
        app.mode_note_var = Mock()
        app.closing = False
        app.dirty = False
        return app

    def test_mode_switch_enables_only_matching_executable(self):
        app = self.app()
        app.engine_controls()
        app.engine_inputs['core_path'][0].configure.assert_called_with(state='normal')
        app.engine_inputs['native_path'][0].configure.assert_called_with(state='disabled')
        app.vars['engine_mode'].get.return_value = 'embedded'
        app.engine_controls()
        app.engine_inputs['core_path'][0].configure.assert_called_with(state='disabled')
        app.engine_inputs['native_path'][0].configure.assert_called_with(state='normal')
        self.assertIn('Experimental', app.mode_note_var.set.call_args.args[0])
        app.vars['core_path'].set.assert_not_called()
        app.vars['native_path'].set.assert_not_called()

    def test_running_engine_disables_all_executable_inputs(self):
        app = self.app()
        app.backend.process = Mock()
        app.backend.process.poll.return_value = None
        app.engine_controls()
        for widgets in app.engine_inputs.values():
            widgets[0].configure.assert_called_with(state='disabled')

    def test_duplicate_start_does_not_save_or_launch_again(self):
        app = self.app()
        app.backend.process = Mock()
        app.backend.process.poll.return_value = None
        app.save = Mock()
        app.start()
        app.save.assert_not_called()
        app.backend.start.assert_not_called()

    def test_cancel_close_preserves_running_app_then_confirm_stops(self):
        app = self.app()
        app.backend.process = Mock()
        app.backend.process.poll.return_value = None
        app.stop = Mock()
        dialog = Mock(askyesno=Mock(return_value=False))
        with patch.dict(sys.modules, {'tkinter': SimpleNamespace(messagebox=dialog)}):
            app.close()
        self.assertFalse(app.closing)
        app.stop.assert_not_called()
        app.root.destroy.assert_not_called()
        dialog.askyesno.return_value = True
        with patch.dict(sys.modules, {'tkinter': SimpleNamespace(messagebox=dialog)}):
            app.close()
            app.close()
        self.assertTrue(app.closing)
        app.stop.assert_called_once()
        app.root.destroy.assert_not_called()


@unittest.skipUnless(os.environ.get('PSPORTAL_NATIVE_BINARY'), 'Set PSPORTAL_NATIVE_BINARY to built shared engine')
class RealNativeDesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='portal native desktop ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = values(Path(os.environ['PSPORTAL_NATIVE_BINARY']).resolve())
        provider = self.root / 'empty provider.json'
        provider.write_text('{"proxies": []}', encoding='utf-8')
        self.cfg.update(subscription_file=str(provider), unknown_sensitive='never-forward')
        self.path = self.root / 'config.json'
        desktop.save_config(self.path, self.cfg)

    def wait_ready(self, process):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.ready:
                return
            if process.process.poll() is not None:
                self.fail('Native exited before readiness')
            time.sleep(.02)
        self.fail('Native readiness timed out')

    def test_real_native_check_and_python_cli_dispatch(self):
        command = [sys.executable, '-m', 'portalproxy', '--config', str(self.path), '--check']
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Configuration valid', result.stdout)
        self.assertNotIn('opaque-test-token', result.stdout + result.stderr)

    def test_real_native_desktop_ready_reject_stop_restart_cleanup(self):
        process = desktop.BackendProcess()
        first_pid = None
        try:
            for _ in range(2):
                process.start(self.path, self.cfg)
                self.wait_ready(process)
                if first_pid is not None:
                    self.assertNotEqual(process.process.pid, first_pid)
                first_pid = process.process.pid
                private_path = Path(process.launch.command[2])
                self.assertTrue(private_path.is_file())
                with self.assertRaises(RuntimeError):
                    process.start(self.path, self.cfg)
                for target in ('127.0.0.1', '169.254.169.254'):
                    with socket.create_connection(('127.0.0.1', self.cfg['listen_port']), timeout=3) as sock:
                        sock.sendall(f'CONNECT {target}:443 HTTP/1.1\r\nHost: {target}:443\r\n\r\n'.encode())
                        self.assertIn(b'403', sock.recv(4096))
                # Empty local provider fails closed without any subscription or
                # upstream network access, while proving local-file dispatch.
                with socket.create_connection(('127.0.0.1', self.cfg['listen_port']), timeout=3) as sock:
                    sock.sendall(b'CONNECT 1.1.1.1:443 HTTP/1.1\r\nHost: 1.1.1.1:443\r\n\r\n')
                    self.assertIn(b'502', sock.recv(4096))
                for key in ('backend_port', 'api_port'):
                    with self.assertRaises(OSError):
                        socket.create_connection(('127.0.0.1', self.cfg[key]), timeout=.1)
                process.stop(); process.stop()
                self.assertEqual(process.process.wait(timeout=10), 0)
                self.assertEqual(process.poll(), 0)
                self.assertFalse(private_path.parent.exists())
                with self.assertRaises(OSError):
                    socket.create_connection(('127.0.0.1', self.cfg['listen_port']), timeout=.1)
        finally:
            process.stop()
            if process.process is not None and process.process.poll() is None:
                process.process.kill(); process.process.wait()
            process.poll()

    def test_python_cli_parent_eof_stops_native(self):
        command = [sys.executable, '-u', '-m', 'portalproxy', '--config', str(self.path), '--desktop-child']
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            # communicate closes stdin immediately: startup followed by EOF must
            # also stop cleanly, even before the GUI sees readiness.
            output, _ = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, output)
            self.assertIn('"event":"ready"', output)
            self.assertNotIn('opaque-test-token', output)
            with self.assertRaises(OSError):
                socket.create_connection(('127.0.0.1', self.cfg['listen_port']), timeout=.1)
        finally:
            if process.poll() is None:
                process.kill(); process.wait()

    def test_native_bind_failure_is_observed_and_cleaned(self):
        process = desktop.BackendProcess()
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', self.cfg['listen_port']))
            occupied.listen()
            process.start(self.path, self.cfg)
            private_path = Path(process.launch.command[2])
            self.assertNotEqual(process.process.wait(timeout=10), 0)
            self.assertIsNotNone(process.poll())
            self.assertFalse(process.ready)
            self.assertFalse(private_path.parent.exists())
            self.assertGreaterEqual(occupied.fileno(), 0)
        lines = []
        while not process.events.empty():
            lines.append(process.events.get_nowait())
        self.assertNotIn('opaque-test-token', '\n'.join(lines))

    @unittest.skipIf(os.name == 'nt', 'POSIX SIGTERM; Windows needs native acceptance')
    def test_cli_sigterm_stops_native(self):
        command = [sys.executable, '-u', '-m', 'portalproxy', '--config', str(self.path)]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            event = process.stdout.readline()
            self.assertIn('"event":"ready"', event)
            process.send_signal(signal.SIGTERM)
            output, _ = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, event + output)
            with self.assertRaises(OSError):
                socket.create_connection(('127.0.0.1', self.cfg['listen_port']), timeout=.1)
        finally:
            if process.poll() is None:
                process.kill(); process.wait()

    @unittest.skipIf(os.name == 'nt', 'POSIX parent-disappearance test; Windows needs native acceptance')
    def test_desktop_parent_disappearance_closes_native_listener(self):
        code = '''import json, os, sys, time
from pathlib import Path
from portalproxy.desktop import BackendProcess, read_config
controller = BackendProcess()
path = Path(sys.argv[1])
controller.start(path, read_config(path))
deadline = time.monotonic() + 10
while not controller.ready and time.monotonic() < deadline:
    time.sleep(.02)
print(json.dumps({"pid": controller.process.pid, "temporary": str(Path(controller.launch.command[2]).parent), "ready": controller.ready}), flush=True)
sys.stdin.read()
os._exit(0)
'''
        process = subprocess.Popen([sys.executable, '-u', '-c', code, str(self.path)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        child = None
        stopped = False
        try:
            child = json.loads(process.stdout.readline())
            self.assertTrue(child['ready'])
            process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(('127.0.0.1', self.cfg['listen_port']), timeout=.1):
                        pass
                except OSError:
                    stopped = True
                    break
                time.sleep(.02)
            self.assertTrue(stopped, 'Native listener survived its parent closing stdin')
        finally:
            if process.poll() is None:
                process.kill(); process.wait()
            if child:
                if not stopped:
                    try:
                        os.kill(child['pid'], signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                # Hard parent termination cannot run Python cleanup; remove only
                # the exact directory created by this test after child shutdown.
                shutil.rmtree(child['temporary'], ignore_errors=True)

    @unittest.skipUnless(os.environ.get('PSPORTAL_DUAL_BINARY'), 'Set PSPORTAL_DUAL_BINARY to rebuilt desktop package')
    def test_frozen_cli_dispatch_native_and_eof(self):
        executable = os.environ['PSPORTAL_DUAL_BINARY']
        # The packaged GUI must find its own bundled native executable without
        # depending on the build machine's separate native distribution path.
        self.path.write_text(json.dumps(dict(self.cfg, native_path='')), encoding='utf-8')
        command = [executable, '--backend', '--config', str(self.path)]
        checked = subprocess.run(command + ['--check'], capture_output=True, text=True, timeout=20)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        process = subprocess.Popen(command + ['--desktop-child'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            output, _ = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, output)
            self.assertIn('"event":"ready"', output)
            self.assertNotIn('opaque-test-token', output)
        finally:
            if process.poll() is None:
                process.kill(); process.wait()
