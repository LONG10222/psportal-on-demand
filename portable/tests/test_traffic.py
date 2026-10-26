import asyncio
import json
import unittest
from unittest.mock import patch
from portalproxy.traffic import TrafficMeter, validate_traffic
from portalproxy.backend import parse_status
from portalproxy.policy import Route
from portalproxy.shared_proxy import SharedProxy


class TrafficTests(unittest.TestCase):
    def test_destination_scopes_rates_and_idle(self):
        clock=[0.0];meter=TrafficMeter(lambda:clock[0])
        meter.add('local','upload',100);meter.add('external','download',200)
        meter.add('deny','upload',900)
        clock[0]=2;snapshot=meter.snapshot()
        self.assertEqual(snapshot['local']['upload_bps'],50)
        self.assertEqual(snapshot['external']['download_bytes'],200)
        clock[0]=4;self.assertEqual(meter.snapshot()['external']['download_bps'],0)

    def test_invalid_runtime_traffic_is_rejected(self):
        clean=TrafficMeter().snapshot()
        for value in (-1, float('nan'), '100'):
            bad={k:dict(v) for k,v in clean.items()};bad['local']['upload_bps']=value
            with self.assertRaises(ValueError):validate_traffic(bad)
        record=dict(event='status',state='listening',connected_clients=0,active_connections=0,traffic=clean)
        self.assertEqual(parse_status(json.dumps(record))['traffic'],clean)


class SharedCoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_closed_tunnel_does_not_poison_shared_listener_health(self):
        async def upstream(reader, writer):
            await reader.readuntil(b'\r\n\r\n')
            writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n');await writer.drain()
            await reader.read();writer.close();await writer.wait_closed()
        server=await asyncio.start_server(upstream,'127.0.0.1',0)
        endpoint=('127.0.0.1',server.sockets[0].getsockname()[1])
        class Core:
            active=0
            async def acquire(self):self.active+=1;return endpoint
            async def release(self):self.active-=1
            def status(self):return dict(core_state='running')
        core=Core();proxy=SharedProxy(dict(listen_host='127.0.0.1',listen_port=0,local_proxy_port=0,allowed_clients=['127.0.0.1']),core)
        async def reset(send,receive):
            send.close();receive.close();raise ConnectionResetError('fixture client disconnect')
        try:
            await proxy.start()
            with patch('portalproxy.proxy.resolve_destination',return_value=Route('external')),patch.object(proxy.local,'_duplex',side_effect=reset):
                reader,writer=await asyncio.open_connection('127.0.0.1',proxy.local.bound_addresses[0][1])
                writer.write(b'CONNECT example.invalid:443 HTTP/1.1\r\nHost: example.invalid:443\r\n\r\n');await writer.drain()
                self.assertIn(b'200 Connection Established',await asyncio.wait_for(reader.read(),3))
                writer.close();await writer.wait_closed();await asyncio.sleep(.05)
            self.assertEqual(core.active,0)
            self.assertEqual(proxy.status()['state'],'listening')
            self.assertEqual(proxy.status()['stats']['errors'],1)
        finally:
            await proxy.close();server.close();await server.wait_closed()

    async def test_two_inputs_share_one_core_and_one_node_selection(self):
        tasks=set()
        async def origin(reader,writer):
            tasks.add(asyncio.current_task())
            try:
                await reader.readuntil(b'\r\n\r\n')
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nyes');await writer.drain()
            finally:
                writer.close();await writer.wait_closed();tasks.discard(asyncio.current_task())
        server=await asyncio.start_server(origin,'127.0.0.1',0)
        endpoint=('127.0.0.1',server.sockets[0].getsockname()[1])
        class Core:
            calls=0;node='shared-node'
            async def acquire(self):self.calls+=1;return endpoint
            async def release(self):pass
            def status(self):return dict(core_state='running',selected_node=self.node)
        core=Core()
        proxy=SharedProxy(dict(listen_host='127.0.0.1',listen_port=0,local_proxy_port=0,
            allowed_clients=['127.0.0.1']),core)
        try:
            await proxy.start()
            self.assertIs(proxy.primary.core,proxy.local.core)
            for input in (proxy.primary,proxy.local):
                reader,writer=await asyncio.open_connection('127.0.0.1',input.bound_addresses[0][1])
                with patch('portalproxy.proxy.resolve_destination',return_value=Route('external')):
                    writer.write(b'GET http://example.invalid/ HTTP/1.1\r\nHost: example.invalid\r\n\r\n');await writer.drain()
                    self.assertIn(b'yes',await asyncio.wait_for(reader.read(),3))
                writer.close();await writer.wait_closed()
            self.assertEqual(core.calls,2)
            status=proxy.status()
            self.assertTrue(status['shared_core']);self.assertEqual(status['selected_node'],'shared-node')
            self.assertGreater(status['traffic']['external']['upload_bytes'],0)
            self.assertGreater(status['traffic']['external']['download_bytes'],6)
            self.assertEqual(status['traffic']['local']['download_bytes'],0)
        finally:
            await proxy.close();server.close();await server.wait_closed()
            if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        self.assertFalse(proxy.primary.bound_addresses);self.assertFalse(proxy.local.bound_addresses)

    async def test_second_bind_failure_closes_first_input(self):
        blocker=await asyncio.start_server(lambda r,w:w.close(),'127.0.0.1',0)
        port=blocker.sockets[0].getsockname()[1]
        proxy=SharedProxy(dict(listen_host='127.0.0.1',listen_port=0,local_proxy_port=port,allowed_clients=['127.0.0.1']),object())
        try:
            with self.assertRaises(OSError):await proxy.start()
            self.assertFalse(proxy.primary.bound_addresses)
        finally:
            await proxy.close();blocker.close();await blocker.wait_closed()
