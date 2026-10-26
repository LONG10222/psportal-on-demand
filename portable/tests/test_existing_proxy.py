import asyncio
import subprocess
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from portalproxy import config
from portalproxy.existing_proxy import ExistingProxy, detect_system_proxy, read_clash_accounting
from portalproxy.proxy import ProxyServer


class ExistingProxyConfigTests(unittest.TestCase):
    def test_linked_mixed_mode_requires_explicit_host_acl_and_local_only_remains_separate(self):
        raw = dict(existing_proxy_port=7897, product_mode='game',
            listen_host='192.168.50.2', allowed_clients=['192.168.50.3'])
        self.assertEqual(config.validate(raw, '/unused.json')['product_mode'], 'game')
        with self.assertRaisesRegex(ValueError,'allowed devices'):
            config.validate(dict(raw,product_mode='mixed'),'/unused.json')
        mixed=dict(raw,product_mode='mixed',allowed_clients=['192.168.50.3','192.168.50.2'])
        self.assertEqual(config.validate(mixed,'/unused.json')['allowed_clients'],mixed['allowed_clients'])
        with self.assertRaisesRegex(ValueError,'game mode only'):
            config.validate(dict(raw,product_mode='clash'),'/unused.json')
    def test_clash_cache_reader_returns_only_active_accounting_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'profiles.yaml'
            raw=json.dumps({'current':'active','items':[
                {'uid':'other','extra':{'total':999}},
                {'uid':'active','name':'fixture profile','url':'https://provider.example/secret-token',
                 'password':'do-not-return','extra':{'upload':10,'download':20,'total':100,'expire':2000000000},'updated':1900000000}]})
            path.write_text(raw)
            info=read_clash_accounting(path)
            self.assertEqual(info['total'],100)
            self.assertEqual(info['source_kind'],'clash-cache')
            self.assertNotIn('secret-token',str(info))
            self.assertNotIn('do-not-return',str(info))
            self.assertNotIn('url',info)
            self.assertEqual(path.read_text(),raw)

    def test_reuse_needs_no_core_or_subscription_and_rejects_self_loop(self):
        raw = dict(existing_proxy_port=7897, listen_host='127.0.0.1', allowed_clients=['127.0.0.1'])
        self.assertEqual(config.validate(raw, '/tmp/unused.json')['existing_proxy_port'], 7897)
        for value in (10081, 80, '7897'):
            with self.assertRaises(ValueError):
                config.validate(dict(raw, existing_proxy_port=value), '/tmp/unused.json')

    def test_discovery_is_read_only_and_accepts_only_loopback_proxy(self):
        for host, expected in [('127.0.0.1',7897),('localhost',7897),('8.8.8.8',None)]:
            result=subprocess.CompletedProcess([],0,stdout=f'<dictionary> {{\n HTTPEnable : 1\n HTTPProxy : {host}\n HTTPPort : 7897\n}}\n')
            with patch('portalproxy.existing_proxy.sys.platform','darwin'), patch('portalproxy.existing_proxy.subprocess.run',return_value=result) as command:
                info=detect_system_proxy()
                self.assertEqual(info['port'] if info else None,expected)
                self.assertEqual(command.call_args.args[0],['/usr/sbin/scutil','--proxy'])


class ExistingProxyTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_connect_and_stop_never_manage_the_existing_process(self):
        calls=[]
        async def upstream(reader,writer):
            try:
                request=await reader.readuntil(b'\r\n\r\n');calls.append(request)
                if request.startswith(b'CONNECT '):
                    writer.write(b'HTTP/1.1 200 OK\r\n\r\n');await writer.drain()
                    data=await reader.read(5);writer.write(data);await writer.drain()
                else:
                    writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nreused');await writer.drain()
            finally:
                writer.close();await writer.wait_closed()
        server=await asyncio.start_server(upstream,'127.0.0.1',0)
        endpoint=server.sockets[0].getsockname()
        cfg=dict(config.DEFAULTS,listen_host='127.0.0.1',listen_port=0,allowed_clients=['127.0.0.1'],existing_proxy_port=endpoint[1])
        core=ExistingProxy(cfg);proxy=ProxyServer(cfg,core)
        try:
            await proxy.start();address=proxy.bound_addresses[0][:2]
            reader,writer=await asyncio.open_connection(*address)
            writer.write(b'GET http://1.1.1.1/fixture HTTP/1.1\r\nHost: 1.1.1.1\r\n\r\n');await writer.drain()
            self.assertIn(b'reused',await asyncio.wait_for(reader.read(),3))
            writer.close();await writer.wait_closed()
            reader,writer=await asyncio.open_connection(*address)
            writer.write(b'CONNECT 1.1.1.1:443 HTTP/1.1\r\nHost: 1.1.1.1:443\r\n\r\n');await writer.drain()
            self.assertIn(b'200',await reader.readuntil(b'\r\n\r\n'))
            writer.write(b'hello');await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(5),3),b'hello')
            writer.close();await writer.wait_closed()
            await proxy.close();await core.close()
            self.assertTrue(server.is_serving())
            self.assertEqual(len(calls),2)
            self.assertEqual(core.active,0)
        finally:
            await proxy.close();await core.close()
            server.close();await server.wait_closed()
