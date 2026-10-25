"""Exercise fixed entries with real local TCP, routing snapshots and coordination."""
import asyncio,importlib.util,json,sys,tempfile,unittest,subprocess
from pathlib import Path
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'gateway'),str(ROOT/'integrations/xianniu-router/src')]
import entry,control
from starpass_http.proxy import ProxyServer

class State:
    route='direct';snapshot=('direct',None,'')
    def refresh(self):pass

class Routing(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):self.servers=[];self.events=[]
    async def asyncTearDown(self):
        for s in self.servers:s.close();await s.wait_closed()
    async def backend(self,kind):
        async def client(reader,writer):
            try:
                if kind=='http':
                    h=await reader.readuntil(b'\r\n\r\n');self.events.append(('connect',h))
                    writer.write(b'HTTP/1.1 200 OK\r\n\r\n');await writer.drain()
                elif kind=='socks':
                    self.assertEqual(await reader.readexactly(3),b'\x05\x01\x00')
                    writer.write(b'\x05\x00');await writer.drain()
                    head=await reader.readexactly(5);self.assertEqual(head[:4],b'\x05\x01\x00\x03')
                    await reader.readexactly(head[4]+2)
                    writer.write(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x01');await writer.drain()
                h=await reader.readuntil(b'\r\n\r\n');self.events.append(('origin',h))
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK');await writer.drain()
            finally:writer.close()
        s=await asyncio.start_server(client,'127.0.0.1',0);self.servers.append(s)
        return s.sockets[0].getsockname()
    async def request(self,route):
        address=await self.backend('socks' if route=='socks' else 'http' if route in ('game','starpass') else 'direct')
        state=State();state.route=route;state.snapshot=(route,address,'private-token' if route=='starpass' else '')
        core=entry.SwitchingCore(state)
        proxy=ProxyServer({'listen_host':'127.0.0.1','listen_port':0,'allowed_clients':['127.0.0.1'],'destination_resolver':entry.resolve},core)
        original=asyncio.open_connection
        async def connect(host,port,*args,**kw):
            if host=='93.184.216.34':host,port=address
            return await original(host,port,*args,**kw)
        async def dns(*args,**kw):return [(2,1,6,'',('93.184.216.34',80))]
        await proxy.start()
        try:
            with patch('entry.option',return_value='127.0.0.1'),patch('entry.asyncio.open_connection',side_effect=connect),patch('entry.resolve_real',return_value='93.184.216.34'):
                reader,writer=await original(*proxy.bound_addresses[0][:2])
                writer.write(b'GET http://example.com/test HTTP/1.1\r\nHost: example.com\r\nProxy-Authorization: Basic CLIENTSECRET\r\n\r\n');await writer.drain()
                response=await reader.read();writer.close()
                self.assertIn(b'200 OK',response);self.assertTrue(response.endswith(b'OK'))
        finally:await proxy.close()
        origin=next(v for k,v in self.events if k=='origin')
        self.assertTrue(origin.startswith(b'GET /test HTTP/1.1'))
        self.assertNotIn(b'CLIENTSECRET',origin);self.assertNotIn(b'private-token',origin)
        if route=='starpass':self.assertIn(b'private-token',self.events[0][1])
    async def test_off_direct_uses_pinned_default_connection(self):await self.request('direct')
    async def test_game_uses_original_local_listener(self):await self.request('game')
    async def test_openclash_auth_is_only_sent_to_local_backend(self):await self.request('starpass')
    async def test_accelerator_uses_existing_loopback_socks(self):await self.request('socks')
    async def test_same_listening_port_survives_off_on_off(self):
        direct=await self.backend('direct');accelerated=await self.backend('socks')
        state=State();core=entry.SwitchingCore(state)
        server=ProxyServer({'listen_host':'127.0.0.1','listen_port':0,'allowed_clients':['127.0.0.1'],'destination_resolver':entry.resolve},core)
        original=asyncio.open_connection
        async def connect(host,port,*args,**kwargs):
            if host=='93.184.216.34':host,port=direct
            return await original(host,port,*args,**kwargs)
        await server.start();front=server.bound_addresses[0][:2]
        try:
            with patch('entry.resolve_real',return_value='93.184.216.34'),patch('entry.option',return_value='127.0.0.1'),patch('entry.asyncio.open_connection',side_effect=connect):
                for route,endpoint in [('direct',None),('socks',accelerated),('direct',None)]:
                    state.route=route;state.snapshot=(route,endpoint,'')
                    reader,writer=await original(*front)
                    writer.write(b'GET http://example.com/test HTTP/1.1\r\nHost: example.com\r\n\r\n');await writer.drain()
                    self.assertTrue((await reader.read()).endswith(b'OK'));writer.close()
                    self.assertEqual(server.bound_addresses[0][:2],front)
        finally:await server.close()

    async def test_concurrent_clients_do_not_share_route_selection(self):
        state=State();state.route='game';state.snapshot=('game',('127.0.0.1',18880),'')
        core=entry.SwitchingCore(state)
        async def request(ip):
            core.set_client(ip);await core.acquire_for_request('example.com',443)
            await asyncio.sleep(0)
            return core.selected.get()[0]
        with patch('entry.option',return_value='192.168.50.30'):
            result=await asyncio.gather(request('192.168.50.30'),request('192.168.50.99'))
        self.assertEqual(result,['game','direct'])

    async def test_non_game_client_is_direct_while_game_is_enabled(self):
        s=State();s.route='game';s.snapshot=('game',('127.0.0.1',18880),'')
        core=entry.SwitchingCore(s);core.set_client('192.168.50.99')
        with patch('entry.option',return_value='192.168.50.30'):await core.acquire_for_request('example.com',443)
        self.assertEqual(core.selected.get(),('direct',None,''))

class Coordination(unittest.TestCase):
    def test_game_on_disables_starpass_before_starting_game(self):
        events=[]
        with patch('control.ensure_entry'),patch('control.option',side_effect=lambda c,k,*d: 'standalone' if k=='main.core_mode' else '0'),patch('control.set_options',side_effect=lambda **k:events.append(k)),patch('control.stop_openclash',side_effect=lambda:events.append('stop-openclash')),patch('control.run',side_effect=lambda a,*x:events.append(a)):
            control.action('game-on')
        self.assertLess(events.index('stop-openclash'),next(i for i,x in enumerate(events) if x==['/etc/init.d/portalproxy','start']))
        self.assertIn({'starpass_enabled':0},events)
    def test_switch_pause_stops_session_before_account_pause(self):
        events=[];manager=Mock()
        manager.finish.side_effect=lambda:events.append('finish') or {'billing':'paid'}
        manager.config.return_value={'account':{'access_token':'fixture'}}
        manager.member.return_value={'pause_state':1}
        manager.member_pause.side_effect=lambda:events.append('pause')
        with patch('xianniu_router.manager.Manager',return_value=manager):control.pause_accelerator()
        self.assertEqual(events,['finish','pause'])

    def test_boot_sync_restores_owned_manual_core_without_losing_saved_feature(self):
        def get(config,key,*default):return '1'
        with patch('control.service_running',return_value=False),patch('control.option',side_effect=get),patch('control.OWNER') as owner,patch('control.start_openclash') as start,patch('control.set_options') as write:
            owner.exists.return_value=True
            control.action('sync')
            start.assert_called_once();write.assert_not_called()

    def test_openclash_ui_disable_updates_feature_and_releases_boot_owner(self):
        def get(config,key,*default):return '0' if config=='openclash' else '1'
        with patch('control.service_running',return_value=False),patch('control.option',side_effect=get),patch('control.set_options') as write,patch('control.release_manual_owner') as release:
            control.action('sync')
            write.assert_called_once_with(starpass_enabled=0);release.assert_called_once()

    def test_failed_starpass_start_restores_game(self):
        events=[]
        with patch('control.ensure_entry'),patch('control.option',return_value='1'),patch('control.set_options',side_effect=lambda **k:events.append(k)),patch('control.stop_openclash'),patch('control.start_openclash',side_effect=RuntimeError),patch('control.run') as run:
            with self.assertRaises(RuntimeError):control.action('starpass-on')
            self.assertIn({'starpass_enabled':0,'enabled':1},events)
            run.assert_any_call(['/etc/init.d/portalproxy','start'])

class ManualOpenClash(unittest.TestCase):
    def test_render_keeps_rules_but_disables_network_takeover(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.yaml';target=Path(directory)/'manual.json'
            original={'tun':{'enable':True},'redir-port':7892,'tproxy-port':7895,'allow-lan':True,
                'rules':['MATCH,DIRECT'],'proxy-groups':[],'proxies':[],'profile':{'note':'fixture\nmultiline'},'dns':{'enable':True,'enhanced-mode':'fake-ip'}}
            source.write_text(json.dumps(original))
            subprocess.run(['/usr/bin/ruby',str(ROOT/'gateway/openclash_prepare.rb'),str(source),str(target),
                '7890','9090','192.168.50.1','192.168.50.2'],input=b'fixture-secret',check=True,capture_output=True)
            parsed=subprocess.check_output(['/usr/bin/ruby','-ryaml','-rjson','-e','puts JSON.generate(YAML.safe_load(File.read(ARGV[0]), aliases: true))',str(target)],text=True)
            result=json.loads(parsed)
            self.assertEqual(result['profile'],original['profile'])
            self.assertFalse(result['tun']['enable']);self.assertEqual(result['redir-port'],0)
            self.assertEqual(result['tproxy-port'],0);self.assertFalse(result['allow-lan'])
            self.assertEqual(result['rules'],original['rules'])
            self.assertEqual(json.loads(source.read_text()),original)
            self.assertEqual(result['dns']['enhanced-mode'],'redir-host')

if __name__=='__main__':unittest.main()
