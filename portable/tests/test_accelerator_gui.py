"""Opt-in real Tk checks for independent accelerator configuration."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

from portalproxy.desktop import DesktopApp, _write_config
from portalproxy.config import validate


@unittest.skipUnless(sys.platform == 'win32' and os.environ.get('PSPORTAL_TK_TEST') == '1',
                     'requires explicit Windows Tk verification')
class AcceleratorGuiTests(unittest.TestCase):
    def test_sources_mode_isolation_and_saved_state(self):
        import tkinter as tk
        with tempfile.TemporaryDirectory() as folder:
            root = tk.Tk()
            root.withdraw()
            try:
                path = Path(folder) / 'config.json'
                _write_config(path, dict(product_mode='mixed', listen_host='192.168.3.243',
                    allowed_clients=['192.168.3.50'], listen_port=10081, backend_port=10082,
                    api_port=10090, subscription_url='https://fixture.invalid/original'))
                app = DesktopApp(root, path)
                app.view.language = 'zh'
                app.view.refresh()
                root.update_idletasks()
                original = app.vars['subscription_url'].get()
                self.assertIn('accelerator', app.view.product_mode_buttons)
                app.set_product_mode('accelerator')
                root.update_idletasks()
                self.assertEqual(app.vars['subscription_url'].get(), '')
                self.assertEqual(app.view.accelerator_card.winfo_manager(), 'grid')
                self.assertEqual(app.view.subscription_entry.winfo_manager(), '')
                self.assertEqual(app.view.profile_card.winfo_manager(), '')
                self.assertIsNone(app.backend.process)
                app.vars['listen_port'].set('10181')
                for transport in ('http', 'socks5'):
                    app.view.accelerator_source_var.set(transport)
                    app.view.accelerator_port_var.set('12345')
                    values = app.collect()
                    validate(values, path)
                    self.assertEqual(values['accelerator_proxy']['protocol'], transport)
                    self.assertNotIn('host_relay', values)
                    self.assertNotIn('existing_proxy_port', values)
                app.view.accelerator_source_var.set('host')
                self.assertEqual(app.collect()['host_relay'], 'steam')
                self.assertTrue(app.save())
                app.load()
                self.assertEqual(app.product_mode(), 'accelerator')
                app.set_product_mode('mixed')
                root.update_idletasks()
                self.assertEqual(app.vars['subscription_url'].get(), original)
                self.assertEqual(app.vars['listen_port'].get(), '10081')
                self.assertEqual(app.view.accelerator_card.winfo_manager(), '')
                self.assertEqual(app.view.profile_card.winfo_manager(), 'grid')
                app.set_product_mode('accelerator')
                self.assertEqual(app.vars['listen_port'].get(), '10181')
                self.assertIsNone(app.backend.process)
            finally:
                root.destroy()
