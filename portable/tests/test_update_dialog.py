"""Real Tk update states with synthetic HTTP metadata, no live download/install."""
import os
from types import SimpleNamespace
import time
import threading
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from portalproxy import update_dialog


@unittest.skipUnless(os.environ.get('PSPORTAL_TK_TEST') == '1', 'Requires explicitly enabled graphical Tk runner')
class UpdateDialogTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root=tk.Tk()
        self.addCleanup(self.root.destroy)
        from portalproxy.desktop_view import DesktopView
        self.app=SimpleNamespace(root=self.root,_t=lambda text:text,view=SimpleNamespace(root=self.root,theme='dark'))
        DesktopView._styles(self.app.view)
        update_dialog.show(self.app)
        self.window=self.app._update_window
        self.root.update()
        self.frame=self.window.winfo_children()[0]
        self.buttons=self.frame.winfo_children()[3].winfo_children()

    def wait(self,condition):
        deadline=time.monotonic()+3
        while not condition() and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertTrue(condition())

    def notes(self):
        return self.frame.winfo_children()[4].winfo_children()[0]

    def status(self):
        return self.root.getvar(self.frame.winfo_children()[1].cget('textvariable'))

    def test_no_release_and_offline_are_distinct(self):
        with patch('portalproxy.app_updates.check',return_value=(None,False)):
            self.buttons[0].invoke()
            self.wait(lambda:'No official release' in self.status())
        self.assertIn('disabled',self.buttons[1].state())
        with patch('portalproxy.app_updates.check',side_effect=OSError('offline')):
            self.buttons[0].invoke()
            self.wait(lambda:'failed' in self.status())
        self.assertIn('unknown',self.status())

    def test_existing_window_reused_and_theme_applied(self):
        update_dialog.show(self.app)
        self.assertIs(self.window,self.app._update_window)
        self.assertEqual(self.notes().cget('background'),'#111c2a')

    def test_check_has_no_automatic_download_and_close_is_safe(self):
        candidate=SimpleNamespace(version=(0,2,0),notes='Synthetic notes',name='example.tar.gz')
        with patch('portalproxy.app_updates.check',return_value=(candidate,True)),patch('portalproxy.app_updates.download') as download:
            self.buttons[0].invoke()
            self.wait(lambda:'0.2.0' in self.status())
            self.assertNotIn('disabled',self.buttons[1].state())
            download.assert_not_called()
            self.window.destroy()
            self.root.update()

    def test_compact_languages_themes_keep_actions_visible(self):
        from portalproxy import i18n
        from tkinter import ttk
        for language in ('en','zh'):
            for dark in (False,True):
                with self.subTest(language=language,dark=dark):
                    self.window.destroy()
                    self.app._t=lambda text:i18n.text(text,language)
                    from portalproxy.desktop_view import DesktopView
                    self.app.view.theme='dark' if dark else 'light'
                    DesktopView._styles(self.app.view)
                    update_dialog.show(self.app)
                    self.window=self.app._update_window
                    self.frame=self.window.winfo_children()[0]
                    self.buttons=self.frame.winfo_children()[3].winfo_children()
                    self.window.geometry('380x320')
                    self.root.update()
                    self.assertEqual(self.buttons[0].cget('text'),i18n.text('Check updates',language))
                    self.assertEqual(self.notes().cget('background'),self.app.view.palette['entry'])
                    for button in self.buttons:
                        self.assertTrue(button.winfo_viewable())
                        self.assertGreaterEqual(button.winfo_rootx(),self.window.winfo_rootx())
                        self.assertGreaterEqual(button.winfo_rooty(),self.window.winfo_rooty())
                        self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),self.window.winfo_rootx()+self.window.winfo_width())
                        self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),self.window.winfo_rooty()+self.window.winfo_height())
                    notes=self.notes()
                    self.assertEqual(ttk.Style(self.root).lookup('TLabel','background'),self.app.view.palette['card'])
                    self.assertEqual(ttk.Style(self.root).lookup('TButton','foreground'),self.app.view.palette['text'])
                    self.assertTrue(notes.winfo_viewable())
                    self.assertGreater(notes.winfo_height(),20)
                    self.assertIsNotNone(notes.dlineinfo('1.0'), 'The first manual-update instruction must actually be visible')
                    self.assertTrue(notes.get('1.0','end').startswith(i18n.text('Manual update: stop sharing, close StarPass, extract into a new folder and launch. Keep the old folder for rollback. Never delete your user configuration.',language)))
                    self.assertLessEqual(notes.winfo_rooty()+notes.winfo_height(),self.window.winfo_rooty()+self.window.winfo_height())
                    if os.environ.get('PSPORTAL_SCREENSHOT_DIR') and os.sys.platform.startswith('linux'):
                        from helpers.x11_window_capture import capture
                        output=Path(os.environ['PSPORTAL_SCREENSHOT_DIR'])
                        output.mkdir(parents=True,exist_ok=True)
                        capture(self.window,output/f'synthetic-updates-{language}-{"dark" if dark else "light"}.png')

    def test_download_success_and_close_cancels_background(self):
        candidate=SimpleNamespace(version=(0,2,0),notes='Synthetic notes',name='example.tar.gz')
        with patch('portalproxy.app_updates.check',return_value=(candidate,True)):
            self.buttons[0].invoke()
            self.wait(lambda:'0.2.0' in self.status())
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/('synthetic-'+'long-path-'*100+'.tar.gz')
            with patch('tkinter.filedialog.asksaveasfilename',return_value=str(target)),patch('portalproxy.app_updates.download',return_value=target):
                self.buttons[1].invoke()
                self.wait(lambda:'not installed' in self.status())
                self.root.update()
                self.assertNotIn(str(target),self.status())
                self.assertIn(str(target),self.notes().get('1.0','end'))
                self.assertIsNotNone(self.notes().dlineinfo('1.0'))
                self.notes().yview_moveto(1)
                self.root.update()
                self.assertGreater(self.notes().yview()[0],0)
                self.notes().yview_moveto(0)
            started=threading.Event();stopped=threading.Event();cancelled=[]
            def pending(update,destination,cancel,progress):
                started.set()
                try:
                    cancelled.append(cancel.wait(3))
                finally:stopped.set()
            with patch('tkinter.filedialog.asksaveasfilename',return_value=str(target)),patch('portalproxy.app_updates.download',side_effect=pending):
                self.buttons[1].invoke()
                self.wait(started.is_set)
                self.window.destroy()
                self.wait(stopped.is_set)
                self.assertEqual(cancelled,[True])
