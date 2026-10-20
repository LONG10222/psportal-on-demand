import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from portalproxy import i18n
from portalproxy.desktop import DesktopApp
from test_core import port


class LanguagePreferencesTests(unittest.TestCase):
    def test_preferences_are_independent_of_proxy_config_and_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            self.assertEqual(i18n.load_language(path), 'zh')
            original = '{"subscription_url":"opaque-user-value"}'
            path.write_text(original)
            self.assertEqual(i18n.load_language(path), 'en')
            i18n.save_language(path, 'zh')
            self.assertEqual(path.read_text(), original)
            self.assertEqual(i18n.load_language(path), 'zh')
            self.assertEqual(json.loads(i18n.preference_path(path).read_text()), {'language': 'zh'})
            if os.name != 'nt':
                self.assertEqual(i18n.preference_path(path).stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                i18n.save_language(path, 'invalid')

    def test_catalog_format_placeholders_match(self):
        import string
        parser = string.Formatter()
        for source, translated in i18n.ZH.items():
            self.assertEqual([x[1] for x in parser.parse(source) if x[1]],
                             [x[1] for x in parser.parse(translated) if x[1]], source)

    def test_diagnostics_are_not_interpreted_as_format_templates(self):
        for language in ('zh', 'en'):
            self.assertEqual(i18n.text('Invalid value {opaque}', language), 'Invalid value {opaque}')

    def test_appearance_and_language_preferences_preserve_each_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            self.assertEqual(i18n.load_theme(path), 'dark')
            i18n.save_language(path, 'zh')
            i18n.save_theme(path, 'light')
            self.assertEqual(i18n.load_language(path), 'zh')
            i18n.save_language(path, 'en')
            self.assertEqual(i18n.load_theme(path), 'light')
            with self.assertRaises(ValueError):
                i18n.save_theme(path, 'unknown')


@unittest.skipUnless(os.environ.get('PSPORTAL_TK_TEST') == '1', 'Set PSPORTAL_TK_TEST=1 for real GUI hot switching')
class HotLanguageWindowTests(unittest.TestCase):
    def test_switching_live_listener_preserves_pid_inputs_dirty_page_and_logs(self):
        import tkinter as tk
        root = tk.Tk(); app = None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                provider = folder / 'provider.yaml'; provider.write_text('proxies: []\n')
                ports = set()
                while len(ports) < 3:
                    ports.add(port())
                listen, backend, api = sorted(ports)
                cfg = dict(listen_host='127.0.0.1', listen_port=listen, allowed_clients=['127.0.0.1'],
                           core_path=sys.executable, subscription_file=str(provider),
                           backend_port=backend, api_port=api, data_dir=str(folder / 'runtime'))
                path = folder / 'host.json'; path.write_text(json.dumps(cfg))
                app = DesktopApp(root, path)
                def wait(predicate):
                    end = time.monotonic() + 15
                    while time.monotonic() < end:
                        root.update()
                        if predicate(): return
                        time.sleep(.02)
                    self.fail(app.log_widget.get('1.0', 'end'))
                app.start_button.invoke()
                wait(lambda: app.status_var.get() == 'Listening')
                process = app.backend.process
                before = app.collect(); state = app.dirty
                variables = {key:id(var) for key,var in app.vars.items()}
                app.view.show('Profiles')
                log = app.log_widget.get('1.0', 'end')
                app.set_language('zh'); root.update()
                self.assertEqual(app.status_var.get(), '正在监听')
                self.assertEqual(app.start_button.cget('text'), '启动共享')
                self.assertEqual(app.view.title.get(), '配置')
                self.assertIs(app.backend.process, process)
                self.assertIsNone(process.poll())
                self.assertEqual(app.collect(), before)
                self.assertEqual(app.dirty, state)
                self.assertEqual({key:id(var) for key,var in app.vars.items()}, variables)
                self.assertTrue(app.log_widget.get('1.0', 'end').startswith(log))
                app.set_language('en'); root.update()
                app.set_theme('light'); app.set_theme('dark'); root.update()
                self.assertIs(app.backend.process, process)
                self.assertIsNone(process.poll())
                self.assertEqual(app.collect(), before)
                self.assertEqual(app.status_var.get(), 'Listening')
                self.assertEqual(app.start_button.cget('text'), 'Start sharing')
                self.assertEqual(app.view.page, 'Profiles')
                app.stop_button.invoke()
                wait(lambda: app.backend.process is None)
                app.vars['preferred_node'].set('未保存的节点名')
                self.assertTrue(app.dirty)
                app.set_language('zh'); app.set_language('en')
                self.assertTrue(app.dirty)
                self.assertEqual(app.vars['preferred_node'].get(), '未保存的节点名')
                app.dirty = False
                app.close()
        finally:
            if app:
                app.backend.stop()
                if app.backend.process:
                    app.backend.process.wait(timeout=15)
            for timer in root.tk.splitlist(root.tk.call('after', 'info')):
                root.tk.call('after', 'cancel', timer)
            try: root.destroy()
            except tk.TclError: pass
