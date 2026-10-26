"""One Windows workspace for owned subscriptions, linked Clash and devices."""
import queue,threading
import tkinter as tk
from tkinter import ttk
from . import windows_network

LABELS={'game':'游戏共享','accelerator':'鲜牛加速','clash':'Clash 联动','subscription':'独立订阅'}
NOTES={'game':'使用星渡自己的订阅，向选定网络中的游戏设备共享。',
 'clash':'复用电脑上已开启的 Clash 代理；星渡只管理自己的共享入口。',
 'subscription':'使用自己的订阅，可供本机或设备使用。',
 'accelerator':'官方登录、游戏、区服、线路与免费规则在鲜牛游戏库中管理。'}


class WorkspaceHub:
    def __init__(self,app,frame):
        self.app,self.frame=app,frame
        self.selected=('accelerator' if app.product_mode()=='accelerator' else 'clash' if app.raw.get('existing_proxy_port') else 'game' if app.product_mode()=='game' else 'subscription')
        self.inventory={};self.events=queue.Queue();self.detecting=False;self.pending_start=None
        self.was_running=False
        self.buttons={}
        modes=ttk.Frame(frame,style='Portal.Page.TFrame');modes.pack(fill='x',pady=(0,16))
        for key,label in LABELS.items():
            b=ttk.Button(modes,text=label,command=lambda k=key:self.select(k));b.pack(side='left',fill='x',expand=True,padx=(0,8));self.buttons[key]=b
        card=ttk.Frame(frame,padding=24,style='Portal.Card.TFrame');card.pack(fill='both',expand=True)
        self.title=tk.StringVar();self.note=tk.StringVar();self.state=tk.StringVar(value='请选择用途，确认接入网络后启动。')
        self.source_note=tk.StringVar()
        ttk.Label(card,textvariable=self.title,style='Portal.Section.TLabel').pack(anchor='w')
        ttk.Label(card,textvariable=self.note,style='Portal.CardNote.TLabel',wraplength=730).pack(anchor='w',pady=(8,20))
        self.source=ttk.Frame(card,style='Portal.Card.TFrame');self.source.pack(fill='x',pady=(0,20))
        ttk.Label(self.source,text='独立订阅',style='Portal.Card.TLabel').pack(anchor='w',pady=(0,8))
        row=ttk.Frame(self.source,style='Portal.Card.TFrame');row.pack(fill='x')
        self.url=ttk.Entry(row,textvariable=app.vars['subscription_url'],show='•');self.url.pack(side='left',fill='x',expand=True)
        self.url.bind('<<Paste>>',app.paste_subscription)
        self.url.bind('<Return>',lambda _:app.import_subscription())
        ttk.Button(row,text='导入',command=app.import_subscription).pack(side='left',padx=8)
        ttk.Button(row,text='本地配置',command=app.choose_profile).pack(side='left')
        ttk.Label(self.source,textvariable=self.source_note,style='Portal.CardNote.TLabel',wraplength=730).pack(anchor='w',pady=(8,0))
        self.linked=ttk.Frame(card,style='Portal.Card.TFrame')
        self.proxy=tk.StringVar()
        ttk.Label(self.linked,textvariable=self.proxy,style='Portal.Card.TLabel').pack(anchor='w')
        ttk.Label(self.linked,text='独立订阅会保留，停止共享不会关闭 Clash。',style='Portal.CardNote.TLabel').pack(anchor='w',pady=(6,0))
        self.network=ttk.Frame(card,style='Portal.Card.TFrame');self.network.pack(fill='x',pady=(0,16))
        network=ttk.Frame(self.network,style='Portal.Card.TFrame');network.pack(fill='x',pady=(0,12))
        ttk.Label(network,text='接入方式',style='Portal.Card.TLabel').pack(side='left',padx=(0,12))
        saved=app.raw.get('workspace_target')
        if app.product_mode()=='clash':saved='local'
        if not isinstance(saved,str):saved=None
        self.target=tk.StringVar(value={'lan':'当前局域网','hotspot':'Windows 热点','local':'仅此电脑'}.get(saved,'仅此电脑' if app.product_mode()=='clash' else '当前局域网'))
        self.network_combo=ttk.Combobox(network,textvariable=self.target,values=('当前局域网','Windows 热点','仅此电脑'),state='readonly',width=19)
        self.network_combo.pack(side='left')
        ttk.Button(network,text='重新检测',command=self.detect).pack(side='left',padx=8)
        self.hotspot_button=ttk.Button(network,text='打开热点设置',command=self.open_hotspot)
        self.network_combo.bind('<<ComboboxSelected>>',lambda _:self.refresh())
        self.network_note=tk.StringVar(value='正在检测接入网络…')
        self.allow_subnet=tk.BooleanVar(value=not bool(app.vars['allowed_clients'].get().strip()))
        self.allow_check=ttk.Checkbutton(self.network,text='允许所选网络中的设备接入',variable=self.allow_subnet)
        self.network_label=ttk.Label(self.network,textvariable=self.network_note,style='Portal.CardNote.TLabel',wraplength=730)
        self.allow_check.pack(anchor='w',pady=(0,8));self.network_label.pack(anchor='w')
        self.connection=tk.StringVar(value='启动后显示设备需要填写的代理地址。')
        self.connection_label=ttk.Label(card,textvariable=self.connection,style='Portal.Card.TLabel',wraplength=730)
        self.connection_label.pack(anchor='w',pady=(6,16))
        actions=ttk.Frame(card,style='Portal.Card.TFrame');actions.pack(fill='x',pady=(12,8))
        self.action=ttk.Button(actions,text='启动共享',command=self.toggle,style='Portal.Accent.TButton');self.action.pack(side='left')
        self.details_button=ttk.Button(actions,text='设备与高级设置',command=lambda:app.view.show('LAN sharing'))
        self.details_button.pack(side='left',padx=12)
        ttk.Label(card,textvariable=self.state,style='Portal.CardNote.TLabel',wraplength=730).pack(anchor='w',pady=(10,8))
        self.footnote=ttk.Label(card,text='热点会共享电脑原有网络，设备需填写代理；此入口不接管游戏 UDP。',style='Portal.CardNote.TLabel',wraplength=730)
        self.refresh();self.detect();frame.after(200,self.poll)

    def active(self):
        hub=self.app.games_hub
        return bool(self.pending_start or self.app.importing or self.app.setting_up or self.app.closing
            or getattr(self.app,'xianniu_checking',False) or self.app.backend.process is not None or (hub and hub.running))

    def sync_mode(self):
        previous=self.selected
        mode=self.app.product_mode()
        if mode=='accelerator':self.selected='accelerator'
        elif self.app.raw.get('existing_proxy_port'):self.selected='clash'
        elif mode=='game':self.selected='game'
        elif mode=='clash' or self.selected not in ('subscription','clash'):self.selected='subscription'
        if mode=='clash':self.target.set('仅此电脑')
        if previous!=self.selected:
            self.connection.set('启动后显示代理地址。');self.state.set('选择接入方式，再启动。')
        self.refresh()

    def cancel_preparation(self):
        if getattr(self.app,'_start_after_setup',False)=='workspace':
            self.app._start_after_setup=False
            self.app._workspace_network=None;self.app._workspace_target=None
            self.state.set('已取消启动；核心准备完成后可重试。');self.refresh()
        if self.pending_start:
            self.pending_start=None;self.state.set('已取消准备，未启动共享。');self.refresh()

    def select(self,key):
        if key not in LABELS:raise ValueError('无效工作区')
        if self.active():self.state.set('请先停止当前通道，再切换用途。');return
        self.selected=key
        self.connection.set('启动后显示代理地址。');self.state.set('选择接入方式，再启动。')
        if key=='accelerator':
            if self.app.raw.get('existing_proxy_port'):self.app.unlink_proxy()
            self.app.open_game_accelerator();return
        if self.app.product_mode()=='accelerator':self.app.set_product_mode('mixed')
        if self.app.raw.get('existing_proxy_port') and key!='clash':
            self.app.unlink_proxy()
            saved=self.app.raw.get('workspace_target')
            if isinstance(saved,str) and saved in ('lan','hotspot','local'):
                self.target.set({'lan':'当前局域网','hotspot':'Windows 热点','local':'仅此电脑'}[saved])
        if key!='subscription' and self.target.get()=='仅此电脑':self.target.set('当前局域网')
        self.app.set_product_mode('game' if key=='game' else 'clash' if self.target.get()=='仅此电脑' and key=='subscription' else 'mixed')
        self.selected=key;self.refresh()

    def detect(self):
        if self.detecting:return
        self.detecting=True
        def read():
            from .existing_proxy import detect_system_proxy
            try:self.events.put((windows_network.inspect(),detect_system_proxy()))
            except Exception:self.events.put(({'lan':None,'hotspot':{'state':'unknown','network':None}},None))
        threading.Thread(target=read,daemon=True).start()

    def open_hotspot(self):
        try:windows_network.open_hotspot_settings()
        except ValueError as error:self.state.set(str(error))

    def toggle(self):
        if self.selected=='accelerator':self.app.open_game_accelerator();return
        if self.app.backend.process is not None:self.app.stop();return
        if self.pending_start:self.cancel_preparation();return
        if getattr(self.app,'_start_after_setup',False)=='workspace':self.cancel_preparation();return
        if self.active():return
        target={'当前局域网':'lan','Windows 热点':'hotspot','仅此电脑':'local'}[self.target.get()]
        if target=='local' and self.selected in ('game','clash'):
            self.state.set('设备共享请选择局域网或热点；本机可直接使用现有 Clash。');return
        self.pending_start=(self.selected,target)
        self.state.set('正在确认接入网络… 可取消准备。')
        self.detect();self.refresh()

    def _start_checked(self,target):
        try:
            self.app._workspace_network=None if target=='local' else windows_network.selected_network(self.inventory,target)
            if self.selected!='clash' and not self.app.subscription_ready():
                self.state.set('请先导入订阅或选择本地配置，再启动。');return
            self.app._workspace_network_allow_subnet=self.allow_subnet.get()
            self.app._workspace_target=target
            self.app.set_product_mode('game' if self.selected=='game' else 'clash' if target=='local' else 'mixed')
            if self.selected=='clash':self.app.use_existing_proxy(mode='mixed')
            else:self.app.quick_start()
            if not self.active():self.state.set('未启动，请检查配置提示或重新检测 Clash。')
        except ValueError as error:
            self.app._workspace_network=None;self.app._workspace_target=None
            self.state.set(str(error))

    def refresh(self):
        self.title.set(LABELS[self.selected]);self.note.set(NOTES[self.selected])
        linked=self.selected=='clash'
        accelerator=self.selected=='accelerator'
        if not accelerator and not self.network.winfo_manager():self.network.pack(fill='x',before=self.connection_label,pady=(0,16))
        if linked:
            self.source.pack_forget()
            if not self.linked.winfo_manager():self.linked.pack(fill='x',before=self.network,pady=(0,20))
        elif accelerator:
            self.source.pack_forget();self.linked.pack_forget();self.network.pack_forget()
        else:
            self.linked.pack_forget()
            if not self.source.winfo_manager():self.source.pack(fill='x',before=self.network,pady=(0,20))
        values=('当前局域网','Windows 热点','仅此电脑') if self.selected=='subscription' else ('当前局域网','Windows 热点')
        if self.target.get() not in values:self.target.set(values[0])
        self.network_combo.configure(values=values)
        local=self.target.get()=='仅此电脑'
        hotspot=self.target.get()=='Windows 热点'
        if hotspot:self.hotspot_button.pack(side='left')
        else:self.hotspot_button.pack_forget()
        if local:self.allow_check.pack_forget();self.network_label.pack_forget()
        else:
            self.allow_check.pack(anchor='w',before=self.network_label,pady=(0,8)) if self.network_label.winfo_manager() else self.allow_check.pack(anchor='w',pady=(0,8))
            self.network_label.pack(anchor='w')
        self.footnote.pack(anchor='w') if hotspot and not accelerator else self.footnote.pack_forget()
        self.details_button.pack_forget() if accelerator else self.details_button.pack(side='left',padx=12)
        proxy=getattr(self.app,'existing_proxy',None)
        self.proxy.set('已发现 Clash / 系统代理：127.0.0.1:'+str(proxy['port']) if proxy else '未发现已启用的本机 HTTP 代理，请先在 Clash 中开启系统代理。')
        running=self.app.backend.process is not None
        self.source_note.set(self.app._t(self.app.subscription_message) if self.app.subscription_message else '已准备独立配置' if self.app.subscription_ready() else '粘贴订阅链接并导入，或选择本地 YAML。')
        for widget in self.source.winfo_children():
            if isinstance(widget,ttk.Frame):
                for control in widget.winfo_children():control.configure(state='disabled' if self.active() else 'normal')
        self.network_combo.configure(state='disabled' if self.active() else 'readonly')
        core_pending=getattr(self.app,'_start_after_setup',False)=='workspace'
        label='返回游戏库' if accelerator else ('停止本机代理' if local else '停止共享') if running else '取消准备' if self.pending_start or core_pending else '联动并共享' if linked else '启动本机代理' if local else '启动共享'
        stopping=running and self.app.backend.stopping_since is not None
        blocked=self.active() and not (running or self.pending_start or core_pending or accelerator)
        self.action.configure(text=label,state='disabled' if stopping or blocked else 'normal')
        self.allow_check.configure(state='disabled' if self.active() else 'normal')
        self.details_button.configure(state='disabled' if self.pending_start else 'normal')
        if accelerator:self.connection.set('进入游戏库选择游戏、区服并一键加速。')
        elif not running and self.connection.get().startswith('启动后显示'):
            self.connection.set('启动后显示本机应用使用的代理地址。' if local else '启动后显示设备需要填写的代理地址。')
        if running:
            host='127.0.0.1' if self.app.product_mode()=='clash' else self.app.vars['listen_host'].get()
            hint='本机应用填写 HTTP 代理' if self.app.product_mode()=='clash' else '设备 Wi-Fi 中填写手动 HTTP 代理'
            self.connection.set('代理地址：'+host+':'+self.app.vars['listen_port'].get()+' · '+hint)
            self.state.set(self.app.status_var.get())
        elif self.was_running:
            self.connection.set('共享已停止，设备代理入口已关闭。')
            self.state.set('Clash 继续运行；可重新启动共享。' if linked else '可切换用途，或重新启动共享。')
        self.was_running=running
        for key,button in self.buttons.items():button.configure(style='Portal.Accent.TButton' if key==self.selected else 'TButton',state='disabled' if self.active() else 'normal')

    def poll(self):
        if not self.frame.winfo_exists():return
        try:
            self.inventory,proxy=self.events.get_nowait();self.app.existing_proxy=proxy;self.detecting=False
            lan=self.inventory.get('lan');hotspot=self.inventory.get('hotspot',{})
            self.network_note.set(('局域网 '+lan['host'] if lan else '局域网未确认')+' · '+('热点 '+hotspot['network']['host'] if hotspot.get('network') else '热点未开启或未确认')+'\n电脑 IP 变化后请重新检测；设备代理地址应属于实际接入的网络。')
            self.refresh()
            pending=self.pending_start;self.pending_start=None
            if pending:
                if self.app.view.page=='Workspaces' and pending[0]==self.selected and not self.active():self._start_checked(pending[1])
                self.refresh()
        except queue.Empty:pass
        self.frame.after(200,self.poll)
