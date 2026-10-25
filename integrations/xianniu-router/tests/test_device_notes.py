import json
import unittest
from unittest.mock import patch
import test_profiles as profile_tests
from xianniu_router.devices import discover,device_preferences,mac_key


class DeviceNotes(unittest.TestCase):
    setUp = profile_tests.Profiles.setUp
    tearDown = profile_tests.Profiles.tearDown
    def test_mac_key_validation(self):
        self.assertEqual(mac_key('02:AB:00:00:00:01'),'02:ab:00:00:00:01')
        for value in ['bad','00:00:00:00:00:00','ff:ff:ff:ff:ff:ff','01:00:00:00:00:01',None]:
            self.assertEqual(mac_key(value),'')

    def test_legacy_migrates_known_mac_without_keeping_ip_as_key(self):
        value=device_preferences({'devices':{'192.168.50.30':{'mac':'02:AB:00:00:00:01','game_id':797}}})
        self.assertEqual(list(value['devices']),['02:ab:00:00:00:01'])
        self.assertEqual(value['devices']['02:ab:00:00:00:01']['last_ip'],'192.168.50.30')

    def test_note_saved_by_mac_and_profile_preserved(self):
        from xianniu_router.manager import atomic_json
        atomic_json(self.manager.private/'preferences.json',{'devices':{'02:00:00:00:00:01':{'game_id':797}}})
        with patch('xianniu_router.devices.discover',return_value=self.inventory):
            self.manager.set_device_note('02:00:00:00:00:01','PS5')
            with self.assertRaises(ValueError):self.manager.set_device_note('02:00:00:00:00:01','bad\nname')
        saved=self.manager.preferences()['devices']['02:00:00:00:00:01']
        self.assertEqual(saved['note'],'PS5');self.assertEqual(saved['game_id'],797)
        self.assertEqual(saved['last_ip'],'192.168.31.112')

    def test_ip_change_follows_mac_and_old_ip_does_not_inherit_note(self):
        prefs={'devices':{'02:00:00:00:00:01':{'last_ip':'192.168.50.30','note':'PS5','game_id':797}}}
        def command(args):
            if args[:3]==['uci','-q','get']:return ''
            if 'address' in args:return json.dumps([{'addr_info':[{'local':'192.168.50.2','prefixlen':24}]}])
            if 'neigh' in args:return json.dumps([
                {'dst':'192.168.50.30','lladdr':'02:00:00:00:00:02','state':['REACHABLE']},
                {'dst':'192.168.50.31','lladdr':'02:00:00:00:00:01','state':['REACHABLE']}])
            return '[]'
        with patch('xianniu_router.devices.read_command',side_effect=command),patch('xianniu_router.devices.Path.read_text',side_effect=FileNotFoundError):
            rows={r['ip']:r for r in discover({},prefs)['devices']}
        self.assertEqual(rows['192.168.50.31']['name'],'PS5')
        self.assertEqual(rows['192.168.50.31']['preset']['game_id'],797)
        self.assertEqual(rows['192.168.50.30']['note'],'')
