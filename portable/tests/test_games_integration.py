import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(REPO/'integrations/xianniu-windows/src'),str(REPO/'integrations/xianniu-router/src')]


@unittest.skipUnless(sys.platform=='win32','DPAPI integration runs on Windows')
class IntegratedGamesTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from tkinter import ttk
        from portalproxy.desktop import DesktopApp
        from portalproxy.accelerator_registry import discover
        from starpass_xianniu.storage import Store
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.path=self.base/'config.json'
        self.path.write_text(json.dumps({'subscription_url':'https://example.invalid/sub?token=fixture-only',
          'product_mode':'mixed','listen_host':'192.168.50.5','allowed_clients':['192.168.50.8'],
          'preferred_node':'saved-node','accelerator_preferences':{'transport':'host','port':'7890'}}))
        self.original=self.path.read_bytes();self.store=Store(self.base/'game-private')
        inventory=discover({'installations':[],'processes':[]},exists=lambda p:False)
        self.patches=[patch('starpass_xianniu.storage.Store',return_value=self.store),
            patch('starpass_xianniu.game_grid.IconCache.read',return_value=None),
            patch('portalproxy.games_hub.discover',return_value=inventory),
            patch('portalproxy.existing_proxy.detect_system_proxy',return_value=None)]
        for item in self.patches:item.start()
        self.root=tk.Tk();self.app=DesktopApp(self.root,self.path);self.root.update()
        self.style=ttk.Style(self.root)

    def tearDown(self):
        hub=self.app.games_hub
        if hub and hub.xianniu:
            app=hub.xianniu
            async def drain():
                tasks=[t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
                for task in tasks:task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
            asyncio.run_coroutine_threadsafe(drain(),app.loop).result(3)
            app.loop.call_soon_threadsafe(app.loop.stop);app.thread.join(2);app.loop.close();app.store.unlock()
        widgets=[]
        def collect(widget):
            widgets.append(widget)
            for child in widget.winfo_children():collect(child)
        collect(self.root)
        for timer in self.root.tk.call('after','info'):
            command=self.root.tk.call('after','info',timer)[0]
            owner=next((w for w in widgets if command in (w._tclCommands or [])),self.root)
            owner.after_cancel(timer)
        self.root.destroy()
        for item in self.patches:item.stop()
        self.temp.cleanup()

    def test_games_are_embedded_in_same_window_without_mutating_other_modes_or_styles(self):
        raw=copy.deepcopy(self.app.raw)
        values={k:v.get() for k,v in self.app.vars.items()}
        title=self.root.title();protocol=self.root.protocol('WM_DELETE_WINDOW')
        background=self.style.lookup('TButton','background');theme=self.style.theme_use()
        self.app.view.show('Games');self.root.update()
        hub=self.app.games_hub
        self.assertIsNotNone(hub.xianniu)
        self.assertIs(hub.xianniu.root.winfo_toplevel(),self.root)
        self.assertEqual(self.root.title(),title);self.assertEqual(self.root.protocol('WM_DELETE_WINDOW'),protocol)
        self.assertEqual(self.style.lookup('TButton','background'),background);self.assertEqual(self.style.theme_use(),theme)
        self.assertEqual(self.style.lookup('SPGame.CardTitle.TLabel','foreground'),'#17243b')
        self.assertFalse(self.app.view.main_footer.winfo_ismapped())
        count=len(hub.native_frame.winfo_children())
        for _ in range(3):self.app.view.show('Overview');self.app.view.show('Games')
        self.assertEqual(len(hub.native_frame.winfo_children()),count)
        self.assertEqual(self.app.raw,raw)
        self.assertEqual({k:v.get() for k,v in self.app.vars.items()},values)
        self.assertEqual(self.path.read_bytes(),self.original)
        self.assertIsNone(self.app.backend.process)

    def test_other_brands_do_not_show_xianniu_games_as_their_own(self):
        self.app.view.show('Games');self.root.update()
        hub=self.app.games_hub;raw=copy.deepcopy(self.app.raw)
        hub.select('uu');self.root.update()
        self.assertFalse(hub.native_frame.winfo_ismapped())
        self.assertTrue(hub.linked_frame.winfo_ismapped())
        self.assertFalse(hub.providers['uu']['capabilities']['public_catalog_reader'])
        self.assertEqual(self.app.raw,raw)
        hub.select('leigod');self.assertFalse(hub.providers['leigod']['capabilities']['native_tcp_udp'])

    def test_navigation_away_disables_game_shortcuts(self):
        self.app.view.show('Games');self.assertTrue(self.app.games_hub.xianniu.active)
        self.app.view.show('Overview');self.assertFalse(self.app.games_hub.xianniu.active)


if __name__=='__main__':unittest.main()
