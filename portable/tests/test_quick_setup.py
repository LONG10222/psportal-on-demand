import ipaddress
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from portalproxy.setup import parse_interfaces, available_port
from portalproxy.desktop import DesktopApp
from test_core import port


class NetworkSetupTests(unittest.TestCase):
    def test_only_physical_private_interface_and_current_subnet_are_selected(self):
        data = '''utun3: flags=1
    inet 10.9.0.2 netmask 0xffffff00
en0: flags=1
    inet 192.168.3.8 netmask 0xffffff00
en1: flags=1
    inet 10.1.0.2 netmask 0xfffffff0
'''
        info = parse_interfaces(data, 'en1')
        self.assertEqual(info['host'], '10.1.0.2')
        self.assertEqual(info['subnet'], '10.1.0.0/28')
        self.assertNotIn(info['host'], info['clients'])
        self.assertTrue(all(ipaddress.ip_address(ip) in ipaddress.ip_network(info['subnet']) for ip in info['clients']))
        self.assertLessEqual(len(info['clients']), 254)
        with self.assertRaises(ValueError):
            parse_interfaces('utun0: flags=1\n    inet 10.0.0.1 netmask 0xffffff00')
        with self.assertRaises(ValueError):
            parse_interfaces('en0: flags=1\n    inet 10.0.0.1 netmask 0xff000000')

    def test_port_is_kept_until_occupied_and_alternative_is_available(self):
        preferred = port()
        self.assertEqual(available_port('127.0.0.1', preferred), preferred)
        with socket.socket() as owner:
            owner.bind(('127.0.0.1', preferred)); owner.listen()
            alternative = available_port('127.0.0.1', preferred, (10082, 10090))
            self.assertNotIn(alternative, (preferred, 10082, 10090))
            with socket.socket() as check:
                check.bind(('127.0.0.1', alternative))


@unittest.skipUnless(os.environ.get('PSPORTAL_TK_TEST') == '1', 'Real Tk quick setup opt-in')
class QuickSetupWindowTests(unittest.TestCase):
    def test_one_click_imports_configures_starts_and_shows_wifi_guide(self):
        import tkinter as tk
        root = tk.Tk(); app = None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                ports = set()
                while len(ports) < 3: ports.add(port())
                listen, backend, api = sorted(ports)
                path = folder / 'host.json'
                path.write_text(json.dumps(dict(core_path=sys.executable, listen_port=listen,
                    backend_port=backend, api_port=api, subscription_url='https://fixture.example/opaque-token')))
                app = DesktopApp(root, path)
                def download(url, target):
                    target.write_text('proxies: []\n')
                    return {'upload':1000000000,'download':2000000000,'total':10000000000,'expire':2000000000}
                with (patch('portalproxy.setup.discover_lan', return_value=dict(host='127.0.0.1',clients=['127.0.0.1'],subnet='loopback-fixture')),
                      patch('portalproxy.core.download_subscription', side_effect=download)):
                    app.view.quick_button.invoke()
                    end = time.monotonic()+15
                    while time.monotonic()<end and not app.backend.ready:
                        root.update(); time.sleep(.02)
                    self.assertTrue(app.backend.ready, app.log_widget.get('1.0','end'))
                    self.assertEqual(app.vars['listen_host'].get(), '127.0.0.1')
                    self.assertEqual(app.vars['listen_port'].get(), str(listen))
                    self.assertEqual(app.view.page, 'LAN sharing')
                    self.assertFalse(app.view.advanced)
                    self.assertIn('127.0.0.1', app.view.guide_var.get())
                    self.assertIn('6.52 GiB', app.view.subscription_var.get())
                    app.set_language('zh')
                    self.assertIn('剩余', app.view.subscription_var.get())
                    self.assertIn('6.52 GiB', app.view.subscription_var.get())
                    self.assertNotIn('opaque-token', app.log_widget.get('1.0', 'end'))
                app.stop()
                end=time.monotonic()+15
                while time.monotonic()<end and app.backend.process is not None:
                    root.update(); time.sleep(.02)
                self.assertIsNone(app.backend.process)
                app.close()
        finally:
            if app:
                app.backend.stop()
                if app.backend.process: app.backend.process.wait(timeout=15)
            for timer in root.tk.splitlist(root.tk.call('after','info')):
                root.tk.call('after','cancel',timer)
            try: root.destroy()
            except tk.TclError: pass
