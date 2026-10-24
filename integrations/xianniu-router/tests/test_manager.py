import asyncio
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from xianniu_router.auth_api import authenticate,authorization_code
from xianniu_router.auth_web import OfficialHTTP,AuthenticationRedirectError,parse_qr_page,create_qr
from xianniu_router.manager import Manager,atomic_json,PART_SIZE
from xianniu_router.rpc import METHODS
from xianniu_router.control import APIError


class OfficialLogin(unittest.TestCase):
    def test_qr_entry_keeps_official_callback_cookie_on_same_host(self):
        page=b'''<img src="/connect/qrcode/fixture_uuid_123"/>
        var t="https://webapi.xianniu.com/auth/weixinweb/callback?auth_key=fixture";
        t+="code="+wx_code+"&state=fixture_state";'''
        image=b'\x89PNG\r\n\x1a\nfixture'
        with patch('xianniu_router.auth_web.OfficialHTTP') as factory:
            client=factory.return_value;client.cookies=[]
            client.request.side_effect=[(page,'text/html','unused'),(image,'image/png','unused')]
            state,_=create_qr('192.168.31.1')
            self.assertTrue(client.request.call_args_list[0].args[0].startswith('https://webapi.xianniu.com/'))
            self.assertTrue(state['callback'].startswith('https://webapi.xianniu.com/'))
    def test_rpcd_integer_types_are_numeric_signatures(self):
        for method,fields in METHODS.items():
            for name,kind in fields.items():
                if name in ('game_id','area_id','line_id','part'):self.assertEqual(kind,32)
    def test_official_qr_callback_and_state_are_preserved(self):
        page=b'''<img src="/connect/qrcode/fixture_uuid_123"/>
        var usenewdomain = '1' * 1;
        var t="https://webapi.xianniu.com/auth/weixinweb/callback?auth_key=fixture";
        t+="code="+wx_code+"&state=fixture_state";'''
        state=parse_qr_page(page)
        self.assertEqual(state['uuid'],'fixture_uuid_123')
        self.assertEqual(state['state'],'fixture_state')
        self.assertEqual(state['poll_host'],'lp.open.weixin.qq.com')
        self.assertIn('auth_key=fixture',state['callback'])

    def test_redirect_rejects_nonofficial_and_plaintext_before_network(self):
        client=OfficialHTTP('192.168.31.1')
        for url in ('http://api1.xianniu.com/','https://attacker.example/auth','https://api1.xianniu.com:444/auth'):
            with self.assertRaises(AuthenticationRedirectError):client.request(url)

    def test_one_time_code_accepted_only_from_official_account_page(self):
        self.assertEqual(authorization_code({'final_url':'https://user.xianniu.com/auth2.html?code=fixture-code'}),'fixture-code')
        for url in ('https://other.example/auth2.html?code=fixture','https://user.xianniu.com/auth2.html'):
            with self.assertRaises(ValueError):authorization_code({'final_url':url})

    def test_password_md5_known_vector_and_no_plaintext_request(self):
        with patch('xianniu_router.auth_api.server_datetime',return_value='2026-10-24 12:00:00'), \
             patch('xianniu_router.auth_api.call_api',return_value={'access_token':'fixture-token'}) as call:
            authenticate({'hardware':'fixture-own-device'},'password',{'mobile':'13800000000','password':'abc'})
            config,path,request=call.call_args.args
            self.assertEqual(path,'/client/auth/login')
            self.assertEqual(request['password'],'900150983cd24fb0d6963f7d28e17f72')
            self.assertNotIn('abc',json.dumps(request))
            self.assertEqual(request['hardware'],'fixture-own-device')


class PrivateManager(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.root=Path(self.directory.name)
        self.private=self.root/'private'
        self.catalog=self.root/'catalog.json'
        self.catalog.write_text(json.dumps([{'id':797,'title':'PS5 港服','areas':[{'id':933,'title':'全区'}]}]))
        self.status=self.root/'runtime.json'
        self.status.write_text('{"running":false}')
        self.manager=Manager(self.private,self.catalog,self.status)
        self.config={'hardware':'fixture-own-device','account':{'access_token':'OLD-SECRET'},
                     'auth':{'u':'OLD-USER','key':'OLD-KEY'},'game_id':797,'profile':{'area_id':933,'line_id':122}}
        atomic_json(self.manager.path,self.config)

    def tearDown(self):self.directory.cleanup()

    def test_status_never_exposes_account_or_line_credentials(self):
        public=json.dumps(self.manager.status())
        for secret in ('OLD-SECRET','OLD-USER','OLD-KEY','fixture-own-device'):
            self.assertNotIn(secret,public)

    def test_login_status_distinguishes_imported_official_expired_and_logged_out(self):
        self.assertEqual(self.manager.status()['login_state'],'saved_unverified')
        config=self.manager.config();config['login_info']={'method':'wechat','at':123}
        atomic_json(self.manager.path,config)
        self.assertEqual(self.manager.status()['login_state'],'authenticated')
        atomic_json(self.private/'member.json',{'login_required':True})
        self.assertEqual(self.manager.status()['login_state'],'login_required')
        (self.private/'member.json').unlink();config['account']={};atomic_json(self.manager.path,config)
        self.assertEqual(self.manager.status()['login_state'],'logged_out')

    def test_member_rejection_updates_visible_login_status_without_exposing_token(self):
        with patch('xianniu_router.manager.call_api',side_effect=APIError(400011)):
            with self.assertRaises(APIError):self.manager.member()
        public=self.manager.status()
        self.assertTrue(public['login_required'])
        self.assertEqual(public['login_state'],'login_required')
        self.assertNotIn('OLD-SECRET',json.dumps(public))

    def test_account_switch_stops_old_session_before_atomic_save(self):
        self.status.write_text('{"running":true}')
        observed=[]
        def stop(action):observed.append((action,self.manager.config()['account']['access_token']))
        with patch.object(self.manager,'service',side_effect=stop):
            result=self.manager.accept_login({'access_token':'NEW-SECRET','nickname':'test'},'wechat')
        self.assertEqual(observed,[('stop','OLD-SECRET')])
        self.assertTrue(result['logged_in'])
        self.assertEqual(self.manager.config()['account']['access_token'],'NEW-SECRET')
        self.assertNotIn('NEW-SECRET',json.dumps(result))
        if os.name=='posix':self.assertEqual(self.manager.path.stat().st_mode&0o777,0o600)

    def test_pending_login_ids_cannot_escape_private_directory(self):
        for identity in ('../session','x'*32,'0'*31,'0'*33):
            with self.assertRaises(ValueError):self.manager.qr_paths(identity)

    def test_qr_image_chunks_reassemble_without_public_image_file(self):
        data=b'\x89PNG\r\n\x1a\n'+b'fixture'*10000
        identity='a'*32
        _,path=self.manager.qr_paths(identity)
        path.write_bytes(data)
        chunks=[self.manager.wechat_image(identity,i)['chunk'] for i in range((len(data)+PART_SIZE-1)//PART_SIZE)]
        self.assertEqual(base64.b64decode(''.join(chunks)),data)
        with self.assertRaises(ValueError):self.manager.wechat_image(identity,-1)

    def test_running_session_rejects_unannounced_profile_switch(self):
        self.status.write_text('{"running":true}')
        with self.assertRaises(ValueError):self.manager.select(797,933,122)

    def test_line_list_does_not_expose_backend_node_fields(self):
        rows=[{'line_id':122,'line_title':'香港','area_ids':'933,934','speed_ip':'PRIVATE-NODE',
               'line_token':'PRIVATE-TOKEN','is_exclusive':0},
              {'line_id':999,'line_title':'其他区','area_ids':'999'}]
        with patch('xianniu_router.manager.call_api',return_value=rows):result=self.manager.lines(797,933)
        self.assertEqual(result['lines'],[{'id':122,'title':'香港','exclusive':False}])
        self.assertEqual(len(result['all_lines']),2)
        self.assertFalse(result['all_lines'][1]['compatible'])
        self.assertNotIn('PRIVATE',json.dumps(result))

    def test_authorized_callback_is_not_consumed_a_second_time(self):
        identity='b'*32
        path,_=self.manager.qr_paths(identity)
        atomic_json(path,{'status':'authorized'})
        atomic_json(self.private/('result-'+identity+'.json'),
                    {'final_url':'https://user.xianniu.com/auth2.html?code=fixture-code'})
        with patch('xianniu_router.manager.poll_qr',side_effect=AssertionError('Must not repeat OAuth callback')), \
             patch('xianniu_router.manager.authenticate',return_value={'access_token':'NEW-SECRET'}) as login, \
             patch.object(self.manager,'service'):
            self.assertEqual(self.manager.wechat_poll(identity)['status'],'complete')
            self.assertEqual(self.manager.wechat_poll(identity)['status'],'complete')
            self.assertEqual(login.call_count,1)

    def test_refresh_qr_is_not_blocked_by_account_or_old_poll_lock(self):
        with patch.object(self.manager,'lock',side_effect=BlockingIOError('account busy')), \
             patch('xianniu_router.manager.create_qr',return_value=({'expires_at':123},b'\x89PNGfixture')):
            result=self.manager.wechat_create()
        self.assertEqual(result['parts'],1)
        self.assertEqual(len(list(self.private.glob('wechat-*.json'))),1)

    def test_waiting_poll_does_not_take_account_lock_and_authorized_retry_keeps_callback(self):
        identity='c'*32;path,_=self.manager.qr_paths(identity)
        atomic_json(path,{'status':'waiting'})
        @contextmanager
        def busy(name='manager.lock'):
            if name=='manager.lock':raise BlockingIOError('account operation busy')
            yield
        with patch.object(self.manager,'lock',side_effect=busy), \
             patch('xianniu_router.manager.poll_qr',return_value={'status':'waiting'}):
            self.assertEqual(self.manager.wechat_poll(identity)['status'],'waiting')
        atomic_json(path,{'status':'authorized'})
        atomic_json(self.private/('result-'+identity+'.json'),
                    {'final_url':'https://threelogin.xianniu.com/pc/auth2.html?code=fixture-code'})
        with patch.object(self.manager,'lock',side_effect=busy), \
             patch('xianniu_router.manager.poll_qr',side_effect=AssertionError('Must not consume twice')):
            with self.assertRaises(BlockingIOError):self.manager.wechat_poll(identity)
        self.assertEqual(json.loads(path.read_text())['status'],'authorized')
