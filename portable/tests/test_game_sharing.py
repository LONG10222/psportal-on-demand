import asyncio
import unittest
from unittest.mock import patch
from portalproxy.game_sharing import GameSharing,validate
from portalproxy.policy import Route


class IndependentSharingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.servers=[];self.writers=set();self.game=GameSharing()
        self.route_patch=patch('portalproxy.proxy.resolve_destination',side_effect=self.route);self.route_patch.start()
    async def route(self,host,port):return Route('external') if host=='external.invalid' else Route('local','127.0.0.1')
    async def asyncTearDown(self):
        self.game.stop();await self.wait(lambda:not self.game.active)
        for writer in self.writers:writer.close()
        for server in self.servers:server.close();await server.wait_closed()
        self.route_patch.stop()
    async def wait(self,predicate):
        for _ in range(200):
            if predicate():return
            await asyncio.sleep(.01)
        self.fail('service did not settle')
    async def fixture(self,name=None):
        async def handler(reader,writer):
            self.writers.add(writer)
            try:
                if name is not None:
                    header=await reader.readuntil(b'\r\n\r\n')
                    if header.startswith(b'CONNECT'):
                        writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\nready');await writer.drain();await reader.read()
                    else:
                        body=name.encode();writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body);await writer.drain()
                else:
                    while data:=await reader.read(4096):writer.write(data);await writer.drain()
            except (OSError,asyncio.IncompleteReadError):pass
            finally:writer.close();self.writers.discard(writer)
        server=await asyncio.start_server(handler,'127.0.0.1',0);self.servers.append(server)
        return server.sockets[0].getsockname()[1]
    async def start_game(self):
        # A local-only bind exercises the same ingress without opening LAN.
        blocker=await asyncio.start_server(lambda r,w:w.close(),'127.0.0.1',0);port=blocker.sockets[0].getsockname()[1];blocker.close();await blocker.wait_closed()
        self.game.start(dict(listen_host='127.0.0.1',listen_port=port,allowed_clients=['127.0.0.1']))
        await self.wait(lambda:self.game.ready);return port
    async def request(self,port,host='external.invalid'):
        reader,writer=await asyncio.open_connection('127.0.0.1',port)
        writer.write(f'GET http://{host}/ HTTP/1.1\r\nHost: {host}\r\n\r\n'.encode());await writer.drain()
        body=await asyncio.wait_for(reader.read(),3);writer.close();await writer.wait_closed();return body

    async def test_game_and_three_sources_coexist_and_stop_independently(self):
        ports=[await self.fixture(name) for name in ('owned','clash','accelerator')]
        game=await self.start_game()
        for port,name in zip(ports,('owned','clash','accelerator')):
            self.game.upstream(port)
            self.assertIn(name.encode(),await self.request(game))
            self.assertTrue(all(s.is_serving() for s in self.servers))
        self.game.stop();await self.wait(lambda:not self.game.active)
        self.assertTrue(all(s.is_serving() for s in self.servers))
        for port,name in zip(ports,('owned','clash','accelerator')):self.assertIn(name.encode(),await self.request(port))

    async def test_upstream_loss_closes_only_external_streams_and_never_falls_back(self):
        upstream=await self.fixture('owned');local=await self.fixture();game=await self.start_game();self.game.upstream(upstream)
        async def connect(host,port):
            reader,writer=await asyncio.open_connection('127.0.0.1',game)
            writer.write(f'CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n'.encode());await writer.drain()
            self.assertIn(b'200',await reader.readuntil(b'\r\n\r\n'));return reader,writer
        external,ew=await connect('external.invalid',443);self.assertEqual(await external.readexactly(5),b'ready')
        lan,lw=await connect('127.0.0.1',local);lw.write(b'first');await lw.drain();self.assertEqual(await lan.readexactly(5),b'first')
        self.game.upstream(None)
        self.assertEqual(await asyncio.wait_for(external.read(),2),b'')
        lw.write(b'still-local');await lw.drain();self.assertEqual(await asyncio.wait_for(lan.readexactly(11),2),b'still-local')
        self.assertIn(b'502',await self.request(game))
        self.assertTrue(self.game.ready)
        ew.close();lw.close();await ew.wait_closed();await lw.wait_closed()

    def test_public_bind_and_unbounded_acl_are_rejected(self):
        with self.assertRaises(ValueError):validate(dict(listen_host='0.0.0.0',listen_port=10081,allowed_clients=['192.168.1.1']))
        with self.assertRaises(ValueError):validate(dict(listen_host='192.168.1.2',listen_port=10081,allowed_clients=['8.8.8.8']))
