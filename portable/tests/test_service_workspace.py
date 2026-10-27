import copy
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch


@unittest.skipUnless(sys.platform=='win32','Windows service workspace')
class ServiceWorkspaceTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from portalproxy.desktop import DesktopApp
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.profile=self.folder/'nodes.json';self.profile.write_text('{"proxies":[]}')
        self.path=self.folder/'config.json'
        self.path.write_text(json.dumps(dict(core_path=sys.executable,subscription_file=str(self.profile),listen_host='192.168.50.5',allowed_clients=['192.168.50.8'],product_mode='game')))
        self.network={'lan':{'host':'192.168.50.5','interface':'fixture','subnet':'192.168.50.0/24','clients':['192.168.50.8']},'hotspot':{}}
        self.patches=[patch('portalproxy.windows_network.inspect',return_value=self.network),patch('portalproxy.existing_proxy.detect_system_proxy',return_value=None),patch('portalproxy.existing_proxy.read_clash_accounting',return_value=None),patch('portalproxy.existing_proxy.clash_subscription_source',return_value=None)]
        for p in self.patches:p.start()
        self.root=tk.Tk();self.app=DesktopApp(self.root,self.path);self.app._next_discovery=float('inf')
        self.app.view.show('Workspaces');self.home=self.app.workspace_hub
        for monitor in self.app.source_monitors.values():monitor.loader=lambda url:None
        self.original=self.path.read_bytes()
        self.root.update()
    def tearDown(self):
        self.home.game.stop()
        if self.home.game.thread:self.home.game.thread.join(3)
        self.app.backend.process=None
        if self.home.owned_folder:self.home.owned_folder.cleanup()
        for timer in self.root.tk.splitlist(self.root.tk.call('after','info')):self.root.tk.call('after','cancel',timer)
        self.root.destroy()
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def running_owned(self):
        process=SimpleNamespace(poll=lambda:None)
        self.app.backend.process=process;self.app.backend.ready=True
        self.home.owned_config={'listen_port':10080,'subscription_file':str(self.profile)}
        return process

    def test_navigation_and_three_sources_do_not_mutate_saved_subscription(self):
        process=self.running_owned();raw=copy.deepcopy(self.app.raw);values={k:v.get() for k,v in self.app.vars.items()}
        self.app.existing_proxy={'port':7897};self.home.clash_enabled=True
        provider=SimpleNamespace(status=lambda:{'running':True,'http_port':18082},stop=Mock())
        self.app.games_hub=SimpleNamespace(xianniu=SimpleNamespace(provider=provider),running=True)
        with patch.object(self.app,'open_game_accelerator') as open_games:
            for page in ('game','clash','subscription','accelerator','game'):self.home.select(page)
            open_games.assert_called_once()
        self.assertIs(self.app.backend.process,process);self.assertTrue(self.home.clash_enabled)
        provider.stop.assert_not_called()
        self.assertEqual(raw,self.app.raw);self.assertEqual(values,{k:v.get() for k,v in self.app.vars.items()})
        self.assertEqual(self.path.read_bytes(),self.original)
        self.app.games_hub=None

    def test_owned_start_uses_loopback_and_does_not_modify_game_preferences(self):
        def start(path,values):self.app.backend.process=SimpleNamespace(poll=lambda:None)
        raw=copy.deepcopy(self.app.raw);values={k:v.get() for k,v in self.app.vars.items()}
        self.home.clash_enabled=True
        with patch.object(self.app.backend,'start',side_effect=start) as launch:
            self.home.start_owned()
        cfg=launch.call_args.args[1]
        self.assertEqual(cfg['listen_host'],'127.0.0.1');self.assertEqual(cfg['allowed_clients'],['127.0.0.1'])
        self.assertNotIn('shared_core',cfg);self.assertNotEqual(cfg['listen_port'],10081)
        self.assertTrue(self.home.clash_enabled);self.assertEqual(raw,self.app.raw)
        self.assertEqual(values,{k:v.get() for k,v in self.app.vars.items()})

    def test_each_stop_only_affects_its_own_service(self):
        self.running_owned();self.home.clash_enabled=True;self.app.existing_proxy={'port':7897}
        self.home.selected='clash'
        with patch.object(self.app,'stop') as stop_owned,patch.object(self.home.game,'stop') as stop_game:
            self.home.toggle();stop_owned.assert_not_called();stop_game.assert_not_called()
            self.assertFalse(self.home.clash_enabled)
            self.home.selected='subscription';self.home.toggle();stop_owned.assert_called_once();stop_game.assert_not_called()

    def test_source_quota_is_separate_and_survives_tab_switches(self):
        a=self.app.source_monitors['subscription'];b=self.app.source_monitors['clash']
        a.info={'upload':10,'download':20,'total':100,'updated_at':100}
        b.info={'upload':30,'download':50,'total':100,'updated_at':200}
        for key,expected in (('subscription',30),('clash',80),('subscription',30)):
            self.home.select(key);self.home.refresh()
            self.assertEqual(float(self.home.usage_progress['value']),expected)
        self.assertEqual(a.info['updated_at'],100);self.assertEqual(b.info['updated_at'],200)

    def test_empty_subscription_is_explicit_and_does_not_show_clash_as_owned(self):
        self.app.vars['subscription_file'].set('');self.app.raw.pop('subscription_file',None)
        self.home.select('subscription');self.home.refresh()
        self.assertEqual(self.home.usage_text.get(),'未导入订阅')
        self.assertFalse(self.home.usage_progress.winfo_manager())
        self.assertFalse(self.home.game.active);self.assertFalse(self.home.clash_enabled)

    def test_refresh_preserves_live_network_controls_and_stopped_status(self):
        self.home.select('game');self.root.update()
        with patch.object(self.home.network,'pack_forget',wraps=self.home.network.pack_forget) as forget:
            for _ in range(4):self.home.refresh()
            forget.assert_not_called()
        with patch.object(self.home.game,'snapshot',return_value={'state':'stopped','running':False}):
            self.home.state.set('局域网可用 · 外网 已连接');self.home.refresh()
            self.assertEqual(self.home.state.get(),'游戏共享已关闭')

    def test_source_preparation_survives_navigation_and_can_be_cancelled(self):
        self.home.source_pending=True
        self.home.select('clash');self.assertTrue(self.home.source_pending)
        self.home.select('subscription');self.home.toggle()
        self.assertFalse(self.home.source_pending)
