import asyncio
import base64
import copy
import json
from pathlib import Path
import socket
import struct
import tempfile
import unittest
from unittest.mock import patch

from starpass_xianniu.provider import Provider, validate
from starpass_xianniu.storage import Store
from xianniu_router.protocol import frame, read_frame


AUTH = {'u': base64.b64encode(b'fixture').decode(), 'key': base64.b64encode(b'fixture-key').decode(), 'plain_second': True}


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); return sock.getsockname()[1]


def config(mode='borrowed'):
    value = dict(account={'access_token':'fixture-account'}, auth=AUTH, node={'host':'8.8.8.8','port':443},
                 game_id=797,profile={'area_id':933,'line_id':122},hardware='fixture',dns_server='192.168.1.1',
                 session_mode=mode,listen_host='127.0.0.1',http_port=free_port(),socks_port=free_port(),devices=[])
    if mode == 'borrowed': value['external_session_owner']='fixture-owner'
    return value


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api_calls=[]
        def api(cfg,path,value):
            self.api_calls.append(path)
            return {'total_datetime':3600,'free_datetime':100,'pause_state':1}
        self.api_patch=patch('starpass_xianniu.provider.control.call_api',side_effect=api);self.api_patch.start()
        self.refresh_patch=patch('starpass_xianniu.provider.control.refresh',return_value=AUTH);self.refresh=self.refresh_patch.start()
        self.starts=patch('starpass_xianniu.provider.control.start_session',side_effect=self.start_session);self.start_mock=self.starts.start()
        self.stops=patch('starpass_xianniu.provider.control.stop_session',side_effect=self.stop_session);self.stop_mock=self.stops.start()
        self.providers=[]

    def start_session(self,cfg):
        cfg['_owned_session_started']=True
        return {'host':'8.8.8.8','port':443},AUTH

    def stop_session(self,cfg,counters):
        cfg['_owned_session_started']=False
        return True

    async def asyncTearDown(self):
        for p in self.providers: await p.stop()
        for item in (self.api_patch,self.refresh_patch,self.starts,self.stops):item.stop()

    async def provider(self,mode='borrowed',store=None):
        p=Provider(config(mode),store);self.providers.append(p)
        await p.start(exclusive=mode=='managed')
        return p

    async def connect(self,p,port='http_port',source=None):
        return await asyncio.open_connection('127.0.0.1',p.config[port],local_addr=(source,0) if source else None)

    async def test_borrowed_never_starts_stops_recovers_or_pauses_owner(self):
        p=await self.provider();await p.stop();await p.stop()
        self.start_mock.assert_not_called();self.stop_mock.assert_not_called()
        self.assertTrue(all(x=='/client/member/details' for x in self.api_calls))

    async def test_managed_requires_explicit_exclusivity(self):
        p=Provider(config('managed'));self.providers.append(p)
        with self.assertRaises(ValueError):await p.start()
        self.start_mock.assert_not_called()
        with self.assertRaises(OSError):await self.connect(p)

    async def test_pause_rejected_for_borrowed_session(self):
        p=await self.provider()
        with self.assertRaises(ValueError):await p.stop_and_pause()
        self.assertTrue(p.running)
        self.assertNotIn('/client/member/suspend',self.api_calls)

    async def test_owned_stop_then_pause_is_confirmed(self):
        p=await self.provider('managed')
        def api(cfg,path,value):
            self.api_calls.append(path)
            return {'pause_state':0,'total_datetime':3600}
        with patch('starpass_xianniu.provider.control.call_api',side_effect=api):
            member=await p.stop_and_pause()
        self.assertEqual(member['pause_state'],0)
        self.assertFalse(p.running);self.assertTrue(p.stop_ok)
        self.assertIn('/client/member/suspend',self.api_calls)

    async def test_official_free_game_starts_and_stops_while_account_timer_stays_paused(self):
        def paused(cfg,path,value):
            self.api_calls.append(path)
            return {'pause_state':0,'total_datetime':3600}
        cfg=config('managed');cfg['game_id']=12
        with patch('starpass_xianniu.provider.control.call_api',side_effect=paused),patch('starpass_xianniu.provider.resolve_billing',return_value={'kind':'free','source':'official_fixture'}):
            p=Provider(cfg);self.providers.append(p)
            p.renew_seconds=.01
            await p.start(exclusive=True)
            self.assertTrue(p.running)
            self.assertEqual(p.billing['kind'],'free')
            self.start_mock.assert_called_once();self.refresh.assert_called_once()
            await asyncio.sleep(.08)
            self.assertGreaterEqual(p.renewals,1)
            member=await p.stop_and_pause()
        self.assertEqual(member['pause_state'],0)
        self.stop_mock.assert_called_once()
        self.assertNotIn('/client/member/recovery',self.api_calls)
        self.assertNotIn('/client/member/suspend',self.api_calls)

    async def test_rejected_free_session_never_falls_back_to_paid_recovery(self):
        from xianniu_router.control import APIError
        cfg=config('managed');cfg['game_id']=12
        self.start_mock.side_effect=APIError(400065)
        with patch('starpass_xianniu.provider.resolve_billing',return_value={'kind':'free','source':'official_fixture'}):
            p=Provider(cfg);self.providers.append(p)
            with self.assertRaises(APIError):await p.start(exclusive=True)
        self.assertNotIn('/client/member/recovery',self.api_calls)
        self.assertNotIn('/client/member/suspend',self.api_calls)
        self.assertFalse(p.running);self.refresh.assert_not_called()

    async def test_unknown_billing_rule_does_not_resume_or_start(self):
        with patch('starpass_xianniu.provider.resolve_billing',return_value={'kind':'unknown','source':'fixture'}):
            p=Provider(config('managed'));self.providers.append(p)
            with self.assertRaises(ValueError):await p.start(exclusive=True)
        self.start_mock.assert_not_called()
        self.assertNotIn('/client/member/recovery',self.api_calls)

    async def test_paid_project_keeps_existing_paused_timer_recovery(self):
        def paused(cfg,path,value):
            self.api_calls.append(path)
            return {'pause_state':0,'total_datetime':3600}
        with patch('starpass_xianniu.provider.control.call_api',side_effect=paused),patch('starpass_xianniu.provider.resolve_billing',return_value={'kind':'paid','source':'official_fixture'}):
            await self.provider('managed')
        self.assertEqual(self.api_calls.count('/client/member/recovery'),1)

    async def test_external_owner_cannot_be_stopped_by_managed(self):
        cfg=config('managed');cfg['external_session_owner']='N1'
        p=Provider(cfg);self.providers.append(p)
        with self.assertRaises(ValueError):await p.start(exclusive=True)
        self.start_mock.assert_not_called();self.stop_mock.assert_not_called()

    async def test_owned_start_stop_once_and_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);p=await self.provider('managed',store)
            self.assertTrue(store.unresolved())
            await asyncio.gather(p.stop(),p.stop())
            self.assertFalse(store.unresolved());self.assertEqual(self.stop_mock.call_count,1)
            with self.assertRaises(OSError):await self.connect(p)

    async def test_startup_port_conflict_does_not_start_paid_session(self):
        cfg=config('managed')
        server=await asyncio.start_server(lambda r,w:w.close(),'127.0.0.1',cfg['socks_port'])
        try:
            p=Provider(cfg);self.providers.append(p)
            with self.assertRaises(OSError):await p.start(exclusive=True)
            self.start_mock.assert_not_called();self.stop_mock.assert_not_called()
            with self.assertRaises(OSError):await self.connect(p)
        finally:server.close();await server.wait_closed()

    async def test_http_and_socks_deny_unselected_source(self):
        p=await self.provider()
        r,w=await self.connect(p,source='127.0.0.2')
        self.assertIn(b'403',await r.read(1024));w.close();await w.wait_closed()
        r,w=await self.connect(p,'socks_port','127.0.0.2')
        self.assertEqual(await r.read(1024),b'');w.close();await w.wait_closed()
        self.assertGreater(p.service.counters['rejected'],0)

    async def test_http_native_binary_tunnel_and_stop_closes_active_connections(self):
        async def node(r,w):
            try:
                self.assertEqual(await read_frame(r),b'\x00binary\xff')
                w.write(frame(b'\xffreply\x00'));await w.drain();await r.read()
            finally:w.close()
        server=await asyncio.start_server(node,'127.0.0.1',0)
        p=await self.provider()
        async def native(command,host,port):
            self.assertEqual((command,host,port),(1,'8.8.8.8',443))
            r,w=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1])
            return r,w,b'\0Z'+b'\0'*6
        p.service.open_native=native
        try:
            r,w=await self.connect(p)
            w.write(b'CONNECT 8.8.8.8:443 HTTP/1.1\r\nHost: 8.8.8.8:443\r\n\r\n');await w.drain()
            self.assertIn(b'200',await r.readuntil(b'\r\n\r\n'))
            w.write(b'\x00binary\xff');await w.drain()
            self.assertEqual(await r.readexactly(7),b'\xffreply\x00')
            await p.stop()
            self.assertEqual(await asyncio.wait_for(r.read(),1),b'')
            w.close();await w.wait_closed()
        finally:server.close();await server.wait_closed()

    async def test_private_and_fakeip_http_destinations_fail_before_native(self):
        p=await self.provider()
        for host in ('192.168.1.1','198.18.0.1','127.0.0.1'):
            r,w=await self.connect(p)
            w.write(f'CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n'.encode());await w.drain()
            self.assertIn(b'403',await r.read(1024));w.close();await w.wait_closed()
        self.assertEqual(p.service.counters['tcp_connections'],0)

    async def test_udp_association_has_lan_address_and_rejects_wrong_source_fragment_and_private(self):
        p=await self.provider()
        loop=asyncio.get_running_loop()
        remote=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);remote.bind(('127.0.0.1',0));remote.setblocking(False)
        controls=[]
        async def native(command,host,port):
            a,b=await asyncio.open_connection('127.0.0.1',control_server.sockets[0].getsockname()[1])
            return a,b,b'\0Z'+struct.pack('<H',remote.getsockname()[1])+b'\0'*4
        async def hold(r,w):controls.append(w);await r.read();w.close()
        control_server=await asyncio.start_server(hold,'127.0.0.1',0)
        p.service.open_native=native;p.config['node']['host']='127.0.0.1'
        r,w=await self.connect(p,'socks_port');w.write(b'\5\1\0');await w.drain();self.assertEqual(await r.readexactly(2),b'\5\0')
        w.write(b'\5\3\0\1'+b'\0'*6);await w.drain();reply=await r.readexactly(10)
        endpoint=(socket.inet_ntoa(reply[4:8]),struct.unpack('!H',reply[8:10])[0])
        self.assertEqual(endpoint[0],'127.0.0.1')
        client=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);client.bind(('127.0.0.1',0));client.setblocking(False)
        stranger=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);stranger.bind(('127.0.0.2',0));stranger.setblocking(False)
        packet=b'\0\0\0\1'+socket.inet_aton('8.8.8.8')+struct.pack('!H',3478)+b'fixture'
        try:
            await loop.sock_sendto(stranger,packet,endpoint)
            await loop.sock_sendto(client,b'\0\0\1'+packet[3:],endpoint)
            await loop.sock_sendto(client,b'\0\0\0\1'+socket.inet_aton('192.168.1.1')+packet[8:],endpoint)
            with self.assertRaises(asyncio.TimeoutError):await asyncio.wait_for(loop.sock_recvfrom(remote,100),.15)
            await loop.sock_sendto(client,packet,endpoint)
            native_packet,node_peer=await asyncio.wait_for(loop.sock_recvfrom(remote,100),1)
            self.assertEqual(native_packet,b'\xfe'+packet[4:])
            await loop.sock_sendto(remote,native_packet,node_peer)
            returned,_=await asyncio.wait_for(loop.sock_recvfrom(client,100),1)
            self.assertEqual(returned,packet)
            self.assertEqual(p.service.counters['udp_packets'],1)
            w.close();await w.wait_closed();await asyncio.sleep(.05)
            self.assertTrue(all(t.done() for t in p.service.tasks))
        finally:
            client.close();stranger.close();remote.close();control_server.close();await control_server.wait_closed()
            for stream in controls:stream.close()

    async def test_renew_failure_closes_listeners_instead_of_fallback(self):
        p=Provider(config());self.providers.append(p);p.renew_seconds=.01;p.retry_seconds=.01
        self.refresh.side_effect=[AUTH,RuntimeError('fixture'),RuntimeError('fixture'),RuntimeError('fixture')]
        await p.start();await asyncio.sleep(.2)
        self.assertFalse(p.running)
        with self.assertRaises(OSError):await self.connect(p)
        self.stop_mock.assert_not_called()

    async def test_status_excludes_all_credentials(self):
        p=await self.provider()
        text=json.dumps(p.status())
        for secret in ('fixture-account','fixture-key','access_token','"auth"'):
            self.assertNotIn(secret,text)
        self.assertFalse(p.status()['console_udp_captured'])

    async def test_restart_after_stop(self):
        p=await self.provider();await p.stop();await p.start()
        self.assertTrue(p.running);self.start_mock.assert_not_called()


class StorageTests(unittest.TestCase):
    def test_dpapi_roundtrip_and_no_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);cfg=config();cfg['_owned_session_started']=True
            store.save(cfg)
            self.assertNotIn(b'fixture-account',store.path.read_bytes())
            self.assertNotIn('fixture-account',(store.root/'lan-access.json').read_text())
            self.assertNotIn('account',(store.root/'lan-access.json').read_text())
            self.assertEqual(store.load()['account'],cfg['account'])
            self.assertNotIn('_owned_session_started',store.load())

    def test_ownership_cannot_be_imported(self):
        cfg=config();cfg['_owned_session_started']=True
        self.assertNotIn('_owned_session_started',validate(cfg))

    def test_wildcard_and_duplicate_ports_rejected(self):
        cfg=config();cfg['listen_host']='0.0.0.0'
        with self.assertRaises(ValueError):validate(cfg)
        cfg=config();cfg['http_port']=cfg['socks_port']
        with self.assertRaises(ValueError):validate(cfg)


if __name__=='__main__':unittest.main()
