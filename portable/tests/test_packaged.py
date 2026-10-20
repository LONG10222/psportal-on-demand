"""Opt-in standalone executable + real core acceptance on loopback only."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from test_core import port


@unittest.skipUnless(os.environ.get('PSPORTAL_BINARY') and os.environ.get('MIHOMO_BINARY'), 'Set PSPORTAL_BINARY and MIHOMO_BINARY for packaged integration')
class PackagedTests(unittest.IsolatedAsyncioTestCase):
    async def test_unicode_node_control_uses_utf8_in_frozen_child(self):
        group, selected = '选择 🚀', '香港 🌏'
        with tempfile.TemporaryDirectory(prefix='portal unicode ') as tmp:
            root = Path(tmp)
            ports = set()
            while len(ports) < 4:
                ports.add(port())
            listen, backend, api, unused_upstream = sorted(ports)
            profile = root / 'profile.json'
            profile.write_text(json.dumps({
                'proxies': [dict(name=name, type='http', server='127.0.0.1', port=unused_upstream)
                            for name in ('日本 🗾', selected)],
                'proxy-groups': [dict(name=group, type='select', proxies=['日本 🗾', selected])],
                'rules': ['MATCH,' + group]}), encoding='utf-8')
            cfg = dict(listen_host='127.0.0.1', listen_port=listen, allowed_clients=['127.0.0.1'],
                backend_port=backend, api_port=api, core_path=os.environ['MIHOMO_BINARY'],
                profile_file=str(profile), host_profile_overlay=True, data_dir=str(root / 'runtime'))
            path = root / 'config.json'
            path.write_text(json.dumps(cfg), encoding='utf-8')
            process = await asyncio.create_subprocess_exec(os.environ['PSPORTAL_BINARY'],
                '--backend', '--config', str(path), '--desktop-child',
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=dict(os.environ, PYTHONIOENCODING='cp1252', PYTHONUTF8='0'))
            try:
                self.assertIn(b'Proxy ready', await asyncio.wait_for(process.stdout.readline(), 20))

                async def command(value):
                    process.stdin.write((json.dumps(value, ensure_ascii=False) + '\n').encode('utf-8'))
                    await process.stdin.drain()
                    async def response():
                        while True:
                            line = await process.stdout.readline()
                            self.assertTrue(line, 'Frozen child exited before its node response')
                            if line.startswith(b'PSPORTAL_EVENT '):
                                event = json.loads(line[len(b'PSPORTAL_EVENT '):].decode('utf-8'))
                                if event.get('id') == value['id']:
                                    return event
                    event = await asyncio.wait_for(response(), 20)
                    self.assertEqual(event['kind'], 'nodes', event)
                    self.assertEqual(event['group'], group)
                    return event

                state = await command(dict(id=1, action='nodes'))
                self.assertIn(selected, [node['name'] for node in state['rows']])
                state = await command(dict(id=2, action='select', group=group, name=selected))
                self.assertEqual(state['current'], selected)
                self.assertEqual(state['policies'][group], dict(mode='manual', name=selected))
                process.stdin.close()
                output = await asyncio.wait_for(process.stdout.read(), 20)
                self.assertEqual(await asyncio.wait_for(process.wait(), 20), 0, output)
                self.assertFalse((root / 'runtime/owner.lock').exists())
                self.assertFalse(list((root / 'runtime').glob('session-*')))
            finally:
                if process.returncode is None:
                    process.stdin.close()
                    try:
                        await asyncio.wait_for(process.wait(), 15)
                    except TimeoutError:
                        process.kill()
                        await process.wait()

    async def test_packaged_http_connect_idle_rewake_and_eof_cleanup(self):
        hits = []
        async def upstream(reader, writer):
            try:
                header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
                hits.append(header)
                writer.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
                await writer.drain()
                if b'1.1.1.1:80 ' in header:
                    request = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
                    hits.append(request)
                    writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 7\r\nConnection: close\r\n\r\npackage')
                    await writer.drain()
                else:
                    while data := await reader.read(65536):
                        writer.write(data); await writer.drain()
            except (OSError, asyncio.IncompleteReadError, TimeoutError):
                pass
            finally:
                writer.close()
                try: await writer.wait_closed()
                except OSError: pass
        node = await asyncio.start_server(upstream, '127.0.0.1', 0)
        node_port = node.sockets[0].getsockname()[1]
        process = None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = root/'provider.json'
            provider.write_text(json.dumps({'proxies':[{'name':'Tokyo','type':'http','server':'127.0.0.1','port':node_port}]}))
            cfg = dict(listen_host='127.0.0.1', listen_port=port(), allowed_clients=['127.0.0.1'],
                core_path=os.environ['MIHOMO_BINARY'], subscription_file=str(provider),
                selection_mode='fixed', preferred_node='Tokyo', backend_port=port(), api_port=port(),
                idle_seconds=1, data_dir=str(root/'runtime'), health_url='https://1.1.1.1/health')
            path = root/'config.json'; path.write_text(json.dumps(cfg))
            async def listening(port_number):
                try:
                    reader, writer = await asyncio.open_connection('127.0.0.1', port_number)
                    writer.close(); await writer.wait_closed()
                    return True
                except OSError:
                    return False
            try:
                process = await asyncio.create_subprocess_exec(os.environ['PSPORTAL_BINARY'], '--backend', '--config', str(path), '--desktop-child',
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                line = await asyncio.wait_for(process.stdout.readline(), 15)
                self.assertIn(b'Proxy ready', line)
                self.assertFalse(await listening(cfg['backend_port']))
                for attempt in range(2):
                    reader, writer = await asyncio.open_connection('127.0.0.1', cfg['listen_port'])
                    writer.write(b'GET http://1.1.1.1/fixture HTTP/1.1\r\nHost: 1.1.1.1\r\n\r\n'); await writer.drain()
                    response = await asyncio.wait_for(reader.read(), 20)
                    self.assertIn(b'200 OK', response); self.assertIn(b'package', response)
                    writer.close(); await writer.wait_closed()
                    reader, writer = await asyncio.open_connection('127.0.0.1', cfg['listen_port'])
                    writer.write(b'CONNECT 1.1.1.1:443 HTTP/1.1\r\nHost: 1.1.1.1:443\r\n\r\n'); await writer.drain()
                    self.assertIn(b'200', await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10))
                    writer.write(b'echo'); await writer.drain()
                    self.assertEqual(await asyncio.wait_for(reader.readexactly(4), 5), b'echo')
                    await asyncio.sleep(1.2)
                    self.assertTrue(await listening(cfg['backend_port']))
                    writer.close(); await writer.wait_closed()
                    for _ in range(40):
                        if not await listening(cfg['backend_port']): break
                        await asyncio.sleep(.1)
                    self.assertFalse(await listening(cfg['backend_port']))
                process.stdin.close()
                self.assertEqual(await asyncio.wait_for(process.wait(), 15), 0)
                self.assertFalse(await listening(cfg['listen_port']))
                self.assertFalse(await listening(cfg['api_port']))
                self.assertFalse((root/'runtime'/'owner.lock').exists())
                self.assertFalse(list((root/'runtime').glob('session-*')))
                self.assertTrue(any(b'GET /fixture' in item for item in hits))
            finally:
                if process is not None and process.returncode is None:
                    process.stdin.close()
                    try: await asyncio.wait_for(process.wait(), 15)
                    except TimeoutError:
                        process.kill(); await process.wait()
                node.close(); await node.wait_closed()
