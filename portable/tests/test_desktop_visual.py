"""Opt-in genuine mapped-window screenshots with explicitly synthetic data.

Run on isolated Linux X11/Xvfb with PSPORTAL_TK_TEST=1 and
PSPORTAL_SCREENSHOT_DIR=/absolute/output/path. Images are actual DesktopApp pixels,
but runtime/node/provider values are offline test fixtures, not live measurements.
This does not establish macOS/Windows appearance or physical-device acceptance.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from portalproxy.desktop import DesktopApp
from helpers.x11_window_capture import capture


@unittest.skipUnless(sys.platform.startswith('linux') and os.environ.get('PSPORTAL_TK_TEST') == '1'
    and os.environ.get('PSPORTAL_SCREENSHOT_DIR'),
    'Set PSPORTAL_TK_TEST=1 and PSPORTAL_SCREENSHOT_DIR on isolated Linux X11')
class DesktopVisualEvidenceTests(unittest.TestCase):
    def test_current_simple_ui_runtime_nodes_and_repeated_hot_switching(self):
        import tkinter as tk
        root = tk.Tk()
        app = None
        destination = Path(os.environ['PSPORTAL_SCREENSHOT_DIR']).absolute()
        destination.mkdir(parents=True, exist_ok=True)
        evidence = []
        try:
            with tempfile.TemporaryDirectory(prefix='synthetic desktop visual ') as directory:
                folder = Path(directory)
                path = folder / 'config.json'
                with patch('portalproxy.existing_proxy.detect_system_proxy', return_value=None):
                    app = DesktopApp(root, path)
                root.geometry('1120x800+0+0')
                deadline = time.monotonic() + 10
                while not root.winfo_viewable() and time.monotonic() < deadline:
                    root.update(); time.sleep(.02)
                self.assertTrue(root.winfo_viewable())

                def save(name):
                    root.update_idletasks(); root.update()
                    filename = 'synthetic-' + name + '.png'
                    result = capture(root, destination / filename)
                    result.update(file=filename, language=app.view.language, theme=app.view.theme,
                                  page=app.view.page, synthetic_fixture=True,
                                  sha256=hashlib.sha256((destination / filename).read_bytes()).hexdigest())
                    evidence.append(result)

                def visible(widget):
                    root.update_idletasks()
                    # Overview is scrollable so subscription details and live
                    # runtime controls remain reachable at compact sizes.
                    canvas = widget.master
                    while canvas is not None and not isinstance(canvas, tk.Canvas):
                        canvas = getattr(canvas, 'master', None)
                    if canvas is not None:
                        top = widget.winfo_rooty()
                        bottom = top + widget.winfo_height()
                        viewport_top = canvas.winfo_rooty()
                        if top < viewport_top or bottom > viewport_top + canvas.winfo_height():
                            bounds = canvas.bbox('all')
                            target = canvas.canvasy(0) + top - viewport_top - 8
                            canvas.yview_moveto(max(0, target) / max(1, bounds[3]))
                            root.update_idletasks()
                        self.assertGreaterEqual(widget.winfo_rooty(), canvas.winfo_rooty())
                        self.assertGreaterEqual(widget.winfo_rootx(), canvas.winfo_rootx())
                        self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                             canvas.winfo_rooty() + canvas.winfo_height())
                        self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                             canvas.winfo_rootx() + canvas.winfo_width())
                    self.assertTrue(widget.winfo_viewable(), str(widget))
                    self.assertGreater(widget.winfo_width(), 2)
                    self.assertGreaterEqual(widget.winfo_rootx(), root.winfo_rootx())
                    self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                         root.winfo_rootx() + root.winfo_width())
                    self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                         root.winfo_rooty() + root.winfo_height())

                self.assertFalse(app.view.advanced)
                self.assertEqual(app.view.language, 'zh')
                self.assertFalse(app.view.runtime_panel.winfo_ismapped())
                self.assertFalse(app.view.node_controls.winfo_ismapped())
                visible(app.view.quick_button)
                visible(app.view.preflight_button)
                visible(app.view.core_setup_button)
                with patch('tkinter.messagebox.showinfo') as help_dialog:
                    app.view.preflight_button.invoke()
                self.assertIn('首次使用', help_dialog.call_args.args[1])
                self.assertIsNone(app.backend.process)
                self.assertIn('第 1 步', app.view.hero_note_var.get())
                app.view.observe('Core: failed')
                self.assertIn(app._t('failed'), app.view.hero_note_var.get())
                app.view.observe('Core: starting')
                self.assertIn(app._t('starting'), app.view.hero_note_var.get())
                app.view.observe('Core: stopped')
                for canvas in app.view.scroll_canvases:
                    canvas.yview_moveto(0)
                save('simple-home-zh-dark')
                # Real compact-window evidence: primary controls must stay
                # reachable in both translations and themes, with no network.
                original = {key: value.get() for key, value in app.vars.items()}
                for language, theme in (('zh', 'light'), ('en', 'dark')):
                    root.geometry('1040x740+0+0')
                    app.set_language(language); app.set_theme(theme)
                    root.update()
                    self.assertEqual((root.winfo_width(), root.winfo_height()), (1040, 740))
                    for canvas in app.view.scroll_canvases:
                        canvas.yview_moveto(0)
                    visible(app.view.subscription_entry)
                    visible(app.view.product_mode_combo)
                    visible(app.view.quick_button)
                    visible(app.view.preflight_button)
                    visible(app.view.core_setup_button)
                    self.assertEqual({key: value.get() for key, value in app.vars.items()}, original)
                    self.assertIsNone(app.backend.process)
                    for canvas in app.view.scroll_canvases:
                        canvas.yview_moveto(0)
                    save('compact-home-' + language + '-' + theme)
                root.geometry('1120x800+0+0')
                app.set_language('zh'); app.set_theme('dark')
                provider = folder / 'synthetic-provider.json'
                provider.write_text(json.dumps({'proxies': [
                    {'name': 'HK Offline fixture', 'type': 'ss', 'server': 'example.invalid', 'port': 443},
                    {'name': 'JP Offline fixture', 'type': 'ss', 'server': 'example.invalid', 'port': 443}]}))
                path.write_text(json.dumps(dict(listen_host='192.168.50.2', listen_port=10081,
                    allowed_clients=['192.168.50.30'], subscription_file=str(provider),
                    core_path=sys.executable, selection_mode='auto')))
                app.load()
                app.set_language('zh')
                app.inspect_provider()
                for mode in ('game', 'mixed', 'clash'):
                    app.set_product_mode(mode)
                    visible(app.view.product_mode_combo)
                    save('product-' + mode + '-zh-dark')
                app.set_product_mode('game')
                fake_process = SimpleNamespace(poll=lambda: None)
                app.backend.process = fake_process
                app.backend.ready = True
                app.backend.runtime = dict(event='status', state='forwarding', core_state='running',
                    listen_host='192.168.50.2', listen_port=10081, connected_clients=2,
                    active_connections=5, node_management=True, selection_mode='fastest',
                    switch_threshold_ms=50, selected_node='HK Offline fixture', busy=False,
                    last_command_id=0, command_error='', nodes=[
                        dict(name='HK Offline fixture', healthy=True, delay_ms=42),
                        dict(name='JP Offline fixture', healthy=None, delay_ms=None)])
                app.running_controls(True)
                app.poll()
                visible(app.view.runtime_panel)
                self.assertEqual(app.view.connection_count_var.get(), '活动设备：2 · 连接数：5')
                self.assertEqual(app.view.address_var.get(), '192.168.50.2:10081')
                save('overview-runtime-zh-dark')
                app.view.show('LAN sharing')
                save('lan-sharing-zh-dark')
                app.view.show('Proxies')
                visible(app.view.node_controls)
                visible(app.view.fastest_button)
                app.view.node_table.selection_set(app.view.node_table.get_children()[0])
                root.update()
                save('proxies-live-fixture-zh-dark')
                variables = {key: id(value) for key, value in app.vars.items()}
                values = app.collect()
                app.backend.command = Mock()
                for _ in range(3):
                    for language in ('en', 'zh'):
                        app.set_language(language)
                        for theme in ('light', 'dark'):
                            app.set_theme(theme)
                            for page in ('Overview', 'LAN sharing', 'Proxies'):
                                app.view.show(page)
                                root.update()
                    self.assertIs(app.backend.process, fake_process)
                    self.assertEqual(app.collect(), values)
                    self.assertEqual({key: id(value) for key, value in app.vars.items()}, variables)
                    selected = app.view.node_table.selection()
                    self.assertEqual(app.view.node_table.item(selected[0], 'values')[0], 'HK Offline fixture')
                app.backend.command.assert_not_called()
                app.set_language('en'); app.set_theme('light')
                visible(app.view.fastest_button)
                save('proxies-live-fixture-en-light')
                app.vars['profile_file'].set(str(provider))
                app.backend.runtime.update(selection_group='', selection_mode='profile', groups=[
                    dict(name='Media selector', selected='HK Offline fixture', eligible_node_count=2),
                    dict(name='Work selector', selected='JP Offline fixture', eligible_node_count=2)])
                app.poll(); root.update()
                self.assertEqual(app.view.selection_group_var.get(), '')
                self.assertEqual(str(app.view.test_nodes_button.cget('state')), 'disabled')
                self.assertFalse(app.view.node_table.get_children())
                app.view.selection_group_var.set('Media selector')
                app.view.group_combo.event_generate('<<ComboboxSelected>>')
                root.update()
                app.backend.command.assert_not_called()
                app.backend.runtime['selection_group'] = 'Media selector'
                app.poll(); root.update()
                self.assertEqual(len(app.view.node_table.get_children()), 2)
                self.assertEqual(str(app.view.test_nodes_button.cget('state')), 'normal')
                self.assertFalse(app.view.selection_card.winfo_ismapped())
                visible(app.view.group_combo)
                save('profile-explicit-group-en-light')
                app.raw['existing_proxy_port'] = 7897
                app.view.refresh(); root.update()
                self.assertFalse(app.view.node_controls.winfo_ismapped())
                self.assertFalse(app.view.selection_card.winfo_ismapped())
                self.assertEqual(len(app.view.node_table.get_children()), 0)
                self.assertIn('existing Clash client', app.view.node_state_var.get())
                save('linked-proxy-delegated-en-light')
                app.backend.process = None
                app.backend.ready = False
                app.backend.runtime = None
                app.dirty = False
                app.close()
            (destination / 'UI-EVIDENCE.json').write_text(json.dumps(dict(
                source_commit=os.environ.get('GITHUB_SHA', ''),
                fixture='SYNTHETIC OFFLINE: no live subscription, remote node, or physical device was used',
                scope='Actual mapped current source DesktopApp on Linux X11, not a mockup or native macOS/Windows acceptance',
                screenshots=evidence), ensure_ascii=False, indent=2) + '\n')
        finally:
            if app is not None:
                app.backend.process = None
            for callback in root.tk.splitlist(root.tk.call('after', 'info')):
                root.tk.call('after', 'cancel', callback)
            try:
                root.destroy()
            except tk.TclError:
                pass
