"""Windows service controls: navigation never changes or stops another service."""
import ipaddress
import json
import queue
import tempfile
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from .game_sharing import GameSharing
from . import windows_network
from .service_model import owned_values

LABELS={'game':'游戏共享','accelerator':'鲜牛加速','clash':'Clash 联动','subscription':'独立订阅'}
ROUTES={'仅局域网':'none','独立订阅':'subscription','Clash 联动':'clash','鲜牛加速':'accelerator'}


class ServiceWorkspace:
    independent_services=True
    def __init__(self,app,frame):
        self.app,self.frame=app,frame
        # Migrate a stopped legacy accelerator view back to its preserved normal
        # configuration. Opening the game library no longer changes this source.
        if app.product_mode()=='accelerator' and app.backend.process is None:
            app._leave_accelerator()
            app._selected_product_mode=app.product_mode()
        self.selected='subscription' if app.subscription_ready() else 'clash' if app.existing_proxy else 'game'
        self.game=GameSharing();self.clash_enabled=False;self.owned_config=None;self.owned_folder=None
        self.pending_start=None;self.source_pending=False;self.detecting=False;self.events=queue.Queue();self.inventory={}
        self.buttons={};self.state=tk.StringVar(value='就绪');self.connection=tk.StringVar();self.network_note=tk.StringVar()
        self.target=tk.StringVar(value='当前局域网');self.allow_subnet=tk.BooleanVar(value=False)
        self.game_source=tk.StringVar(value='独立订阅' if app.subscription_ready() else 'Clash 联动' if app.existing_proxy else '仅局域网')
        self.game_port=tk.StringVar(value='10081');self.edit_source=False
        try:
            prefs_path=app.path.with_suffix(app.path.suffix+'.sharing.json')
            if prefs_path.is_file() and prefs_path.stat().st_size<=4096:
                prefs=json.loads(prefs_path.read_text(encoding='utf-8'))
                if prefs.get('target') in ('当前局域网','Windows 热点'):self.target.set(prefs['target'])
                if prefs.get('source') in ROUTES:self.game_source.set(prefs['source'])
                if type(prefs.get('allow_subnet')) is bool:self.allow_subnet.set(prefs['allow_subnet'])
                if type(prefs.get('port')) is int and 1024<=prefs['port']<=65535:self.game_port.set(str(prefs['port']))
        except (OSError,ValueError):pass
        modes=ttk.Frame(frame,style='Portal.Page.TFrame');modes.pack(fill='x',pady=(0,14))
        for key,label in LABELS.items():
            button=ttk.Button(modes,text=label,command=lambda k=key:self.select(k));button.pack(side='left',expand=True,fill='x',padx=(0,7));self.buttons[key]=button
        card=ttk.Frame(frame,style='Portal.Card.TFrame',padding=20);card.pack(fill='both',expand=True)
        self.summary=tk.StringVar()
        ttk.Label(card,textvariable=self.summary,style='Portal.CardNote.TLabel').pack(anchor='w',pady=(0,14))
        self.network=ttk.Frame(card,style='Portal.Card.TFrame')
        row=ttk.Frame(self.network,style='Portal.Card.TFrame');row.pack(fill='x')
        ttk.Label(row,text='接入网络',style='Portal.Card.TLabel').pack(side='left',padx=(0,10))
        self.network_combo=ttk.Combobox(row,values=('当前局域网','Windows 热点'),textvariable=self.target,state='readonly',width=17);self.network_combo.pack(side='left')
        ttk.Button(row,text='重新检测',command=self.detect).pack(side='left',padx=8)
        self.hotspot_button=ttk.Button(row,text='热点设置',command=self.open_hotspot)
        self.network_combo.bind('<<ComboboxSelected>>',lambda _:self.refresh())
        self.allow_check=ttk.Checkbutton(self.network,text='允许此网络设备接入',variable=self.allow_subnet);self.allow_check.pack(anchor='w',pady=10)
        ttk.Label(self.network,textvariable=self.network_note,style='Portal.CardNote.TLabel').pack(anchor='w')
        route=ttk.Frame(self.network,style='Portal.Card.TFrame');route.pack(fill='x',pady=(14,4))
        ttk.Label(route,text='外网来源',style='Portal.Card.TLabel').pack(side='left',padx=(0,10))
        self.game_source_combo=ttk.Combobox(route,values=tuple(ROUTES),textvariable=self.game_source,state='readonly',width=17);self.game_source_combo.pack(side='left')
        self.game_source_combo.bind('<<ComboboxSelected>>',lambda _:self.refresh_route())
        self.route_action=ttk.Button(route,text='启用来源',command=self.start_route);self.route_action.pack(side='left',padx=8)
        self.source=ttk.Frame(card,style='Portal.Card.TFrame');self.source_note=tk.StringVar()
        self.url=ttk.Entry(self.source,textvariable=app.vars['subscription_url'],show='•');self.url.pack(fill='x')
        self.url.bind('<<Paste>>',app.paste_subscription);self.url.bind('<Return>',lambda _:app.import_subscription())
        row=ttk.Frame(self.source,style='Portal.Card.TFrame');row.pack(fill='x',pady=9)
        self.import_button=ttk.Button(row,text='导入订阅',command=app.import_subscription);self.import_button.pack(side='left')
        self.file_button=ttk.Button(row,text='本地配置',command=app.choose_profile);self.file_button.pack(side='left',padx=8)
        ttk.Label(self.source,textvariable=self.source_note,style='Portal.CardNote.TLabel').pack(anchor='w')
        self.source_summary=ttk.Frame(card,style='Portal.Card.TFrame')
        ttk.Label(self.source_summary,text='订阅已导入',style='Portal.Card.TLabel').pack(side='left')
        self.edit_source_button=ttk.Button(self.source_summary,text='更换订阅',command=self.open_source_editor);self.edit_source_button.pack(side='right')
        self.linked=ttk.Frame(card,style='Portal.Card.TFrame');self.proxy=tk.StringVar()
        ttk.Label(self.linked,textvariable=self.proxy,style='Portal.Card.TLabel').pack(anchor='w')
        self.controls=ttk.Frame(card,style='Portal.Card.TFrame');self.controls.pack(fill='x',pady=12)
        self.action=ttk.Button(self.controls,style='Portal.Accent.TButton',command=self.toggle);self.action.pack(side='left')
        self.details_button=ttk.Button(self.controls,text='游戏库',command=app.open_game_accelerator)
        self.connection_label=ttk.Label(card,textvariable=self.connection,style='Portal.Card.TLabel',wraplength=730);self.connection_label.pack(anchor='w',pady=(4,10))
        ttk.Label(card,textvariable=self.state,style='Portal.CardNote.TLabel',wraplength=730).pack(anchor='w')
        self.data=ttk.Frame(card,style='Portal.Card.TFrame');self.data.pack(fill='x',pady=(18,0));self.data.columnconfigure(0,weight=1);self.data.columnconfigure(1,weight=1)
        self.quota=left=ttk.Frame(self.data,style='Portal.Card.TFrame');left.grid(row=0,column=0,sticky='new',padx=(0,20))
        self.usage_title=tk.StringVar(value='订阅用量');ttk.Label(left,textvariable=self.usage_title,style='Portal.Section.TLabel').pack(anchor='w')
        self.usage_text=tk.StringVar();self.usage_state=tk.StringVar();self.usage_percent=tk.StringVar();self.traffic_text=tk.StringVar()
        ttk.Label(left,textvariable=self.usage_text,style='Portal.Card.TLabel',wraplength=330).pack(anchor='w',pady=8)
        self.usage_progress=ttk.Progressbar(left,maximum=100,length=250,style='Portal.Horizontal.TProgressbar')
        self.usage_percent_label=ttk.Label(left,textvariable=self.usage_percent,style='Portal.CardNote.TLabel')
        self.usage_state_label=ttk.Label(left,textvariable=self.usage_state,style='Portal.CardNote.TLabel');self.usage_state_label.pack(anchor='w')
        self.refresh_usage=ttk.Button(left,text='刷新用量',command=app.refresh_subscription_usage);self.refresh_usage.pack(anchor='w',pady=(9,0))
        right=ttk.Frame(self.data,style='Portal.Card.TFrame');right.grid(row=0,column=1,sticky='new')
        ttk.Label(right,text='当前通道流量',style='Portal.Section.TLabel').pack(anchor='w')
        ttk.Label(right,textvariable=self.traffic_text,style='Portal.Card.TLabel',wraplength=330).pack(anchor='w',pady=8)
        self.refresh();self.detect();frame.after(200,self.poll)

    def active(self):return bool(self.pending_start or self.source_pending or self.app.closing)
    def sync_mode(self):self.refresh()
    def can_view_shared(self,key):return key in LABELS
    def cancel_preparation(self):self.pending_start=None;self.source_pending=False
    def select(self,key):
        if key not in LABELS:raise ValueError('无效页面')
        self.pending_start=None;self.selected=key;self.state.set('就绪');self.refresh()
        if key=='accelerator':self.app.open_game_accelerator()
    def open_source_editor(self):
        if self.app.backend.process is None:self.edit_source=True;self.refresh();self.url.focus_set()
    def change_game_source(self):self.refresh_route()
    def open_hotspot(self):
        try:windows_network.open_hotspot_settings()
        except ValueError as error:self.state.set(str(error))

    def detect(self):
        if self.detecting:return
        self.detecting=True
        def work():
            try:value=windows_network.inspect()
            except Exception:value={'lan':None,'hotspot':{}}
            self.events.put(value)
        threading.Thread(target=work,daemon=True).start()

    def owned_running(self):return self.app.backend.process is not None
    def accelerator_status(self):
        hub=self.app.games_hub
        provider=hub.xianniu.provider if hub and hub.xianniu else None
        if provider:
            try:return provider.status()
            except Exception:pass
        return {}
    def route_port(self):
        route=ROUTES.get(self.game_source.get(),'none')
        if route=='subscription' and self.owned_config and self.app.backend.ready and self.app.backend.stopping_since is None and self.owned_running():return self.owned_config['listen_port']
        if route=='clash' and self.clash_enabled and self.app.existing_proxy:return self.app.existing_proxy['port']
        if route=='accelerator':
            status=self.accelerator_status()
            if status.get('running'):return status.get('http_port')
        return None
    def refresh_route(self):
        self.game.upstream(self.route_port());self.refresh()

    def start_route(self):
        route=ROUTES.get(self.game_source.get())
        if route=='subscription':
            if not self.owned_running():self.start_owned()
        elif route=='clash':
            if self.app.existing_proxy:self.clash_enabled=True;self.refresh_route()
            else:self.state.set('请先在 Clash 开启本机 HTTP 代理')
        elif route=='accelerator':self.app.open_game_accelerator()

    def toggle(self):
        if self.selected=='game':
            if self.game.active:self.game.stop();return
            if self.pending_start:self.pending_start=None;self.refresh();return
            self.pending_start=(self.target.get(),self.game_source.get());self.detect();self.state.set('检测网络中…');self.refresh();return
        if self.selected=='clash':
            if self.clash_enabled:self.clash_enabled=False;self.state.set('联动已停止，原 Clash 保持运行')
            elif self.app.existing_proxy:self.clash_enabled=True;self.state.set('Clash 已联动')
            else:self.state.set('请先在 Clash 开启本机 HTTP 代理')
            self.refresh_route();return
        if self.selected=='accelerator':
            hub=self.app.games_hub
            if hub and hub.xianniu and hub.xianniu.provider:hub.xianniu.quick_toggle()
            else:self.app.open_game_accelerator()
            return
        if self.source_pending:self.source_pending=False;self.refresh();return
        if self.owned_running():self.app.stop();return
        self.start_owned()

    def start_owned(self):
        from .config import validate
        from .core import atomic_private
        from .core_setup import discover_core
        from .setup import available_port
        try:
            values=owned_values(self.app)
            core=discover_core(self.app.path,values.get('core_path',''))
            if values.get('engine_mode','external')=='external' and not core:
                self.source_pending=True;self.app.setup_core();self.state.set('准备核心中…');return
            if core:values['core_path']=core
            reserved={self.game.snapshot().get('listen_port',10081)}
            if self.app.existing_proxy:reserved.add(self.app.existing_proxy['port'])
            status=self.accelerator_status()
            reserved.update(v for v in (status.get('http_port'),status.get('socks_port')) if type(v) is int)
            for key,port in (('listen_port',10080),('backend_port',10082),('api_port',10090)):
                values[key]=available_port('127.0.0.1',port,reserved);reserved.add(values[key])
            self.owned_folder=tempfile.TemporaryDirectory(prefix='starpass-owned-')
            path=Path(self.owned_folder.name)/'config.json';values['data_dir']=str(path.parent/'runtime')
            values=validate(values,path);atomic_private(path,json.dumps(values).encode())
            self.app.backend.start(path,values);self.owned_config=values;self.app.running_controls(True);self.state.set('独立订阅启动中…')
        except (OSError,ValueError,RuntimeError) as error:
            if self.owned_folder:self.owned_folder.cleanup();self.owned_folder=None
            # Never display raw parser/OS text containing an imported value.
            self.state.set(str(error) if str(error) in ('请先导入独立订阅',) else '启动失败，请检查订阅、核心和端口')

    def start_game(self,target):
        from .setup import available_port
        network=windows_network.selected_network(self.inventory,'hotspot' if target=='Windows 热点' else 'lan')
        subnet=ipaddress.ip_network(network['subnet'])
        clients=[c.strip() for c in self.app.vars['allowed_clients'].get().split(',') if c.strip()]
        if self.allow_subnet.get():
            if subnet.num_addresses>256:raise ValueError('网络范围过大，请指定设备地址')
            clients=[str(ip) for ip in subnet.hosts() if str(ip)!=network['host']]
        if not clients or any(ipaddress.ip_address(c) not in subnet for c in clients):raise ValueError('请在连接设置填写设备 IP，或允许此网络设备接入')
        excluded=set()
        if self.owned_config and self.owned_running():excluded.add(self.owned_config['listen_port'])
        status=self.accelerator_status();excluded.update(p for p in (status.get('http_port'),status.get('socks_port')) if type(p) is int)
        port=available_port(network['host'],int(self.game_port.get()),excluded)
        self.game.upstream(self.route_port());self.game.start(dict(listen_host=network['host'],listen_port=port,allowed_clients=clients));self.game_port.set(str(port));self.state.set('游戏共享启动中…')
        try:
            from .core import atomic_private
            path=self.app.path.with_suffix(self.app.path.suffix+'.sharing.json')
            if not path.is_symlink():atomic_private(path,json.dumps(dict(target=self.target.get(),source=self.game_source.get(),allow_subnet=self.allow_subnet.get(),port=port)).encode())
        except OSError:pass

    def refresh(self):
        game=self.game.snapshot();owned=self.owned_running();accel=self.accelerator_status().get('running',False)
        self.summary.set('游戏共享 '+('已开' if self.game.ready else '已关')+'  ·  鲜牛 '+('运行中' if accel else '未启动')+'  ·  Clash '+('已联动' if self.clash_enabled else '未联动')+'  ·  独立订阅 '+('运行中' if owned else '未启动'))
        layout=(self.selected,self.app.subscription_ready(),self.edit_source)
        # Repacking a live combobox dismisses its popup and loses keyboard focus.
        if layout!=getattr(self,'_layout',None):
            self._layout=layout
            for widget in (self.network,self.source,self.source_summary,self.linked):widget.pack_forget()
            if self.selected=='game':self.network.pack(fill='x',before=self.controls,pady=(0,12))
            elif self.selected=='subscription':
                (self.source if not layout[1] or self.edit_source else self.source_summary).pack(fill='x',before=self.controls,pady=(0,12))
            elif self.selected=='clash':self.linked.pack(fill='x',before=self.controls,pady=(0,12))
        self.hotspot_button.pack(side='left') if self.target.get()=='Windows 热点' else self.hotspot_button.pack_forget()
        self.network_combo.configure(state='disabled' if self.game.active or self.pending_start else 'readonly')
        self.route_action.configure(text='来源已就绪' if self.route_port() else '启用来源',state='disabled' if self.route_port() or self.game_source.get()=='仅局域网' else 'normal')
        self.allow_check.configure(state='disabled' if self.game.active or self.pending_start else 'normal')
        source_busy=owned or self.app.importing or self.app.setting_up
        for widget in (self.url,self.import_button,self.file_button,self.edit_source_button):widget.configure(state='disabled' if source_busy else 'normal')
        self.source_note.set(self.app._t(self.app.subscription_message) if self.app.subscription_message else '粘贴链接后导入')
        self.proxy.set('Clash：127.0.0.1:'+str(self.app.existing_proxy['port']) if self.app.existing_proxy else '未发现已开启的 Clash 本机 HTTP 代理')
        self.details_button.pack(side='left',padx=10) if self.selected=='accelerator' else self.details_button.pack_forget()
        labels={'game':'停止游戏共享' if self.game.active else '取消准备' if self.pending_start else '开启游戏共享','subscription':'停止独立订阅' if owned else '取消准备' if self.source_pending else '启动独立订阅','clash':'停止联动' if self.clash_enabled else '启用联动','accelerator':'停止鲜牛加速' if accel else '打开游戏库'}
        self.action.configure(text=labels[self.selected],state='disabled' if self.app.closing or self.selected=='subscription' and (self.app.importing or self.app.setting_up) else 'normal')
        if self.selected=='game':
            self.connection.set('设备代理：'+game.get('address','') if game.get('running') else '游戏共享未开启')
            if game.get('running'):self.state.set('局域网可用 · 外网来源'+('已启用' if self.route_port() else '未启用'))
            elif game.get('error'):self.state.set(game['error'])
            elif game.get('state')=='stopped':self.state.set('游戏共享已关闭')
        elif self.selected=='subscription':self.connection.set('本机代理：127.0.0.1:'+str(self.owned_config['listen_port']) if owned and self.owned_config else '独立订阅未启动')
        elif self.selected=='clash':self.connection.set('游戏设备使用“游戏共享”的地址')
        else:self.connection.set('游戏设备可在“游戏共享”选择鲜牛来源')
        if self.selected=='subscription' or self.selected=='game' and self.game_source.get()=='独立订阅':
            runtime=self.app.view.runtime or {}
            if owned and runtime.get('core_state')=='failed':self.state.set('核心启动失败，请检查订阅和规则数据')
            elif owned and runtime.get('preparing'):self.state.set('正在准备线路…')
            elif self.selected=='subscription' and owned and self.app.backend.ready:self.state.set('本机入口就绪 · 核心按需启动')
        from .subscription_info import display,usage_percent
        from .traffic import display as traffic_display
        route=ROUTES.get(self.game_source.get()) if self.selected=='game' else self.selected
        has_quota=route in ('subscription','clash')
        self.quota.grid() if has_quota else self.quota.grid_remove()
        self.usage_title.set('Clash 订阅用量' if route=='clash' else '独立订阅用量')
        monitor=self.app.source_monitors.get(route,self.app.source_monitors['subscription'])
        info=monitor.info
        self.usage_text.set(display(info,'zh',compact=True) if info else '用量暂不可用' if route=='clash' else '未导入订阅' if not self.app.subscription_ready() else '服务端未提供用量')
        self.usage_state.set('刷新中…' if monitor.busy else '更新失败 · 保留上次数据' if monitor.message.startswith('更新失败') else '每分钟更新' if monitor.info else '')
        self.refresh_usage.configure(state='disabled' if monitor.busy else 'normal')
        percent=usage_percent(info)
        if percent is None:self.usage_progress.pack_forget();self.usage_percent_label.pack_forget()
        else:
            if not self.usage_progress.winfo_manager():self.usage_progress.pack(fill='x',before=self.usage_state_label,pady=5);self.usage_percent_label.pack(anchor='w',before=self.usage_state_label,pady=(0,5))
            self.usage_progress['value']=percent;self.usage_percent.set(f'已用 {percent:.1f}%')
        self.traffic_text.set(traffic_display(game.get('traffic') if self.selected=='game' else (self.app.view.runtime or {}).get('traffic') if self.selected=='subscription' else None))
        for key,button in self.buttons.items():button.configure(style='Portal.ModeSelected.TButton' if key==self.selected else 'Portal.ModeIdle.TButton',state='disabled' if self.app.closing else 'normal')

    def poll(self):
        if not self.frame.winfo_exists():return
        try:
            self.inventory=self.events.get_nowait();self.detecting=False
            network=self.inventory.get('lan');self.network_note.set(network['host'] if network else '未检测到局域网')
            pending=self.pending_start;self.pending_start=None
            if pending and self.app.view.page=='Workspaces' and self.selected=='game':
                try:self.start_game(pending[0])
                except (ValueError,OSError):self.state.set('请检查网络、设备名单和共享端口')
        except queue.Empty:pass
        if self.source_pending and not self.app.setting_up:
            self.source_pending=False
            from .core_setup import discover_core
            if not self.app.closing:
                if discover_core(self.app.path,self.app.vars['core_path'].get()):self.start_owned()
                else:self.state.set('核心准备失败，请检查后重试')
        self.game.upstream(self.route_port())
        if not self.owned_running() and self.owned_folder:
            self.owned_folder.cleanup();self.owned_folder=None;self.owned_config=None
        self.refresh();self.frame.after(200,self.poll)

    def close(self):self.cancel_preparation();self.game.stop();self.clash_enabled=False
    def shutdown_complete(self):
        if not self.owned_running() and self.owned_folder:
            self.owned_folder.cleanup();self.owned_folder=None;self.owned_config=None
        return not self.game.active
