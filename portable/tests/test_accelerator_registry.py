import unittest
from portalproxy.accelerator_registry import discover


class RegistryTests(unittest.TestCase):
    def test_installation_and_owned_process_are_discovered_without_proxy_claims(self):
        data={'installations':[{'display_name':'网易UU加速器','location':r'C:\Apps\UU','icon':r'"C:\Apps\UU\UU.exe",0'}],
              'processes':[{'name':'UU.exe','pid':234,'path':r'C:\Apps\UU\UU.exe'}]}
        rows={r['key']:r for r in discover(data,exists=lambda p:p.startswith('C:\\Apps\\UU'))}
        self.assertTrue(rows['uu']['installed']);self.assertTrue(rows['uu']['running'])
        self.assertFalse(rows['uu']['capabilities']['native_tcp_udp'])
        self.assertFalse(rows['uu']['capabilities']['public_catalog_reader'])
        self.assertFalse(rows['uu']['capabilities']['whole_lan_game_udp_verified'])

    def test_similarly_named_unowned_process_does_not_become_an_official_launcher(self):
        rows={r['key']:r for r in discover({'installations':[],'processes':[{'name':'UU.exe','pid':234,'path':r'C:\Unknown\UU.exe'}]},exists=lambda p:False)}
        self.assertFalse(rows['uu']['installed']);self.assertEqual(rows['uu']['executables'],[])

    def test_elevated_process_without_path_is_only_attributed_to_known_installation(self):
        rows={r['key']:r for r in discover({'installations':[{'display_name':'雷神加速器','location':r'C:\Apps\Leigod','icon':''}],
          'processes':[{'name':'Leigod.exe','pid':777,'path':''}]},exists=lambda p:p==r'C:\Apps\Leigod')}
        self.assertTrue(rows['leigod']['running']);self.assertFalse(rows['leigod']['capabilities']['built_in'])

    def test_inventory_failure_does_not_mark_a_provider_ready(self):
        rows=discover({'installations':[],'processes':[],'error':'inventory_unavailable'},exists=lambda p:False)
        self.assertTrue(all(not r['installed'] and not r['running'] for r in rows))

    def test_display_icon_arguments_are_not_executed_or_accepted(self):
        rows={r['key']:r for r in discover({'installations':[{'display_name':'雷神加速器','location':'','icon':'"C:\\x.exe"; calc.exe'}],'processes':[]},exists=lambda p:False)}
        self.assertEqual(rows['leigod']['executables'],[])


if __name__=='__main__':unittest.main()
