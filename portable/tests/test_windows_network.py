import json,unittest
from portalproxy.windows_network import parse_hotspot,selected_network

def inventory(state='On',description='Microsoft Wi-Fi Direct Virtual Adapter',address='192.168.137.1'):
    return {'state':state,'adapters':[{'index':21,'name':'hotspot','up':True,'virtual':True,'description':description}],
        'addresses':[{'index':21,'address':address,'prefix':24,'preferred':True}]}

class HotspotTests(unittest.TestCase):
    def test_confirmed_on_hotspot_uses_its_real_address_and_subnet(self):
        result=parse_hotspot(json.dumps(inventory(address='192.168.155.1')))
        self.assertEqual(result['network']['host'],'192.168.155.1')
        self.assertEqual(result['network']['subnet'],'192.168.155.0/24')
        self.assertNotIn('192.168.155.1',result['network']['clients'])

    def test_off_and_vpn_do_not_become_a_hotspot_based_on_address(self):
        self.assertIsNone(parse_hotspot(json.dumps(inventory(state='Off')))['network'])
        self.assertIsNone(parse_hotspot(json.dumps(inventory(description='VPN adapter')))['network'])
        self.assertIsNone(parse_hotspot(json.dumps(inventory(address='8.8.8.8')))['network'])
        with self.assertRaises(ValueError):selected_network({'hotspot':{'network':None}},'hotspot')

    def test_ambiguous_active_adapters_are_not_guessed(self):
        data=inventory();data['adapters'].append(dict(data['adapters'][0],index=22));data['addresses'].append(dict(data['addresses'][0],index=22,address='192.168.138.1'))
        self.assertEqual(parse_hotspot(json.dumps(data))['state'],'ambiguous')
