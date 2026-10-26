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
        self.inventory={};self.events=queue.Queue();self.detecting=False
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
        ttk.Button(row,text='导入',command=app.import_subscription).pack(side='left',padx=8)
        ttk.Button(row,text='本地配置',command=app.choose_profile).pack(side='left')
        ttk.Label(self.source,textvariable=self.source_note,style='Portal.CardNote.TLabel',wraplength=730).pack(anchor='w',pady=(8,0))
        self.linked=ttk.Frame(card,style='Portal.Card.TFrame')
        self.proxy=tk.StringVar()
        ttk.Label(self.linked,textvariable=self.proxy,style='Portal.Card.TLabel').pack(anchor='w')
        ttk.Label(self.linked,text='独立订阅会保留，停止共享不会关闭 Clash。',style='Portal.CardNote.TLabel').pack(anchor='w',pady=(6,0))
        network=ttk.Frame(card,style='Portal.Card.TFrame');network.pack(fill='x',pady=(0,16))
        ttk.Label(network,text='接入方式',style='Portal.Card.TLabel').pack(side='left',padx=(0,12))
        self.target=tk.StringVar(value='当前局域网')
        self.network_combo=ttk.Combobox(network,textvariable=self.target,values=('当前局域网','Windows 热点','仅此电脑'),state='readonly',width=19)
        self.network_combo.pack(side='left')
        ttk.Button(network,text='重新检测',command=self.detect).pack(side='left',padx=8)
        ttk.Button(network,text='打开热点设置',command=self.open_hotspot).pack(side='left')
        self.network_note=tk.StringVar(value='正在检测接入网络…')
        self.allow_subnet=tk.BooleanVar(value=not bool(app.vars['allowed_clients'].get().strip()))
        ttk.Checkbutton(card,text='允许所选局域网／热点中的设备接入',variable=self.allow_subnet).pack(anchor='w',pady=(0,8))
        ttk.Label(card,textvariable=self.network_note,style='Portal.CardNote.TLabel',wraplength=730).pack(anchor='w',pady=(0,12))
        self.connection=tk.StringVar(value='启动后显示设备需要填写的代理地址。')
        ttk.Label(card,textvariable=self.connection,style='Portal.Card.TLabel',wraplength=730).pack(anchor='w',pady=(6,16))
        actions=ttk.Frame(card,style='Portal.Card.TFrame');actions.pack(fill='x',pady=(12,8))
        self.action=ttk.Button(actions,text='启动共享',command=self.toggle,style='Portal.Accent.TButton');self.action.pack(side='left')
        ttk.Button(actions,text='设备与高级设置',command=lambda:app.view.show('LAN sharing')).pack(side='left',padx=12)
        ttk.Label(card,textvariable=self.state,style='Portal.CardNote.TLabel',wraplength=730).pack(anchor='w',pady=(10,8))
        ttk.Label(card,text='热点会共享电脑原有网络。需使用上面的代理才能进入星渡通道；不接管任意游戏 UDP。',style='Portal.CardNote.TLabel',wraplength=730).pack(anchor='w')
        self.refresh();self.detect();frame.after(200,self.poll)

    def active(self):
        hub=self.app.games_hub
        return bool(self.app.importing or self.app.setting_up or self.app.backend.process is not None or (hub and hub.running))

    def select(self,key):
        if key not in LABELS:raise ValueError('无效工作区')
        if self.active():self.state.set('请先停止当前通道，再切换用途。');return
        if key=='accelerator':
            if self.app.raw.get('existing_proxy_port'):self.app.unlink_proxy()
            self.selected=key;self.app.open_game_accelerator();return
        if self.app.product_mode()=='accelerator':self.app.set_product_mode('mixed')
        if self.app.raw.get('existing_proxy_port') and key!='clash':self.app.unlink_proxy()
        self.app.set_product_mode('game' if key=='game' else 'mixed')
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
        if self.app.backend.process is not None:self.app.stop();return
        if self.app.games_hub and self.app.games_hub.running:
            self.app.games_hub.xianniu.quick_toggle();return
        if self.selected=='accelerator':self.app.open_game_accelerator();return
        if self.detecting:self.state.set('正在检测网络，请稍后启动。');return
        target={'当前局域网':'lan','Windows 热点':'hotspot','仅此电脑':'local'}[self.target.get()]
        if target=='local' and self.selected in ('game','clash'):
            self.state.set('设备共享请选择局域网或热点；本机可直接使用现有 Clash。');return
        try:
            self.app._workspace_network=None if target=='local' else windows_network.selected_network(self.inventory,target)
            self.app._workspace_network_allow_subnet=self.allow_subnet.get()
            self.app.set_product_mode('game' if self.selected=='game' else 'clash' if target=='local' else 'mixed')
            if self.selected=='clash':self.app.use_existing_proxy(mode='mixed')
            else:self.app.quick_start()
        except ValueError as error:self.state.set(str(error))

    def refresh(self):
        self.title.set(LABELS[self.selected]);self.note.set(NOTES[self.selected])
        linked=self.selected=='clash'
        if linked:
            self.source.pack_forget()
            if not self.linked.winfo_manager():self.linked.pack(fill='x',before=self.network_combo.master,pady=(0,20))
        else:
            self.linked.pack_forget()
            if not self.source.winfo_manager():self.source.pack(fill='x',before=self.network_combo.master,pady=(0,20))
        proxy=getattr(self.app,'existing_proxy',None)
        self.proxy.set('已发现 Clash / 系统代理：127.0.0.1:'+str(proxy['port']) if proxy else '未发现已启用的本机 HTTP 代理，请先在 Clash 中开启系统代理。')
        running=self.app.backend.process is not None
        self.source_note.set(self.app._t(self.app.subscription_message) if self.app.subscription_message else '已准备独立配置' if self.app.subscription_ready() else '粘贴订阅链接并导入，或选择本地 YAML。')
        for widget in self.source.winfo_children():
            if isinstance(widget,ttk.Frame):
                for control in widget.winfo_children():control.configure(state='disabled' if self.active() else 'normal')
        self.network_combo.configure(state='disabled' if self.active() else 'readonly')
        self.action.configure(text='停止共享' if running else '选择游戏' if self.selected=='accelerator' else '联动并共享' if linked else '启动共享',state='disabled' if self.app.importing else 'normal')
        if running:
            host='127.0.0.1' if self.app.product_mode()=='clash' else self.app.vars['listen_host'].get()
            self.connection.set('代理地址：'+host+':'+self.app.vars['listen_port'].get()+' · 在设备 Wi-Fi 中选择手动 HTTP 代理')
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
        except queue.Empty:pass
        self.frame.after(200,self.poll)
