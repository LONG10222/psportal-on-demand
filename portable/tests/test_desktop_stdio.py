"""Real child pipes must speak UTF-8 even under a legacy Windows code page."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_core import port


class DesktopStdioTests(unittest.TestCase):
    def test_invalid_utf8_stops_and_cleans_up_the_owned_listener(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = root / 'provider.json'
            provider.write_text('{"proxies": []}', encoding='utf-8')
            ports = set()
            while len(ports) < 3:
                ports.add(port())
            listen, backend, api = sorted(ports)
            cfg = dict(listen_host='127.0.0.1', listen_port=listen,
                allowed_clients=['127.0.0.1'], backend_port=backend, api_port=api,
                core_path=sys.executable, subscription_file=str(provider),
                data_dir=str(root / 'runtime'))
            path = root / 'config.json'
            path.write_text(json.dumps(cfg), encoding='utf-8')
            commands = [[sys.executable, '-m', 'portalproxy']]
            if os.environ.get('PSPORTAL_BINARY'):
                commands.append([os.environ['PSPORTAL_BINARY'], '--backend'])
            for command in commands:
                with self.subTest(command=command):
                    result = subprocess.run(command + ['--config', str(path), '--desktop-child'],
                        cwd=Path(__file__).resolve().parents[1], input=b'\xff\n',
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(b'Proxy stopped', result.stdout)
                    self.assertNotIn(b'Traceback', result.stderr)
                    self.assertFalse((root / 'runtime/owner.lock').exists())
                    self.assertFalse(list((root / 'runtime').glob('session-*')))

    def test_owned_child_protocol_ignores_inherited_stdio_encoding(self):
        # Exercise the actual CLI dispatch and runtime serializers without a
        # listener, subscription, Tk display or external executable.
        program = '''
import json
import sys
from portalproxy import __main__ as cli
from portalproxy.runtime import emit, validate_command
cli.load = lambda _: {'engine_mode': 'external'}
async def fixture(config, desktop_child=False):
    command = validate_command(json.loads(sys.stdin.readline()))
    assert command['preferred_node'] == chr(0x9999) + chr(0x6e2f) + ' ' + chr(0x1f30f)
    assert command['selection_group'] == chr(0x9009) + chr(0x62e9) + ' ' + chr(0x1f680)
    emit({'kind': 'nodes', 'group': command['selection_group'],
          'current': command['preferred_node']})
    print(command['preferred_node'], file=sys.stderr, flush=True)
cli.serve = fixture
raise SystemExit(cli.main(['--config', 'offline-fixture', '--desktop-child']))
'''
        value = {'command': 'select', 'selection_mode': 'fixed',
                 'selection_group': '选择 🚀', 'preferred_node': '香港 🌏'}
        data = (json.dumps(value, ensure_ascii=False) + '\n').encode('utf-8')
        for encoding in ('cp1252', 'gbk', 'ascii'):
            with self.subTest(encoding=encoding):
                result = subprocess.run([sys.executable, '-c', program],
                    cwd=Path(__file__).resolve().parents[1], input=data,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
                    env=dict(os.environ, PYTHONIOENCODING=encoding, PYTHONUTF8='0'))
                self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
                prefix, record = result.stdout.decode('utf-8').strip().split(' ', 1)
                self.assertEqual(prefix, 'PSPORTAL_EVENT')
                self.assertEqual(json.loads(record), {'kind': 'nodes',
                    'group': value['selection_group'], 'current': value['preferred_node']})
                self.assertEqual(result.stderr.decode('utf-8').strip(), value['preferred_node'])

    def test_interactive_cli_preserves_selected_output_encoding(self):
        program = '''
import sys
from portalproxy import __main__ as cli
cli.load = lambda _: {'engine_mode': 'external'}
assert cli.main(['--config', 'offline-fixture', '--check']) == 0
print(sys.stdout.encoding)
'''
        result = subprocess.run([sys.executable, '-c', program],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15,
            env=dict(os.environ, PYTHONIOENCODING='cp1252', PYTHONUTF8='0'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode('ascii').splitlines(),
                         ['Configuration is valid.', 'cp1252'])


if __name__ == '__main__':
    unittest.main()
