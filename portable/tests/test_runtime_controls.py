import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from portalproxy.config import DEFAULTS
from portalproxy.core import CoreManager
from portalproxy.existing_proxy import ExistingProxy
from portalproxy.nodes import validate_policies
from portalproxy.proxy import ProxyServer
from test_core import port


class DeviceCountsTests(unittest.IsolatedAsyncioTestCase):
    async def test_unique_live_ips_recent_clients_and_denied_connections(self):
        async def upstream(reader, writer):
            try:
                await reader.readuntil(b'\r\n\r\n')
                writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                await writer.drain()
                await reader.read()
            finally:
                writer.close()
                await writer.wait_closed()
        server = await asyncio.start_server(upstream, '127.0.0.1', 0)
        core = ExistingProxy(dict(existing_proxy_port=server.sockets[0].getsockname()[1]))
        cfg = dict(listen_host='127.0.0.1', listen_port=0,
                   allowed_clients=['127.0.0.1', '127.0.0.2'], request_timeout=10)
        proxy = ProxyServer(cfg, core)
        streams = []
        try:
            await proxy.start()
            for address in ('127.0.0.1',) * 3:
                reader, writer = await asyncio.open_connection(*proxy.bound_addresses[0][:2], local_addr=(address, 0))
                streams.append(writer)
                writer.write(b'CONNECT 1.1.1.1:443 HTTP/1.1\r\nHost: 1.1.1.1:443\r\n\r\n')
                await writer.drain()
                self.assertIn(b'200', await reader.readuntil(b'\r\n\r\n'))
            snapshot = proxy.snapshot()
            self.assertEqual((snapshot['devices'], snapshot['active']), (1, 3))
            self.assertEqual([row['requests'] for row in snapshot['clients']], [3])
            proxy.allowed_clients = frozenset()
            denied_reader, denied_writer = await asyncio.open_connection(*proxy.bound_addresses[0][:2])
            self.assertIn(b'403', await denied_reader.read())
            denied_writer.close(); await denied_writer.wait_closed()
            self.assertEqual(len(proxy.snapshot()['clients']), 1)
            self.assertEqual(proxy.snapshot()['clients'][0]['requests'], 3)
            for writer in streams[:2]:
                writer.close(); await writer.wait_closed()
            for _ in range(50):
                if proxy.stats['active'] == 1: break
                await asyncio.sleep(.01)
            snapshot = proxy.snapshot()
            self.assertEqual((snapshot['devices'], snapshot['active']), (1, 1))
            self.assertEqual(len(snapshot['clients']), 1)
            # Unit-level retention of a second, now idle IP (no OS interface changes).
            proxy.clients['192.168.1.8'] = dict(active=0, requests=1, last_seen=time.time())
            self.assertEqual(len(proxy.snapshot()['clients']), 2)
            for row in proxy.clients.values(): row['last_seen'] -= 301
            self.assertEqual(len(proxy.snapshot()['clients']), 1)  # live clients never expire
        finally:
            for writer in streams: writer.close()
            await proxy.close(); await core.close()
            server.close(); await server.wait_closed()


class PolicyValidationTests(unittest.TestCase):
    def test_rejects_unbounded_or_invalid_policies(self):
        for bad in ([], {'a': {'mode': 'unknown'}}, {'a': {'mode':'manual'}},
                    {'a\n': {'mode':'latency'}}, {str(i): {'mode':'latency'} for i in range(33)}):
            with self.assertRaises(ValueError): validate_policies(bad)
        self.assertEqual(validate_policies({'组 / A': {'mode':'manual', 'name':'节点 / 日本'}}),
                         {'组 / A': {'mode':'manual', 'name':'节点 / 日本'}})


@unittest.skipUnless(os.environ.get('MIHOMO_BINARY'), 'Set MIHOMO_BINARY for real node controller tests')
class RealNodeControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_switch_probes_auto_failure_retention_idle_restore_and_no_clash(self):
        servers, requests = [], []
        async def start_node(label, delay):
            async def upstream(reader, writer):
                try:
                    data = await reader.readuntil(b'\r\n\r\n')
                    requests.append((label, data))
                    if data.startswith(b'CONNECT '):
                        writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                        await writer.drain()
                        data = await reader.readuntil(b'\r\n\r\n')
                        requests.append((label, data))
                    await asyncio.sleep(delay)
                    writer.write(b'HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n')
                    await writer.drain()
                except (OSError, asyncio.IncompleteReadError):
                    pass
                finally:
                    writer.close(); await writer.wait_closed()
            server = await asyncio.start_server(upstream, '127.0.0.1', 0)
            servers.append(server)
            return server.sockets[0].getsockname()[1]
        fast, slow = await start_node('fast', .01), await start_node('slow', .12)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            group, fast_name, slow_name = '组 / 自动', '🇯🇵东京 / fast', 'HK / slow'
            profile = folder / 'profile.json'
            profile.write_text(json.dumps({'proxies':[
                dict(name=fast_name, type='http', server='127.0.0.1', port=fast),
                dict(name=slow_name, type='http', server='127.0.0.1', port=slow)],
                'proxy-groups':[dict(name=group, type='select', proxies=[slow_name, fast_name])],
                'rules':['MATCH,'+group]}, ensure_ascii=False))
            cfg = dict(DEFAULTS, data_dir=str(folder / 'runtime'), profile_file=str(profile),
                       host_profile_overlay=True, core_path=os.environ['MIHOMO_BINARY'],
                       backend_port=port(), api_port=port(), health_url='http://health.example/test',
                       listen_host='127.0.0.1', idle_seconds=1, wakeup_timeout=15)
            core = CoreManager(cfg)
            try:
                state = await core.nodes.command('nodes')
                self.assertIn(group, state['groups'])
                state = await core.nodes.command('select', group, fast_name)
                self.assertEqual(state['current'], fast_name)
                state = await core.nodes.command('select', group, slow_name)
                self.assertEqual(state['current'], slow_name)
                state = await core.nodes.command('latency', group)
                self.assertEqual(state['current'], fast_name, repr((state, requests)))
                self.assertEqual(state['policies'][group]['mode'], 'latency')
                self.assertTrue(all(row['delay'] > 0 for row in state['rows']))
                # Automatic mode is periodic while running, and a manual click disables it.
                core.nodes.last_test[group] = time.monotonic() - 301
                await core.nodes.tick()
                state = await core.nodes.command('select', group, slow_name)
                before = len(requests)
                core.nodes.last_test[group] = 0
                await core.nodes.tick()
                self.assertEqual(len(requests), before)
                await core._stop()
                state = await core.nodes.command('nodes', group)
                self.assertEqual(state['current'], slow_name)  # restore manual override on wake
                for server in servers: server.close(); await server.wait_closed()
                state = await core.nodes.command('latency', group)
                self.assertEqual(state['current'], slow_name)  # failed probes keep current
                self.assertTrue(all(row['delay'] is None for row in state['rows']))
                self.assertIn('failed', state['message'])
                await core._stop()
                await core.nodes.tick()
                self.assertIsNone(core.process)  # background automation never wakes a sleeping core
            finally:
                await core.close()
                for server in servers: server.close(); await server.wait_closed()
        self.assertTrue(requests)

    async def test_provider_retains_regional_default_and_supports_stable_manual_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = Path(tmp) / 'provider.json'
            provider.write_text(json.dumps({'proxies':[
                dict(name='🇯🇵 Tokyo', type='http', server='127.0.0.1', port=port()),
                dict(name='HK', type='http', server='127.0.0.1', port=port())]}))
            core = CoreManager(dict(DEFAULTS, data_dir=str(Path(tmp) / 'runtime'),
                subscription_file=str(provider), core_path=os.environ['MIHOMO_BINARY'],
                live_node_controls=True,
                backend_port=port(), api_port=port(), wakeup_timeout=15))
            try:
                state = await core.nodes.command('select', 'PORTAL', '🇯🇵 Tokyo')
                self.assertEqual(state['current'], '🇯🇵 Tokyo')
            finally:
                await core.close()


class LinkedModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_linked_client_receives_no_node_controller_calls(self):
        from portalproxy import runtime
        core = ExistingProxy({'existing_proxy_port': 7897})
        queue = asyncio.Queue()
        queue.put_nowait(dict(id=1, action='select', group='clash', name='anything'))
        with patch.object(runtime, 'emit') as emit:
            task = asyncio.create_task(runtime.commands(queue, core))
            await asyncio.sleep(.02)
            task.cancel(); await asyncio.gather(task, return_exceptions=True)
            self.assertEqual(emit.call_args.args[0]['kind'], 'control_error')
            self.assertEqual(core.active, 0)


@unittest.skipUnless(os.environ.get('PSPORTAL_TK_TEST') == '1' and os.environ.get('MIHOMO_BINARY'),
                     'Enable real Tk and Mihomo for desktop IPC integration')
class RuntimeWindowTests(unittest.TestCase):
    def test_live_device_counts_node_switch_and_language_through_owned_child(self):
        import socket
        import socketserver
        import threading
        import tkinter as tk
        from portalproxy.desktop import DesktopApp
        class Upstream(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(10)
                try:
                    while self.rfile.readline().strip(): pass
                    self.wfile.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                    self.wfile.flush()
                    while data := self.connection.recv(65536):
                        self.connection.sendall(data)
                except OSError:
                    pass
        server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Upstream)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        root, app, client = tk.Tk(), None, None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                provider = folder / 'profile.json'
                provider.write_text(json.dumps({'proxies':[
                    dict(name=name, type='http', server='127.0.0.1', port=server.server_address[1])
                    for name in ('Alpha', 'Beta')],
                    'proxy-groups':[dict(name='TEST-GROUP', type='select', proxies=['Alpha', 'Beta'])],
                    'rules':['MATCH,TEST-GROUP']}))
                ports = set()
                while len(ports) < 3: ports.add(port())
                listen, backend, api = sorted(ports)
                cfg = dict(listen_host='127.0.0.1', listen_port=listen, allowed_clients=['127.0.0.1'],
                    profile_file=str(provider), host_profile_overlay=True, core_path=os.environ['MIHOMO_BINARY'],
                    backend_port=backend, api_port=api, data_dir=str(folder / 'runtime'))
                path = folder / 'host.json'; path.write_text(json.dumps(cfg))
                app = DesktopApp(root, path)
                def wait(predicate):
                    end = time.monotonic() + 15
                    while time.monotonic() < end:
                        root.update()
                        if predicate(): return
                        time.sleep(.02)
                    self.fail(app.log_widget.get('1.0', 'end') + '\n' + app.view.node_note_var.get())
                app.start()
                wait(lambda: app.statistics is not None and app.status_var.get() == 'Listening')
                self.assertEqual(app.view.hero_var.get(), 'Ready · waiting for a device')
                app.node_command('nodes')
                wait(lambda: app.node_state is not None and app.pending_command is None)
                self.assertEqual(app.node_state['group'], 'TEST-GROUP')
                for item in app.view.live_node_table.get_children():
                    if app.view.live_node_table.item(item, 'values')[0] == 'Beta':
                        app.view.live_node_table.selection_set(item)
                app.node_command('select')
                wait(lambda: app.pending_command is None and app.node_state['current'] == 'Beta')
                self.assertEqual(json.loads(path.read_text())['node_policies']['TEST-GROUP']['name'], 'Beta')
                client = socket.create_connection(('127.0.0.1', listen), timeout=5)
                client.sendall(b'CONNECT 1.1.1.1:443 HTTP/1.1\r\nHost: 1.1.1.1:443\r\n\r\n')
                self.assertIn(b'200', client.recv(4096))
                wait(lambda: app.statistics.get('devices') == 1)
                self.assertEqual(app.statistics['active'], 1)
                self.assertEqual(app.view.hero_var.get(), 'Devices are using the proxy')
                self.assertEqual(len(app.view.client_table.get_children()), 1)
                pid = app.backend.process.pid
                app.set_language('zh'); root.update()
                self.assertEqual(app.view.hero_var.get(), '设备正在使用代理')
                self.assertEqual(app.backend.process.pid, pid)
                app.raw['existing_proxy_port'] = server.server_address[1]
                app.view.refresh()
                self.assertTrue(all(str(button['state']) == 'disabled' for button in app.view.node_buttons))
                self.assertIn('Clash', app.view.node_note_var.get())
                app.raw.pop('existing_proxy_port')
                client.close(); client = None
                wait(lambda: app.statistics.get('devices') == 0)
                self.assertIn('等待设备', app.view.hero_var.get())
                self.assertEqual(len(app.view.client_table.get_children()), 1)  # recent, now idle
                app.stop(); wait(lambda: app.backend.process is None)
        finally:
            if client: client.close()
            if app:
                app.backend.stop()
                if app.backend.process: app.backend.process.wait(timeout=15)
            for timer in root.tk.splitlist(root.tk.call('after', 'info')):
                root.tk.call('after', 'cancel', timer)
            root.destroy()
            server.shutdown(); server.server_close()
