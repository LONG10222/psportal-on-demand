import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xianniu_router.manager import Manager,atomic_json

class Billing(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();p=Path(self.tmp.name)
        self.catalog=p/'catalog.json';self.catalog.write_text(json.dumps([
            {'id':12,'is_free':True},{'id':797,'is_free':False},{'id':999}]))
        self.status=p/'status.json';self.status.write_text('{"running":true}')
        self.m=Manager(p/'private',self.catalog,self.status)
        atomic_json(self.m.path,{'game_id':12,'account':{'access_token':'fixture'}})
    def tearDown(self):self.tmp.cleanup()
    def test_free_never_resumes_account_time(self):
        with patch.object(self.m,'_member') as member,patch('xianniu_router.manager.call_api') as api:
            self.assertFalse(self.m.prepare_member(12));member.assert_not_called();api.assert_not_called()
    def test_unknown_rules_fail_before_account_api(self):
        with patch('xianniu_router.manager.call_api') as api:
            with self.assertRaises(ValueError):self.m.prepare_member(999)
            api.assert_not_called()
    def test_paid_target_checked_instead_of_previous_free_selection(self):
        with patch.object(self.m,'_member',side_effect=[{'pause_state':0},{'pause_state':1}]),patch('xianniu_router.manager.call_api') as api:
            self.assertTrue(self.m.prepare_member(797));self.assertEqual(api.call_args.args[1],'/client/member/recovery')
    def stopped(self,action):
        if action=='stop':self.status.write_text('{"running":false,"session_stop_ok":true}')
    def test_free_finish_stops_only_owned_service(self):
        with patch.object(self.m,'service',side_effect=self.stopped),patch.object(self.m,'set_enabled'),patch('xianniu_router.manager.call_api') as api:
            result=self.m.finish();self.assertFalse(result['time_paused']);api.assert_not_called()
    def test_paid_finish_confirms_stop_then_suspends(self):
        c=self.m.config();c['game_id']=797;atomic_json(self.m.path,c)
        with patch.object(self.m,'service',side_effect=self.stopped),patch.object(self.m,'set_enabled'),patch.object(self.m,'_member',return_value={'pause_state':0}),patch('xianniu_router.manager.call_api') as api:
            self.assertTrue(self.m.finish()['time_paused']);self.assertEqual(api.call_args.args[1],'/client/member/suspend')
    def test_unconfirmed_stop_never_suspends_account(self):
        with patch.object(self.m,'service'),patch.object(self.m,'set_enabled'),patch('xianniu_router.manager.call_api') as api:
            with self.assertRaises(ValueError):self.m.finish()
            api.assert_not_called()
    def test_already_stopped_never_changes_account_time(self):
        self.status.write_text('{"running":false}')
        c=self.m.config();c['game_id']=797;atomic_json(self.m.path,c)
        with patch.object(self.m,'service'),patch.object(self.m,'set_enabled'),patch('xianniu_router.manager.call_api') as api:
            self.m.finish();api.assert_not_called()
