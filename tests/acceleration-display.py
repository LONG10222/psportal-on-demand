"""Local acceleration evidence is fresh, bounded, read-only and sanitized."""
import json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'gateway'),str(ROOT/'integrations/xianniu-router/src')]
import monitor
class Evidence(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
  data={'NATIVE_CONFIG':{'account':{'access_token':'private-token'},'auth':{'password':'private-password'},'subscription':'private-subscription','active_device':'192.168.50.10','active_device_mac':'aa:bb:cc:dd:ee:ff','game_id':1,'profile':{'area_id':2}},'NATIVE_STATUS':{'running':True,'refresh_ok':True,'game_id':1,'profile':{'area_id':2},'node':{'host':'private-node','port':9000},'counters':{'sent':100,'received':300,'tcp_errors':2}},'NATIVE_PREFERENCES':{'devices':{'aa:bb:cc:dd:ee:ff':{'note':'Console'}}},'NATIVE_CATALOG':[{'id':1,'title':'Test Game','areas':[{'id':2,'title':'Test Area'}]}]}
  for key,value in data.items():
   p=self.base/key;p.write_text(json.dumps(value));patcher=patch.object(monitor,key,p);patcher.start();self.addCleanup(patcher.stop)
  self.mock=patch('monitor.subprocess.run',return_value=Mock(returncode=0,stdout=json.dumps({'xianniu-router':{'instances':{'main':{'running':True,'pid':123}}}}))).start();self.addCleanup(patch.stopall)
  proc=patch.object(monitor,'PROC',self.base/'proc');proc.start();self.addCleanup(proc.stop)
 def test_fresh_native_counts_and_selected_game_are_whitelisted(self):
  v=monitor.accelerator_snapshot();self.assertTrue(v['running']);self.assertTrue(v['fresh']);self.assertTrue(v['healthy']);self.assertEqual(v['session'],'123');self.assertEqual(v['counters'],{'sent':100,'received':300,'tcp_errors':2});self.assertEqual(v['game'],'Test Game');self.assertEqual(v['area'],'Test Area');self.assertEqual(v['device_name'],'Console')
  for secret in ('private-token','private-password','private-subscription','private-node','aa:bb:cc:dd:ee:ff'):self.assertNotIn(secret,json.dumps(v))
  self.mock.assert_called_once();self.assertEqual(self.mock.call_args.args[0][0],'ubus')
 def test_stale_file_cannot_claim_active_or_publish_counters(self):
  stamp=time.time()-60;os.utime(monitor.NATIVE_STATUS,(stamp,stamp));v=monitor.accelerator_snapshot();self.assertTrue(v['running']);self.assertFalse(v['fresh']);self.assertFalse(v['healthy']);self.assertEqual(v['counters'],{})
 def test_service_stopped_wins_over_old_running_file(self):
  self.mock.return_value.stdout='{}';v=monitor.accelerator_snapshot();self.assertFalse(v['running']);self.assertTrue(v['fresh']);self.assertEqual(v['counters'],{})
 def test_service_query_failure_is_unknown_not_success_or_off(self):
  self.mock.return_value.returncode=1;v=monitor.accelerator_snapshot();self.assertFalse(v['fresh']);self.assertFalse(v['healthy']);self.assertEqual(v['counters'],{})
 def test_future_status_missing_catalog_and_invalid_counters_are_safe(self):
  data=json.loads(monitor.NATIVE_STATUS.read_text());data['counters']={'sent':True,'received':-5,'tcp_connections':'9','tcp_errors':9007199254740992};monitor.NATIVE_STATUS.write_text(json.dumps(data));monitor.NATIVE_CATALOG.write_text('{}');v=monitor.accelerator_snapshot();self.assertEqual(v['counters'],{});self.assertEqual(v['game'],'')
  stamp=time.time()+60;os.utime(monitor.NATIVE_STATUS,(stamp,stamp));self.assertFalse(monitor.accelerator_snapshot()['fresh'])
if __name__=='__main__':unittest.main()
