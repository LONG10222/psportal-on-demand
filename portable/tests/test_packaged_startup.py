"""Opt-in native packaged listener checks; no Mihomo or Internet is used."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest

from test_core import port


@unittest.skipUnless(os.environ.get('PSPORTAL_BINARY'), 'Set PSPORTAL_BINARY for native packaged startup checks')
class PackagedStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_configuration_listener_rejection_eof_cleanup_and_restart(self):
        binary = str(Path(os.environ['PSPORTAL_BINARY']).resolve())
        with tempfile.TemporaryDirectory(prefix='portal native test ') as tmp:
            root = Path(tmp)
            provider = root / 'provider.json'
            provider.write_text('{"proxies": []}', encoding='utf-8')
            ports = set()
            while len(ports) < 3:
                ports.add(port())
            listen, backend, api = sorted(ports)
            cfg = dict(listen_host='127.0.0.1', listen_port=listen,
                allowed_clients=['127.0.0.1'], backend_port=backend, api_port=api,
                # Existing file only: no external request is made, so no core runs.
                core_path=binary, subscription_file=str(provider),
                data_dir=str(root / 'runtime'))
            path = root / 'config.json'
            path.write_text(json.dumps(cfg), encoding='utf-8')
            check = await asyncio.create_subprocess_exec(binary, '--backend', '--config', str(path), '--check',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            output, _ = await asyncio.wait_for(check.communicate(), 20)
            self.assertEqual(check.returncode, 0, output)
            self.assertIn(b'Configuration is valid', output)
            self.assertFalse((root / 'runtime').exists())

            async def listening(number):
                try:
                    _, writer = await asyncio.open_connection('127.0.0.1', number)
                    writer.close()
                    await writer.wait_closed()
                    return True
                except OSError:
                    return False

            for _ in range(2):
                process = await asyncio.create_subprocess_exec(binary, '--backend', '--config', str(path), '--desktop-child',
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), 20)
                    self.assertIn(b'Proxy ready', line)
                    self.assertFalse(await listening(backend))
                    self.assertFalse(await listening(api))
                    reader, writer = await asyncio.open_connection('127.0.0.1', listen)
                    writer.write(b'GET http://127.0.0.1/ HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
                    await writer.drain()
                    response = await asyncio.wait_for(reader.read(), 5)
                    self.assertIn(b'403', response)
                    writer.close()
                    await writer.wait_closed()
                    process.stdin.close()
                    output = await asyncio.wait_for(process.stdout.read(), 20)
                    self.assertEqual(await asyncio.wait_for(process.wait(), 20), 0, output)
                    self.assertIn(b'Proxy stopped', output)
                    self.assertFalse(await listening(listen))
                    self.assertFalse((root / 'runtime' / 'owner.lock').exists())
                    self.assertFalse(list((root / 'runtime').glob('session-*')))
                finally:
                    if process.returncode is None:
                        process.stdin.close()
                        try:
                            await asyncio.wait_for(process.wait(), 10)
                        except TimeoutError:
                            process.kill()
                            await process.wait()
