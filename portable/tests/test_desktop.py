import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from portalproxy import desktop


class DesktopHelpersTests(unittest.TestCase):
    def config(self, tmp):
        core = Path(tmp) / 'mihomo mock file'
        core.write_text('placeholder; never executed', encoding='utf-8')
        return dict(listen_host='192.168.50.2', allowed_clients=['192.168.50.30'],
            core_path=str(core), subscription_url='https://example.com/private?token=opaque-token',
            listen_port=10081, backend_port=10082, api_port=10090, idle_seconds=60,
            selection_mode='auto', preferred_node='', extra_preserved=True)

    def test_private_atomic_save_and_unknown_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = self.config(tmp)
            path = Path(tmp) / 'config.json'
            desktop.save_config(path, values)
            self.assertEqual(desktop.read_config(path), values)
            if os.name != 'nt':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(Path(tmp).glob('.portal-config-*')), [])

    def test_local_provider_can_replace_subscription_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = self.config(tmp)
            provider = Path(tmp) / 'provider.yaml'
            provider.write_text('proxies: []\n')
            values.update(subscription_url='', subscription_file=str(provider))
            path = Path(tmp) / 'config.json'
            desktop.save_config(path, values)
            self.assertEqual(desktop.read_config(path)['subscription_file'], str(provider))

    def test_invalid_config_does_not_replace_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = self.config(tmp)
            path = Path(tmp) / 'config.json'
            desktop.save_config(path, values)
            old = path.read_bytes()
            values['listen_host'] = '0.0.0.0'
            with self.assertRaises(ValueError):
                desktop.save_config(path, values)
            self.assertEqual(path.read_bytes(), old)
            self.assertEqual(list(Path(tmp).glob('.portal-config-*')), [])

    @unittest.skipIf(os.name == 'nt', 'Symlinks may require Windows developer mode')
    def test_refuses_to_overwrite_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            target = Path(tmp) / 'target.json'
            target.write_text('{}')
            path.symlink_to(target)
            with self.assertRaises(ValueError):
                desktop.save_config(path, self.config(tmp))
            self.assertEqual(target.read_text(), '{}')

    def test_read_rejects_large_and_non_object_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            for content in ('[]', ' ' * (desktop.MAX_CONFIG_BYTES + 1)):
                path.write_text(content)
                with self.assertRaises(ValueError):
                    desktop.read_config(path)

    def test_utf8_bom_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_bytes(b'\xef\xbb\xbf{"preferred_node":"Tokyo"}')
            self.assertEqual(desktop.read_config(path)['preferred_node'], 'Tokyo')

    def test_logs_redact_urls_tokens_and_controls(self):
        values = dict(subscription_url='https://example.com/private?token=opaque-token&other=encoded%20secret')
        secrets = desktop.secret_values(values)
        line = desktop.redact_log('\x1b[31mFailed https://example.com/private?token=opaque-token encoded secret\n', secrets)
        self.assertNotIn('opaque-token', line)
        self.assertNotIn('encoded secret', line)
        self.assertNotIn('example.com', line)
        self.assertNotIn('\x1b', line)
        self.assertEqual(desktop.redact_log('authorization: Bearer not-in-known-secrets'), '[Sensitive diagnostic omitted]')
        self.assertEqual(desktop.redact_log('Listener ready'), 'Listener ready')

    def test_source_and_frozen_commands_use_argument_arrays(self):
        path = Path('/path with spaces/config.json')
        with patch.object(sys, 'frozen', False, create=True):
            command = desktop.backend_command(path)
            self.assertEqual(command[:4], [sys.executable, '-u', '-m', 'portalproxy'])
            self.assertEqual(command[-3:], ['--config', str(path), '--desktop-child'])
        with patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(desktop.backend_command(path), [sys.executable, '--backend', '--config', str(path), '--desktop-child'])

    def test_default_config_paths(self):
        with patch.object(sys, 'platform', 'win32'), patch.dict(os.environ, {'LOCALAPPDATA': '/private/profile'}):
            self.assertEqual(desktop.default_config_path(), Path('/private/profile/PSPortalProxy/config.json'))
        with patch.object(sys, 'platform', 'linux'), patch.dict(os.environ, {'XDG_CONFIG_HOME': '/private/config'}):
            self.assertEqual(desktop.default_config_path(), Path('/private/config/PSPortalProxy/config.json'))
        with patch.object(sys, 'platform', 'darwin'):
            self.assertEqual(desktop.default_config_path(), Path.home() / 'Library/Application Support/PSPortalProxy/config.json')

    def test_collect_preserves_advanced_keys_and_parses_fields(self):
        class Var:
            def __init__(self, value): self.value = value
            def get(self): return self.value
        app = object.__new__(desktop.DesktopApp)
        app.raw = {'health_interval': 500, 'data_dir': '/private/runtime'}
        app.vars = {'listen_port': Var('10081'), 'allowed_clients': Var('192.168.1.2, 192.168.1.3'), 'preferred_node': Var('Tokyo')}
        result = app.collect()
        self.assertEqual(result['listen_port'], 10081)
        self.assertEqual(result['allowed_clients'], ['192.168.1.2', '192.168.1.3'])
        self.assertEqual(result['health_interval'], 500)
        self.assertEqual(result['data_dir'], '/private/runtime')


class BackendProcessTests(unittest.TestCase):
    def test_owned_child_stops_on_eof_and_can_restart(self):
        # Only our own stdlib fixture: no network, shell or core binary.
        command = [sys.executable, '-u', '-c', 'import sys; print("ready", flush=True); sys.stdin.read(); print("stopped", flush=True)']
        process = desktop.BackendProcess()
        try:
            with patch('portalproxy.desktop.backend_command', return_value=command):
                process.start(Path('unused.json'), {})
                first = process.process
                self.assertIsNotNone(first)
                with self.assertRaises(RuntimeError):
                    process.start(Path('unused.json'), {})
                process.stop()
                process.stop()
                self.assertEqual(first.wait(timeout=5), 0)
                self.assertEqual(process.poll(), 0)
                process.start(Path('unused.json'), {})
                self.assertNotEqual(process.process.pid, first.pid)
                process.stop()
                self.assertEqual(process.process.wait(timeout=5), 0)
        finally:
            process.stop()
            if process.process and process.process.poll() is None:
                process.process.kill()
                process.process.wait()

    def test_output_queue_is_bounded(self):
        process = desktop.BackendProcess()
        for _ in range(2000):
            process.log('test')
        self.assertEqual(process.events.qsize(), 500)

    def test_oversize_record_is_dropped_as_a_whole(self):
        class Process:
            stdout = io.StringIO('X' * 5000 + 'secret suffix\nready\n')
        process = desktop.BackendProcess()
        process._read_output(Process())
        lines = []
        while not process.events.empty():
            lines.append(process.events.get_nowait())
        self.assertEqual(lines, ['[Oversized diagnostic omitted]', 'ready'])


if __name__ == '__main__':
    unittest.main()
