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
        self.app.vars['core_path'].set('')
        self.root.update()
        self.assertEqual(str(self.app.view.quick_button['state']), 'disabled')
        self.assertTrue(self.app.view.choose_core_button.winfo_viewable())
        self.assertIn('Mihomo', self.app.view.core_note_var.get())

    def test_saved_source_from_an_old_link_cannot_bypass_start_guard(self):
        self.paste()
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['desktop_import_url_sha256'], hashlib.sha256(self.url.encode()).hexdigest())
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
        with patch.object(self.app, '_configure_lan', return_value=True) as configure, patch.object(self.app, 'start') as start:
            self.app.quick_start()
        configure.assert_called_once_with((17897,)); start.assert_called_once()

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


if __name__ == '__main__':
    unittest.main()
