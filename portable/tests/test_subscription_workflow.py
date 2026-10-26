"""Real Tk subscription import/start UX using only a synthetic local download."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from portalproxy.desktop import DesktopApp


@unittest.skipUnless(os.environ.get('PSPORTAL_TK_TEST') == '1', 'Enable real Tk subscription workflow tests')
class SubscriptionWorkflowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.folder = tempfile.TemporaryDirectory(prefix='portal subscription workflow ')
        self.addCleanup(self.folder.cleanup)
        self.root = tk.Tk()
        self.path = Path(self.folder.name) / 'config.json'
        self.path.write_text(json.dumps(dict(core_path=sys.executable)), encoding='utf-8')
        with patch('portalproxy.existing_proxy.detect_system_proxy', return_value=None):
            self.app = DesktopApp(self.root, self.path)
        self.app._next_discovery = float('inf')  # These fixtures inject discovery results explicitly.
        self.app.set_language('zh')
        self.addCleanup(self.close_window)
        self.url = 'https://fixture.example/subscription?token=never-log-this'
        self.download = Mock(side_effect=self.seed)
        self.patch_fetch = patch('portalproxy.core.download_subscription', self.download)
        self.patch_fetch.start(); self.addCleanup(self.patch_fetch.stop)
        self.patch_clipboard = patch.object(self.root, 'clipboard_get', return_value=self.url)
        self.clipboard = self.patch_clipboard.start(); self.addCleanup(self.patch_clipboard.stop)
        self.root.update()

    def close_window(self):
        import tkinter as tk
        self.app.backend.stop()
        if self.app.backend.process:
            self.app.backend.process.wait(timeout=15)
            self.app.backend.poll()
        self.root.update_idletasks()
        self.root.update()
        for timer in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.tk.call('after', 'cancel', timer)
        try: self.root.destroy()
        except tk.TclError: pass

    @staticmethod
    def seed(url, destination):
        destination.write_text(json.dumps({'proxies': [
            dict(name='香港 🌏', type='http', server='127.0.0.1', port=65534)]}), encoding='utf-8')
        return {'upload': 1, 'download': 2, 'total': 100, 'expire': 2000000000}

    def wait_for_import(self):
        deadline = time.monotonic() + 10
        while self.app.importing and time.monotonic() < deadline:
            self.root.update(); time.sleep(.01)
        self.assertFalse(self.app.importing)
        self.root.update()

    def paste(self):
        self.app.view.paste_button.invoke()
        self.wait_for_import()

    def test_virtual_paste_replaces_field_saves_and_survives_reload_without_start(self):
        self.app.vars['subscription_url'].set('old text that must be replaced')
        with patch('portalproxy.setup.discover_lan') as discover:
            self.app.view.subscription_entry.event_generate('<<Paste>>')
            self.wait_for_import()
            self.assertEqual(self.app.vars['subscription_url'].get(), self.url)
            self.assertIsNone(self.app.backend.process)
            discover.assert_not_called()
        self.assertEqual(self.download.call_count, 1)
        self.assertFalse(self.app.dirty, 'A saved import alone must not require another Save action')
        snapshot = self.app.vars['subscription_file'].get()
        self.assertTrue(Path(snapshot).is_file())
        self.app.load()
        self.assertTrue(self.app.subscription_ready())
        self.assertEqual(self.app.view.language, 'zh')
        self.assertEqual(self.app.vars['subscription_url'].get(), self.url)
        self.assertEqual(self.app.view.subscription_info['total'], 100)
        self.paste()
        self.app.import_subscription()
        self.assertEqual(self.download.call_count, 1)
        self.assertEqual(self.app.vars['subscription_file'].get(), snapshot)
        self.assertFalse(self.app.dirty)

    def test_single_flight_explicit_refresh_and_failure_keep_previous_snapshot(self):
        entered, release = threading.Event(), threading.Event()
        def blocked(url, destination):
            entered.set()
            if not release.wait(10): raise TimeoutError()
            return self.seed(url, destination)
        self.download.side_effect = blocked
        try:
            self.app.paste_subscription()
            self.assertTrue(entered.wait(3))
            for _ in range(5):
                self.app.paste_subscription()
                self.app.import_subscription(force=True)
                self.app.quick_start()
            self.assertEqual(self.download.call_count, 1)
            self.assertIsNone(self.app.backend.process)
        finally:
            release.set()
        self.wait_for_import()
        self.download.side_effect = self.seed
        self.app.view.refresh_button.invoke(); self.wait_for_import()
        self.assertEqual(self.download.call_count, 2)
        snapshot = self.app.vars['subscription_file'].get()
        self.download.side_effect = OSError('secret fixture failure')
        with patch('tkinter.messagebox.showerror') as dialog:
            self.app.view.refresh_button.invoke(); self.wait_for_import()
        dialog.assert_not_called()
        self.assertTrue(self.app.subscription_ready())
        self.assertEqual(self.app.vars['subscription_file'].get(), snapshot)
        self.assertIn('之前', self.app.view.import_note_var.get())
        self.assertIsNone(self.app.backend.process)

    def test_edited_link_blocks_old_source_and_restoring_it_recovers_metadata(self):
        self.paste()
        self.app.vars['subscription_url'].set('https://fixture.example/different')
        self.assertFalse(self.app.subscription_ready())
        self.assertEqual(str(self.app.view.quick_button['state']), 'disabled')
        with patch.object(self.app.backend, 'start') as start, patch('portalproxy.setup.discover_lan') as discover:
            self.app.quick_start(); self.app.start()
        start.assert_not_called(); discover.assert_not_called()
        self.app.vars['subscription_url'].set(self.url)
        self.assertTrue(self.app.subscription_ready())
        self.assertEqual(self.app.view.subscription_info['total'], 100)
        self.assertEqual(self.download.call_count, 1)

    def test_import_keeps_unrelated_unsaved_fields_and_never_steals_navigation(self):
        other_core = Path(self.folder.name) / 'chosen core.exe'
        other_core.write_bytes(b'fixture; never executed')
        self.app.vars['core_path'].set(str(other_core))
        self.app.view.show('Devices')
        self.paste()
        self.assertEqual(self.app.view.page, 'Devices')
        self.assertEqual(self.app.vars['core_path'].get(), str(other_core))
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['core_path'], sys.executable)
        self.assertTrue(self.app.dirty)
        self.assertIsNone(self.app.backend.process)

    def test_invalid_clipboard_is_inline_and_missing_core_is_actionable(self):
        self.clipboard.return_value = 'not a subscription URL'
        with patch('tkinter.messagebox.showerror') as dialog:
            self.paste()
        dialog.assert_not_called(); self.download.assert_not_called()
        self.assertIn('HTTPS', self.app.view.import_note_var.get())
        self.clipboard.return_value = self.url
        self.paste()
        with patch('portalproxy.core_setup.can_install', return_value=True):
            self.app.vars['core_path'].set('')
            self.root.update()
        self.assertEqual(str(self.app.view.quick_button['state']), 'normal')
        self.assertFalse(self.app.view.core_setup_button.winfo_viewable())
        self.assertIn('Mihomo', self.app.view.core_note_var.get())

    def test_saved_source_from_an_old_link_cannot_bypass_start_guard(self):
        self.paste()
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['source_provenance']['url'], self.url)
        saved['subscription_url'] = 'https://fixture.example/changed-outside-ui'
        self.path.write_text(json.dumps(saved), encoding='utf-8')
        self.app.load()
        self.assertFalse(self.app.subscription_ready())
        with patch.object(self.app.backend, 'start') as start:
            self.app.start()
        start.assert_not_called()

    def test_start_stays_reachable_on_every_simple_page_and_linked_restart(self):
        self.paste()
        self.root.minsize(800, 600)
        self.root.geometry('1040x740')
        for page in ('Overview', 'Devices', 'LAN sharing', 'Proxies'):
            self.app.view.show(page); self.root.update()
            button = self.app.start_button
            self.assertTrue(button.winfo_viewable(), page)
            self.assertLessEqual(button.winfo_y() + button.winfo_height(), button.master.winfo_height())
            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                 self.root.winfo_rooty() + self.root.winfo_height())
            self.assertEqual(str(button['state']), 'normal')
        self.app.raw['existing_proxy_port'] = 17897
        for key in ('subscription_url', 'profile_file', 'subscription_file'):
            self.app.vars[key].set('')
        with patch('portalproxy.existing_proxy.detect_system_proxy', return_value={'host':'127.0.0.1','port':17897}), patch.object(self.app, '_configure_lan', return_value=({}, '192.168.50.0/24')) as configure, patch.object(self.app, 'start') as start:
            self.app.quick_start()
        configure.assert_called_once_with((17897,), commit=False); start.assert_called_once()

    def test_unselected_clash_account_and_inactive_connection_address_are_not_shown(self):
        self.app.clash_info = {'total': 1234567, 'source_kind': 'clash-cache'}
        with patch('portalproxy.existing_proxy.read_clash_accounting') as read:
            self.app.load()
        read.assert_not_called()
        self.assertIsNone(self.app.view.subscription_info)
        self.app.vars['listen_host'].set('192.168.50.2')
        self.root.update()
        self.assertFalse(self.app.view.runtime_panel.winfo_ismapped())
        self.assertNotIn('192.168.50.2', self.app.view.guide_var.get())
        self.assertEqual(str(self.app.view.guide_copy_button['state']), 'disabled')
        self.assertEqual(str(self.app.view.guide_export_button['state']), 'disabled')

    def test_auto_link_uses_current_proxy_but_never_steals_pending_subscription(self):
        self.app.existing_proxy = {'host':'127.0.0.1', 'port':17897}
        current = {'host':'127.0.0.1', 'port':17898}
        with patch('portalproxy.existing_proxy.detect_system_proxy', return_value=current), \
                patch.object(self.app, '_configure_lan', return_value=({}, '192.168.50.0/24')) as configure, \
                patch.object(self.app, 'start') as start:
            self.app.quick_start()
            configure.assert_called_once_with((17898,), commit=False)
            start.assert_called_once()
            self.assertEqual(self.app.raw['existing_proxy_port'], 17898)
        self.app.vars['subscription_url'].set(self.url)
        with patch.object(self.app, 'use_existing_proxy') as link:
            self.app.quick_start()
            link.assert_not_called()
            self.assertEqual(self.app.vars['subscription_url'].get(), self.url)
        self.app.raw.pop('existing_proxy_port')
        with patch.object(self.app, 'use_existing_proxy') as link:
            self.app.quick_start()
            link.assert_not_called()

    def test_account_refresh_keeps_direct_subscription_and_disables_auto_link_on_pending_url(self):
        self.paste()
        direct = self.app.view.subscription_info
        proxy = {'host':'127.0.0.1', 'port':17897}
        info = {'upload':10, 'download':20, 'total':999, 'source_kind':'clash-cache'}
        self.app._next_discovery = float('inf')
        self.app.discovery_events.put((proxy, info))
        self.app._poll_discovery()
        self.assertIs(self.app.view.subscription_info, direct)
        self.assertEqual(self.app.clash_info, info)
        self.assertIn('缓存', self.app.view.clash_var.get())
        self.app.raw['existing_proxy_port'] = proxy['port']
        self.app.discovery_events.put((proxy, None))
        self.app._poll_discovery()
        self.assertIsNone(self.app.view.subscription_info)
        self.assertIn('暂时没有', self.app.view.clash_var.get())

    def test_one_click_setup_is_single_flight_and_never_starts_listener(self):
        entered, release = threading.Event(), threading.Event()
        def install(path):
            entered.set()
            if not release.wait(5): raise TimeoutError()
            return sys.executable
        with patch('portalproxy.core_setup.discover_core', return_value=None), \
                patch('portalproxy.core_setup.can_install', return_value=True), \
                patch('portalproxy.core_setup.install_core', side_effect=install) as download:
            try:
                self.app.setup_core()
                self.assertTrue(entered.wait(3))
                self.app.setup_core(); self.app.quick_start()
                self.assertEqual(download.call_count, 1)
                self.assertEqual(str(self.app.view.quick_button['state']), 'disabled')
            finally:
                release.set()
            deadline = time.monotonic() + 5
            while self.app.setting_up and time.monotonic() < deadline:
                self.root.update(); time.sleep(.01)
        self.assertFalse(self.app.setting_up)
        self.assertIsNone(self.app.backend.process)
        self.assertEqual(self.app.vars['core_path'].get(), sys.executable)

    def test_start_prepares_default_once_and_resumes_only_after_success(self):
        self.paste()
        self.app.vars['core_path'].set('')
        entered, release = threading.Event(), threading.Event()
        def install(path):
            entered.set()
            if not release.wait(5): raise TimeoutError()
            return sys.executable
        with patch('portalproxy.core_setup.discover_core', return_value=None), \
                patch('portalproxy.core_setup.can_install', return_value=True), \
                patch('portalproxy.core_setup.install_core', side_effect=install) as download, \
                patch.object(self.app, '_configure_lan', return_value=None) as configure:
            try:
                self.app.quick_start()
                self.assertTrue(entered.wait(3))
                self.app.quick_start()
                self.assertEqual(download.call_count, 1)
                configure.assert_not_called()
            finally:
                release.set()
            deadline = time.monotonic() + 5
            while self.app.setting_up and time.monotonic() < deadline:
                self.root.update(); time.sleep(.01)
            configure.assert_called_once_with(commit=False)
            self.assertEqual(self.download.call_count, 1, 'Preparing the core must not fetch the subscription again')
        self.assertFalse(self.app._start_after_setup)
        self.assertIsNone(self.app.backend.process)

    def test_failed_default_preparation_can_retry_start_without_reimport(self):
        self.paste()
        self.app.vars['core_path'].set('')
        with patch('portalproxy.core_setup.discover_core', return_value=None), \
                patch('portalproxy.core_setup.can_install', return_value=True), \
                patch('portalproxy.core_setup.install_core', side_effect=[OSError('fixture'), sys.executable]) as download, \
                patch.object(self.app, '_configure_lan', return_value=None) as configure:
            for attempt in range(2):
                self.app.quick_start()
                deadline = time.monotonic() + 5
                while self.app.setting_up and time.monotonic() < deadline:
                    self.root.update(); time.sleep(.01)
                if attempt == 0:
                    configure.assert_not_called()
                    self.assertFalse(self.app._start_after_setup)
                    self.assertEqual(str(self.app.view.quick_button['state']), 'normal')
            self.assertEqual(download.call_count, 2)
            configure.assert_called_once_with(commit=False)
        self.assertEqual(self.download.call_count, 1)

    def test_linked_modes_are_disabled_guarded_and_unlock_after_unlink(self):
        self.app.raw['existing_proxy_port'] = 17897
        self.app.vars['product_mode'].set('game')
        self.app.view.refresh(); self.root.update()
        self.app.set_product_mode('mixed')
        self.assertEqual(self.app.product_mode(),'mixed')
        self.app.set_product_mode('game')
        for mode in ('clash',):
            button = self.app.view.product_mode_buttons[mode]
            self.assertTrue(button.instate(['disabled']))
            button.invoke()
            self.assertEqual(self.app.product_mode(), 'game')
            self.app.set_product_mode(mode)
            self.assertEqual(self.app.product_mode(), 'game')
        self.app.vars['product_mode'].set('clash')
        with self.assertRaisesRegex(ValueError, 'Game and Mixed'):
            self.app.collect()
        self.app.vars['product_mode'].set('game')
        self.app.unlink_proxy()
        self.assertNotIn('existing_proxy_port', self.app.raw)
        for mode in ('mixed', 'clash'):
            self.assertFalse(self.app.view.product_mode_buttons[mode].instate(['disabled']))
            self.app.view.product_mode_buttons[mode].invoke()
            self.assertEqual(self.app.product_mode(), mode)

    def test_failed_link_restores_previous_mode_and_does_not_start_owned_core(self):
        self.app.set_product_mode('clash')
        before = self.path.read_bytes()
        with patch('portalproxy.existing_proxy.detect_system_proxy', return_value={'host':'127.0.0.1','port':17897}), \
                patch.object(self.app, '_configure_lan', return_value=({}, '192.168.50.0/24')), \
                patch.object(self.app, 'start', return_value=False):
            self.app.use_existing_proxy()
        self.assertEqual(self.app.product_mode(), 'clash')
        self.assertNotIn('existing_proxy_port', self.app.raw)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIsNone(self.app.backend.process)

    def test_unlink_restores_accepted_source_and_mode_without_reimport(self):
        self.paste()
        source = self.app.vars['subscription_file'].get()
        self.app.set_product_mode('mixed')
        with patch('portalproxy.existing_proxy.detect_system_proxy', return_value={'host':'127.0.0.1','port':17897}), \
                patch.object(self.app, '_configure_lan', return_value=({}, '192.168.50.0/24')), \
                patch.object(self.app, 'start', return_value=True):
            self.app.use_existing_proxy()
        self.assertEqual(self.app.product_mode(), 'game')
        self.assertFalse(self.app.subscription_ready())
        self.app.unlink_proxy()
        self.assertTrue(self.app.subscription_ready())
        self.assertEqual(self.app.vars['subscription_file'].get(), source)
        self.assertEqual(self.app.vars['subscription_url'].get(), self.url)
        self.assertEqual(self.app.product_mode(), 'mixed')
        self.assertEqual(self.download.call_count, 1)
        self.app.load()
        self.assertTrue(self.app.subscription_ready())
        self.assertEqual(self.app.product_mode(), 'mixed')


if __name__ == '__main__':
    unittest.main()
