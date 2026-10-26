import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import threading
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
            patch('xianniu_router.control.call_api',return_value={'pause_state':0,'total_datetime':100}),
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
        self.app.open_game_accelerator()
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
        self.app.open_game_accelerator();self.root.update()
        hub=self.app.games_hub;raw=copy.deepcopy(self.app.raw)
        hub.select('uu');self.root.update()
        self.assertFalse(hub.native_frame.winfo_ismapped())
        self.assertTrue(hub.linked_frame.winfo_ismapped())
        self.assertFalse(hub.providers['uu']['capabilities']['public_catalog_reader'])
        self.assertEqual(self.app.raw,raw)
        hub.select('leigod');self.assertFalse(hub.providers['leigod']['capabilities']['native_tcp_udp'])

    def test_navigation_away_disables_game_shortcuts(self):
        self.app.open_game_accelerator();self.assertTrue(self.app.games_hub.xianniu.active)
        self.app.view.show('Overview');self.assertFalse(self.app.games_hub.xianniu.active)

    def pump_until(self,predicate):
        deadline=time.monotonic()+3
        while not predicate() and time.monotonic()<deadline:
            self.root.update();time.sleep(.02)
        self.assertTrue(predicate())

    def test_accelerator_button_enters_real_mode_and_restores_previous_source_when_leaving(self):
        raw=copy.deepcopy(self.app.raw)
        values={k:v.get() for k,v in self.app.vars.items()}
        self.app.view.product_mode_buttons['accelerator'].invoke();self.root.update()
        game=self.app.games_hub.xianniu
        self.assertEqual(self.app.view.page,'Games');self.assertTrue(game.simple)
        self.assertFalse(game.devices_panel.winfo_manager())
        self.assertFalse(game.route_panel.winfo_manager())
        self.assertEqual(game.start_button.cget('text'),'一键加速')
        self.assertEqual(self.app.product_mode(),'accelerator')
        self.assertEqual(self.app.raw['accelerator_previous_config']['raw'],raw)
        self.assertEqual(self.app.vars['subscription_url'].get(),'')
        self.assertEqual(self.path.read_bytes(),self.original)
        self.app.set_product_mode('mixed');self.root.update()
        self.assertEqual(self.app.view.page,'Overview')
        self.assertFalse(self.app.view.nav['Games'].winfo_manager())
        self.assertEqual({k:v.get() for k,v in self.app.vars.items()},values)

    def test_other_modes_cannot_show_game_page_even_in_advanced_navigation(self):
        for mode in ('game','mixed','clash'):
            self.app.set_product_mode(mode);self.root.update()
            self.assertFalse(self.app.view.nav['Games'].winfo_manager())
            self.app.view.show('Games')
            self.assertEqual(self.app.view.page,'Overview')
            self.assertIsNone(self.app.games_hub)
            self.app.view.set_advanced(True)
            self.assertFalse(self.app.view.nav['Games'].winfo_manager())
        self.app.open_game_accelerator();self.root.update()
        self.assertTrue(self.app.view.nav['Games'].winfo_manager())
        self.assertEqual(self.app.view.page,'Games')
        hub=self.app.games_hub
        hub.mode_combo.current(0);hub.change_mode();self.root.update()
        self.assertEqual(self.app.product_mode(),'game')
        self.assertEqual(self.app.view.page,'Overview')
        self.assertFalse(hub.xianniu.active)
        self.app.view.show('Games');self.assertEqual(self.app.view.page,'Overview')

    def test_quick_action_fetches_a_line_then_starts_only_after_user_click(self):
        self.app.open_game_accelerator();game=self.app.games_hub.xianniu
        game.config.update(account={'access_token':'fixture-only'},exclusive_confirmed=True)
        data={'lines':[{'id':120,'title':'fixture line'}],'all_lines':[]}
        with patch.object(game.catalog,'lines',return_value=data),patch.object(game,'start') as start:
            game.select_game_id(12)
            self.assertFalse(start.called)
            game.quick_toggle()
            self.pump_until(lambda:start.called)
            start.assert_called_once()
            self.assertEqual(game.line.current(),0)
            self.assertIsNone(game.quick_pending)

    def test_cancelled_preparation_cannot_start_from_late_line_result(self):
        self.app.open_game_accelerator();game=self.app.games_hub.xianniu
        game.config.update(account={'access_token':'fixture-only'},exclusive_confirmed=True)
        gate=threading.Event()
        def delayed(*args):
            gate.wait(2);return {'lines':[{'id':120,'title':'fixture line'}],'all_lines':[]}
        with patch.object(game.catalog,'lines',side_effect=delayed),patch.object(game,'start') as start:
            game.select_game_id(12);game.quick_toggle()
            self.assertIsNotNone(game.quick_pending)
            game.quick_toggle();gate.set()
            self.assertIsNone(game.quick_pending)
            deadline=time.monotonic()+.4
            while time.monotonic()<deadline:self.root.update();time.sleep(.02)
            start.assert_not_called()

    def test_single_stop_button_pauses_owned_session_and_borrowed_session_only_stops(self):
        self.app.open_game_accelerator();game=self.app.games_hub.xianniu
        game.provider=object()
        try:
            with patch.object(game,'pause') as pause,patch.object(game,'stop') as stop:
                game.config['session_mode']='managed';game.quick_toggle();pause.assert_called_once();stop.assert_not_called()
                game.config['session_mode']='borrowed';game.quick_toggle();stop.assert_called_once()
        finally:game.provider=None

    def test_failed_pause_does_not_trap_closed_listener_in_repeated_shutdown(self):
        self.app.open_game_accelerator();game=self.app.games_hub.xianniu
        class StoppedProvider:
            running=True
            async def stop_and_pause(self):
                self.running=False
                raise ValueError('官方尚未确认暂停，请核对')
        game.provider=StoppedProvider();game.pause()
        self.pump_until(lambda:not game.busy)
        self.assertIsNone(game.provider)
        self.assertIn('暂停',game.status_var.get())

    def test_free_steam_confirmation_does_not_claim_it_will_resume_paid_time(self):
        self.app.open_game_accelerator();game=self.app.games_hub.xianniu
        game.select_game_id(12)
        game.config.update(account={'access_token':'fixture-only'},exclusive_confirmed=False)
        self.assertIs(game.selected_game['is_free'],True)
        with patch('tkinter.messagebox.askyesno',return_value=False) as confirm,patch.object(game,'start') as start:
            game.quick_toggle()
            message=confirm.call_args.args[1]
            self.assertIn('官方标记为免费',message)
            self.assertIn('不恢复账号计时',message)
            self.assertNotIn('开启加速会恢复官方计时',message)
            start.assert_not_called()

    def home(self):
        network={'host':'192.168.50.5','interface':'fixture','subnet':'192.168.50.0/24','clients':['192.168.50.8']}
        with patch('portalproxy.windows_network.inspect',return_value={'lan':network,'hotspot':{'state':'Off','network':None}}):
            self.app.view.show('Workspaces')
            self.pump_until(lambda:not self.app.workspace_hub.detecting)
        return self.app.workspace_hub

    def test_windows_home_prepares_clash_mixed_sharing_without_replacing_saved_subscription(self):
        home=self.home();original=self.app.vars['subscription_url'].get()
        home.select('clash')
        self.assertEqual(self.app.vars['subscription_url'].get(),original)
        self.assertFalse(home.source.winfo_manager())
        self.assertTrue(home.linked.winfo_manager())
        with patch.object(self.app,'use_existing_proxy') as linked:
            home.toggle();linked.assert_called_once_with(mode='mixed')
        self.assertEqual(self.app._workspace_network['host'],'192.168.50.5')
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_hotspot_off_does_not_apply_guessed_address_or_start(self):
        home=self.home();home.target.set('Windows 热点')
        values={k:v.get() for k,v in self.app.vars.items()}
        with patch.object(self.app,'quick_start') as start:
            home.toggle();start.assert_not_called()
        self.assertIn('开启 Windows 热点',home.state.get())
        self.assertEqual({k:v.get() for k,v in self.app.vars.items()},values)

    def test_home_clears_transient_network_on_advanced_navigation_and_reports_stopped(self):
        home=self.home();self.app._workspace_network=home.inventory['lan']
        self.app.view.show('Overview')
        self.assertIsNone(self.app._workspace_network)
        home.was_running=True;home.refresh()
        self.assertIn('已停止',home.connection.get())

    def test_home_leaves_accelerator_and_recovers_independent_source(self):
        home=self.home();original=self.app.vars['subscription_url'].get()
        home.select('accelerator');self.root.update()
        self.assertEqual(self.app.product_mode(),'accelerator')
        home.select('subscription');self.root.update()
        self.assertEqual(self.app.product_mode(),'mixed')
        self.assertEqual(self.app.vars['subscription_url'].get(),original)
        self.assertFalse(self.app.raw.get('existing_proxy_port'))

    def test_changed_network_does_not_silently_widen_manual_device_allowlist(self):
        self.app._workspace_network={'host':'192.168.137.1','interface':'hotspot','subnet':'192.168.137.0/24','clients':['192.168.137.2']}
        self.app._workspace_network_allow_subnet=False
        original=self.app.vars['allowed_clients'].get()
        with patch('tkinter.messagebox.showerror') as error:
            self.assertFalse(self.app._configure_lan(commit=False))
        error.assert_called_once()
        self.assertEqual(self.app.vars['allowed_clients'].get(),original)


if __name__=='__main__':unittest.main()
