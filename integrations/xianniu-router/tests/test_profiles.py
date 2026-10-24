import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock

from xianniu_router.auth_api import authenticate,authorization_code,restore_session
from xianniu_router.auth_web import OfficialHTTP
from xianniu_router.devices import discover
from xianniu_router.http_proxy import steam_store_host,RouterCore
from xianniu_router.manager import Manager,atomic_json
from xianniu_router.runtime import Service


class Profiles(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.root=Path(self.directory.name)
        self.catalog=self.root/'catalog.json'
        self.catalog.write_text(json.dumps([
            {'id':797,'title':'主机 PS5/XBOX 通用－港服','keywords':'ps5,港服','platform':'console','areas':[{'id':933,'title':'全区'}]},
            {'id':80,'title':'暗黑破坏神4','keywords':'暗黑4,Diablo IV','platform':'pc','areas':[{'id':10,'title':'亚洲'}]},
            {'id':81,'title':'Switch 通用','platform':'switch','areas':[{'id':11,'title':'全区'}]}]),encoding='utf-8')
        self.runtime=self.root/'runtime.json';self.runtime.write_text('{"running":false}')
        self.manager=Manager(self.root/'private',self.catalog,self.runtime)
        atomic_json(self.manager.path,{'hardware':'fixture-device','account':{'access_token':'OLD-SECRET'},
                    'game_id':797,'profile':{'area_id':933,'line_id':122},'devices':['192.168.31.112']})
        self.inventory={'devices':[{'ip':'192.168.31.112','name':'PS5 Pro','mac':'02:00:00:00:00:01'},
                                   {'ip':'192.168.31.233','name':'PC','mac':''}],
                        'host':'192.168.31.222','local':['192.168.31.222'],'port':10082}

    def tearDown(self):self.directory.cleanup()

    def test_catalog_alias_fuzzy_categories_paging_and_recent(self):
        self.assertEqual(self.manager.catalog('ps5港服')['games'][0]['id'],797)
        self.assertEqual(self.manager.catalog('暗黑4')['games'][0]['id'],80)
        self.assertEqual(self.manager.catalog('diablo')['games'][0]['id'],80)
        self.assertEqual(self.manager.catalog('',platform='switch')['total'],1)
        first=self.manager.catalog('',offset=0,limit=1)
        second=self.manager.catalog('',offset=1,limit=1)
        self.assertEqual(first['total'],3);self.assertNotEqual(first['games'],second['games'])
        self.assertEqual(self.manager.catalog('',platform='recent')['total'],0)
        atomic_json(self.manager.private/'preferences.json',{'recent':[80]})
        self.assertEqual(self.manager.catalog('',platform='recent')['games'][0]['id'],80)
        with self.assertRaises(ValueError):self.manager.catalog('',limit=10000)

    def test_launch_saves_independent_presets_and_restricts_active_source(self):
        actions=[];commands=[]
        def service(action):
            actions.append(action)
            if action=='stop':self.runtime.write_text('{"running":false,"session_stop_ok":true}')
        def command(args,**kwargs):commands.append(args);return Mock(returncode=0)
        with patch('xianniu_router.devices.discover',return_value=self.inventory), \
             patch.object(self.manager,'prepare_member',return_value=False), \
             patch.object(self.manager,'lines',return_value={'lines':[{'id':122}]}), \
             patch.object(self.manager,'service',side_effect=service), \
             patch('xianniu_router.manager.subprocess.run',side_effect=command):
            self.manager.launch('192.168.31.112',797,933,122)
            self.runtime.write_text('{"running":true}')
            self.manager.launch('192.168.31.233',80,10,122)
        self.assertEqual(self.manager.config()['devices'],['192.168.31.233'])
        preferences=self.manager.preferences()
        self.assertEqual(preferences['devices']['192.168.31.112']['game_id'],797)
        self.assertEqual(preferences['devices']['192.168.31.233']['game_id'],80)
        self.assertEqual(actions,['stop','enable','start']*2)
        self.assertTrue(all('xianniu-router' in ' '.join(cmd) for cmd in commands))
        self.assertNotIn('OLD-SECRET',json.dumps(preferences))

    def test_start_preparation_recovers_only_officially_paused_membership(self):
        with patch.object(self.manager,'_member',side_effect=[{'pause_state':0},{'pause_state':1}]), \
             patch('xianniu_router.manager.call_api',return_value={}) as request:
            self.assertTrue(self.manager.prepare_member())
            self.assertEqual(request.call_args.args[1],'/client/member/recovery')
            self.assertEqual(request.call_args.args[2],{'access_token':'OLD-SECRET','sender':0})
        with patch.object(self.manager,'_member',return_value={'pause_state':1}), \
             patch('xianniu_router.manager.call_api') as request:
            self.assertFalse(self.manager.prepare_member());request.assert_not_called()

    def test_unrecognized_device_or_invalid_profile_does_not_stop_running_session(self):
        self.runtime.write_text('{"running":true}')
        with patch('xianniu_router.devices.discover',return_value=self.inventory),patch.object(self.manager,'service') as service:
            for device,game,area in [('8.8.8.8',797,933),('192.168.31.112',9999,933),('192.168.31.112',797,9999)]:
                with self.assertRaises(ValueError):self.manager.launch(device,game,area,122)
            service.assert_not_called()

    def test_failed_old_stop_does_not_start_or_replace_profile(self):
        self.runtime.write_text('{"running":true}')
        def service(action):self.runtime.write_text('{"running":false,"session_stop_ok":false}')
        with patch('xianniu_router.devices.discover',return_value=self.inventory), \
             patch.object(self.manager,'lines',return_value={'lines':[{'id':122}]}), \
             patch.object(self.manager,'service',side_effect=service) as call:
            with self.assertRaises(ValueError):self.manager.launch('192.168.31.233',80,10,122)
            self.assertEqual(call.call_count,1)
        self.assertEqual(self.manager.config()['game_id'],797)

    def test_pause_stops_owned_service_before_official_suspend_and_projects_only_member_fields(self):
        order=[]
        def service(action):order.append(action)
        def request(config,path,value):
            order.append(path)
            if path.endswith('/suspend'):
                self.assertEqual(value,{'access_token':'OLD-SECRET','sender':0});return {}
            return {'pause_state':0,'package_title':'测试套餐','access_token':'DO-NOT-EXPOSE','mobile':'PRIVATE'}
        with patch.object(self.manager,'service',side_effect=service),patch.object(self.manager,'set_enabled'), \
             patch('xianniu_router.manager.call_api',side_effect=request):
            result=self.manager.member_pause()
        self.assertEqual(order,['stop','disable','/client/member/suspend','/client/member/details'])
        self.assertEqual(result['pause_state'],0)
        self.assertNotIn('PRIVATE',json.dumps(result));self.assertNotIn('DO-NOT-EXPOSE',json.dumps(self.manager.status()))

    def test_remember_login_uses_token_field_and_private_atomic_refresh(self):
        config=self.manager.config();config['_config_path']=str(self.manager.path)
        with patch('xianniu_router.auth_api.server_datetime',return_value='2026-10-24 12:00:00'), \
             patch('xianniu_router.auth_api.call_api',return_value={'access_token':'NEW-SECRET'}) as call:
            restore_session(config)
        path=call.call_args.args[1];body=call.call_args.args[2]
        self.assertEqual(path,'/client/auth/login_token')
        self.assertEqual(body['token'],'OLD-SECRET');self.assertNotIn('access_token',body)
        self.assertEqual(config['account']['access_token'],'NEW-SECRET')
        self.assertEqual(self.manager.config()['account']['access_token'],'NEW-SECRET')

    def test_remember_login_cannot_overwrite_newer_account(self):
        config=self.manager.config();config['_config_path']=str(self.manager.path)
        current=self.manager.config();current['account']['access_token']='OTHER-OWNER';atomic_json(self.manager.path,current)
        with patch('xianniu_router.auth_api.authenticate',return_value={'access_token':'NEW-SECRET'}):
            with self.assertRaises(RuntimeError):restore_session(config)
        self.assertEqual(self.manager.config()['account']['access_token'],'OTHER-OWNER')


class Discovery(unittest.TestCase):
    def test_read_only_discovery_excludes_router_self_failed_and_non_lan(self):
        def command(args):
            if args[0]=='uci':return 'br-lan' if args[-1].endswith('.interface') else ''
            if 'address' in args:return json.dumps([{'addr_info':[{'local':'192.168.31.222','prefixlen':24}]}])
            if 'route' in args:return '[{"gateway":"192.168.31.1"}]'
            return json.dumps([{'dst':ip,'lladdr':mac,'state':['STALE']} for ip,mac in [
                ('192.168.31.112','02:00:00:00:00:01'),('192.168.31.222','00'),
                ('192.168.31.1','00'),('10.1.1.1','00'),('192.168.31.88','')]])
        with patch('xianniu_router.devices.read_command',side_effect=command),patch('xianniu_router.devices.Path.read_text',side_effect=FileNotFoundError):
            result=discover({}, {'devices':{'192.168.31.112':{'name':'PS5 Pro'}}})
        self.assertEqual([r['ip'] for r in result['devices']],['192.168.31.112'])
        self.assertEqual(result['devices'][0]['name'],'PS5 Pro')
        self.assertEqual(result['host'],'192.168.31.222')


class CallbackAndRouting(unittest.TestCase):
    def test_official_three_login_callback_is_captured_before_landing_get(self):
        connection=Mock();response=connection.getresponse.return_value
        response.status=302;response.read.return_value=b'';response.getheaders.return_value=[]
        response.getheader.side_effect=lambda name,*args:'https://threelogin.xianniu.com/pc/auth2.html?code=fixture-code' if name=='Location' else 'text/html'
        with patch('xianniu_router.auth_web.resolve_real',return_value='8.8.8.8'), \
             patch('xianniu_router.auth_web.socket.create_connection'),patch('xianniu_router.auth_web.ssl.create_default_context'), \
             patch('xianniu_router.auth_web.http.client.HTTPSConnection',return_value=connection) as factory:
            result=OfficialHTTP('192.168.31.1').request('https://webapi.xianniu.com/auth/weixinweb/callback?code=fixture',stop_at_login=True)
        self.assertEqual(factory.call_count,1)
        self.assertEqual(authorization_code({'final_url':result[2]}),'fixture-code')
        with self.assertRaises(ValueError):authorization_code({'final_url':'https://threelogin.xianniu.com:444/pc/auth2.html?code=fixture'})

    def test_steam_store_exclusion_does_not_bypass_game_or_community_domains(self):
        for host in ('store.steampowered.com','STORE.STEAMPOWERED.COM.','checkout.steampowered.com','store.akamai.steamstatic.com'):
            self.assertTrue(steam_store_host(host))
        for host in ('steamcommunity.com','api.steampowered.com','store.steampowered.com.attacker.example','cdn.akamai.steamstatic.com','notstore.steamstatic.com'):
            self.assertFalse(steam_store_host(host))


class DirectStore(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_attempts_saved_login_only_once_per_run(self):
        service=Service({'auth':{}})
        with patch('xianniu_router.auth_api.restore_session',return_value={}) as restore:
            await service.restore_login_once()
            with self.assertRaises(RuntimeError):await service.restore_login_once()
            self.assertEqual(restore.call_count,1)

    async def test_direct_store_uses_raw_connection_but_still_rejects_private_dns(self):
        service=Service({'dns_server':'192.168.31.1','auth':{}});core=RouterCore(service)
        service.refresh_failures=3
        await core.acquire_for_request('store.steampowered.com',443)
        with patch('xianniu_router.http_proxy.resolve_real',return_value='8.8.8.8'), \
             patch('xianniu_router.http_proxy.asyncio.open_connection',return_value=('reader','writer')) as connection:
            self.assertEqual(await core.open_connection('store.steampowered.com',443),('reader','writer'))
            connection.assert_awaited_once_with('8.8.8.8',443)
        with patch('xianniu_router.http_proxy.resolve_real',return_value='192.168.31.1'):
            with self.assertRaises(ValueError):await core.open_connection('store.steampowered.com',443)
