"""Native Windows UI and CLI for the isolated StarPass provider preview."""
import argparse
import asyncio
import copy
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time

from . import __version__
from .provider import Catalog, Provider
from .storage import Store
from .library import CatalogRepository, LibraryModel
from .game_grid import GameGrid


def catalog_path():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'catalog.json'
    return Path(__file__).resolve().parents[3] / 'xianniu-router/files/usr/share/xianniu-router/catalog.json'


def duration(value):
    if value is None: return '暂未获取'
    h, rem = divmod(int(value), 3600)
    m, s = divmod(rem, 60)
    return f'{h} 小时 {m:02d} 分 {s:02d} 秒'


def error_text(error):
    from xianniu_router.control import APIError
    if isinstance(error, APIError): return f'官方接口未通过（代码 {error.code}），请刷新账号状态'
    if isinstance(error, (ValueError, RuntimeError)):
        # Only our own static validation strings reach the UI, never raw network exceptions.
        value = str(error)
        if value and all(ord(c) >= 32 for c in value) and any('\u4e00' <= c <= '\u9fff' for c in value):
            return value[:180]
    return f'操作未完成（{type(error).__name__}），请检查网络和官方会话后重试'


class App:
    def __init__(self, root, store, embedded=False):
        import tkinter as tk
        from .ui_style import ScopedTtk
        ttk=ScopedTtk()
        self.tk, self.ttk, self.root, self.store = tk, ttk, root, store
        self.embedded=embedded
        self.closed=False
        self.active=True
        self.config = store.load()
        self.catalog = Catalog(self.config, catalog_path())
        self.repository = CatalogRepository(catalog_path(),store.root,self.config)
        self.games = self.repository.load()
        self.library = LibraryModel(self.games,self.config)
        self.line_sequence = 0
        self.lines, self.all_lines, self.areas = [], [], []
        self.selected_game = None
        self.provider = None
        self.events = queue.Queue()
        self.busy = False
        self.closing = False
        self.qr_generation = 0
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        if not embedded:
            root.title('星渡 · 鲜牛游戏共享预览 ' + __version__)
            width=min(1160,max(900,root.winfo_screenwidth()-64))
            height=min(820,max(650,root.winfo_screenheight()-96))
            root.geometry(f'{width}x{height}+{max(0,(root.winfo_screenwidth()-width)//2)}+{max(0,(root.winfo_screenheight()-height)//2-20)}')
            root.minsize(min(1040,width),min(760,height))
        root.configure(background='#f4f6fa')
        style = ttk.Style(root)
        if not embedded:style.theme_use('clam')
        for name in ttk.classes:
            default='Treeview' if name=='Treeview' else 'TLabelframe' if name=='LabelFrame' else 'Vertical.TScrollbar' if name=='Scrollbar' else 'T'+name
            style.configure('SPGame.'+default,font=('Microsoft YaHei UI',10),background='#f4f6fa',foreground='#17243b')
        style.configure('SPGame.TEntry',fieldbackground='white',foreground='#17243b')
        style.configure('SPGame.TFrame', background='#f4f6fa')
        style.configure('SPGame.TLabel', background='#f4f6fa', foreground='#17243b')
        style.configure('SPGame.Card.TFrame', background='white')
        style.configure('SPGame.Card.TLabel', background='white')
        style.configure('SPGame.Muted.TLabel', foreground='#64748b')
        style.configure('SPGame.CardMuted.TLabel', foreground='#64748b', background='white')
        style.configure('SPGame.CardTitle.TLabel', font=('Microsoft YaHei UI', 12, 'bold'), background='white')
        style.configure('SPGame.Title.TLabel', font=('Microsoft YaHei UI', 18, 'bold'))
        style.configure('SPGame.TButton', padding=(12, 7), background='#e9eef6', borderwidth=0)
        style.map('SPGame.TButton', background=[('active', '#dce5f2')])
        style.configure('SPGame.Compact.TButton',padding=(8,4))
        style.configure('SPGame.Compact.TMenubutton',padding=(8,4))
        style.configure('SPGame.Accent.TButton', font=('Microsoft YaHei UI', 11, 'bold'), padding=(20, 8), background='#3266e3', foreground='white')
        style.map('SPGame.Accent.TButton', background=[('active', '#2455ca'), ('disabled', '#b9c8e8')], foreground=[('disabled', '#f3f6fc')])
        style.configure('SPGame.SelectedTab.TButton',background='#e7efff',foreground='#2455ca',padding=(8,4))
        style.configure('SPGame.Card.TCheckbutton', background='white', padding=(4, 8))
        style.map('SPGame.Card.TCheckbutton', background=[('active', '#eef4ff')])
        style.configure('SPGame.TCombobox', padding=3, fieldbackground='white')
        for name in ('SPGame.Card.TLabel','SPGame.CardTitle.TLabel','SPGame.Card.TCheckbutton'):
            style.configure(name,foreground='#17243b',background='white')
        style.configure('SPGame.Muted.TLabel',background='#f4f6fa')
        style.configure('SPGame.Title.TLabel',foreground='#17243b',background='#f4f6fa')
        for name in ('SPGame.TButton','SPGame.Compact.TButton','SPGame.Compact.TMenubutton'):
            style.configure(name,foreground='#17243b',background='#e9eef6',font=('Microsoft YaHei UI',10),borderwidth=0)
            style.map(name,foreground=[('disabled','#94a3b8'),('!disabled','#17243b')],background=[('active','#dce5f2')])
        style.map('SPGame.Card.TCheckbutton',foreground=[('disabled','#94a3b8'),('!disabled','#17243b')],background=[('active','#eef4ff'),('!active','white')])
        style.configure('SPGame.TCombobox',foreground='#17243b',background='#e9eef6',arrowcolor='#64748b')
        style.map('SPGame.TCombobox',fieldbackground=[('readonly','white'),('disabled','#eef1f6')],foreground=[('disabled','#94a3b8'),('readonly','#17243b')])
        style.map('SPGame.TEntry',fieldbackground=[('!disabled','white')],foreground=[('!disabled','#17243b')])
        outer = ttk.Frame(root, padding=16); outer.pack(fill='both', expand=True)
        header = ttk.Frame(outer)
        if not embedded:header.pack(fill='x', pady=(0, 8))
        ttk.Label(header, text='星渡', style='SPGame.Title.TLabel').pack(side='left')
        ttk.Label(header, text='鲜牛游戏共享', style='SPGame.Muted.TLabel').pack(side='left', padx=16)
        ttk.Button(header, text='设置', command=self.advanced,style='SPGame.Compact.TButton').pack(side='right')
        ttk.Label(header, text='预览版', style='SPGame.Muted.TLabel').pack(side='right', padx=12)
        account = ttk.Frame(outer, style='SPGame.Card.TFrame', padding=10); account.pack(fill='x', pady=(0, 10))
        account_row = ttk.Frame(account, style='SPGame.Card.TFrame'); account_row.pack(fill='x')
        self.account_var = tk.StringVar()
        ttk.Label(account_row, textvariable=self.account_var, style='SPGame.CardTitle.TLabel').pack(side='left', fill='x', expand=True)
        ttk.Button(account_row, text='微信登录', command=self.login,style='SPGame.Compact.TButton').pack(side='right')
        ttk.Button(account_row, text='刷新时长', command=self.refresh_member,style='SPGame.Compact.TButton').pack(side='right', padx=8)
        self.member_var = tk.StringVar(value='可用时长：暂未获取　　试用：暂未获取')
        ttk.Label(account, textvariable=self.member_var, style='SPGame.CardMuted.TLabel').pack(anchor='w', pady=(5, 0))
        footer=ttk.Frame(outer);footer.pack(side='bottom',fill='x')
        body = ttk.Frame(outer); body.pack(fill='both', expand=True)
        body.columnconfigure(1, weight=1); body.rowconfigure(0, weight=1)
        devices = ttk.Frame(body, style='SPGame.Card.TFrame', padding=16, width=210)
        devices.grid(row=0, column=0, rowspan=2, sticky='nsew', padx=(0, 14)); devices.grid_propagate(False)
        ttk.Label(devices, text='共享给谁', style='SPGame.CardTitle.TLabel').pack(anchor='w')
        ttk.Label(devices, text='勾选允许接入的设备', style='SPGame.CardMuted.TLabel').pack(anchor='w', pady=(5, 12))
        self.device_vars = {}
        self.cards = ttk.Frame(devices, style='SPGame.Card.TFrame'); self.cards.pack(fill='both', expand=True)
        self.device_entry = tk.StringVar()
        ttk.Button(devices, text='管理设备', command=self.manage_devices).pack(fill='x', pady=(12, 0))
        self.rebuild_devices()
        self.library_grid = GameGrid(body,self,self.library)
        self.library_grid.grid(row=0,column=1,sticky='nsew')
        choose = ttk.Frame(body, style='SPGame.Card.TFrame', padding=10); choose.grid(row=1, column=1, sticky='ew',pady=(8,0))
        selected_heading = ttk.Frame(choose,style='SPGame.Card.TFrame');selected_heading.pack(fill='x',pady=(0,4))
        self.selected_title_var = tk.StringVar(value='请选择一个游戏')
        ttk.Label(selected_heading,textvariable=self.selected_title_var,style='SPGame.CardTitle.TLabel',wraplength=580).pack(side='left')
        row = ttk.Frame(choose, style='SPGame.Card.TFrame'); row.pack(fill='x')
        row.columnconfigure(0, weight=1); row.columnconfigure(1, weight=1)
        self.area_var = tk.StringVar(); self.line_var = tk.StringVar()
        ttk.Label(row, text='区服', style='SPGame.CardMuted.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 5))
        self.area = ttk.Combobox(row, textvariable=self.area_var, state='readonly', width=18); self.area.grid(row=1, column=0, sticky='ew', padx=(0, 10))
        self.area.bind('<<ComboboxSelected>>', lambda _: self.fetch_lines())
        ttk.Label(row, text='线路', style='SPGame.CardMuted.TLabel').grid(row=0, column=1, sticky='w', pady=(0, 5))
        self.line = ttk.Combobox(row, textvariable=self.line_var, state='readonly', width=24); self.line.grid(row=1, column=1, sticky='ew')
        ttk.Button(row,text='全部线路',command=self.show_all_lines,style='SPGame.Compact.TButton').grid(row=1,column=2,padx=(8,0))
        self.line.bind('<<ComboboxSelected>>',lambda _:self.save_game_profile())
        self.owner_var = tk.StringVar()
        actions = ttk.Frame(footer); actions.pack(fill='x', pady=(8, 5))
        self.start_button = ttk.Button(actions, text='启动加速与共享', style='SPGame.Accent.TButton', command=self.start)
        self.start_button.pack(side='left')
        ttk.Button(actions, text='停止共享', command=self.stop).pack(side='left', padx=10)
        ttk.Button(actions, text='停止并暂停计时', command=self.pause).pack(side='left')
        ttk.Label(actions, text='主机 UDP / NAT 尚待验证', foreground='#a06b18').pack(side='right')
        self.status_var = tk.StringVar(value='已停止 · 选择设备和游戏后启动')
        ttk.Label(footer, textvariable=self.status_var, wraplength=1050, style='SPGame.Muted.TLabel').pack(anchor='w', pady=(0, 3))
        self.entry_var = tk.StringVar()
        ttk.Label(footer, textvariable=self.entry_var, style='SPGame.Muted.TLabel').pack(anchor='w')
        if not embedded:root.protocol('WM_DELETE_WINDOW', self.close)
        self.update_account(); self.update_entry()
        self.select_game_id(self.library.selected_id)
        root.after(100, self.poll)
        root.after(200, self.refresh_member)
        root.after(60000, self.periodic_member)

    def submit(self, coroutine, success=None):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        def done(result):
            try: self.events.put(('success', success, result.result()))
            except Exception as error: self.events.put(('error', None, error_text(error)))
        future.add_done_callback(done)
        return future

    def update_account(self):
        logged = bool(self.config.get('account', {}).get('access_token'))
        self.account_var.set('鲜牛账号：' + ('已保存官方会话（待刷新确认）' if logged else '未登录'))
        borrowed = self.config.get('session_mode') == 'borrowed'
        self.owner_var.set('会话归属：' + ('复用现有 ' + self.config.get('external_session_owner', '') + '；游戏/区服/线路沿用它的当前方案。本预览不调用 start、stop 或暂停计时。' if borrowed else
            'Windows 独立管理。需先停止同账号其他入口，并在高级设置确认独占；关闭共享不会自动暂停会员计时。'))
        self.start_button.configure(text='启动现有会话共享' if borrowed else '启动加速与共享')

    def update_entry(self):
        self.entry_var.set(f"共享地址  {self.config['listen_host']}:{self.config['http_port']}   ·   SOCKS5  {self.config['socks_port']}")

    def rebuild_devices(self):
        for child in self.cards.winfo_children(): child.destroy()
        old = self.device_vars; self.device_vars = {}
        inventory = sorted(set(self.config.get('known_devices', [])) | set(self.config.get('devices', [])) | set(old))
        for i, address in enumerate(inventory):
            var = self.tk.BooleanVar(value=old[address].get() if address in old else address in self.config.get('devices', []))
            self.device_vars[address] = var
            name = self.config.get('device_names', {}).get(address, '')
            self.ttk.Checkbutton(self.cards, text=(name+'\n' if name else '')+address, variable=var, style='SPGame.Card.TCheckbutton').grid(row=i, column=0, sticky='w', pady=4)
        if not inventory: self.ttk.Label(self.cards, text='还没有设备\n点击下方添加', style='SPGame.CardMuted.TLabel').pack(anchor='w')

    def manage_devices(self):
        dialog = self.tk.Toplevel(self.root); dialog.title('管理共享设备'); dialog.geometry('500x200')
        frame = self.ttk.Frame(dialog, padding=20); frame.pack(fill='both', expand=True)
        self.ttk.Label(frame, text='输入设备当前的 IPv4，或读取邻居缓存').pack(anchor='w', pady=(0, 12))
        self.ttk.Entry(frame, textvariable=self.device_entry, width=30).pack(fill='x')
        actions = self.ttk.Frame(frame); actions.pack(fill='x', pady=14)
        self.ttk.Button(actions, text='添加设备', command=self.add_device).pack(side='left')
        self.ttk.Button(actions, text='读取邻居', command=self.discover).pack(side='left', padx=8)
        self.ttk.Button(actions, text='完成', command=dialog.destroy).pack(side='right')

    def add_device(self):
        if self.busy or self.provider:
            self.status_var.set('请先停止共享，再修改设备'); return
        import ipaddress
        try:
            address = str(ipaddress.IPv4Address(self.device_entry.get().strip()))
            if not ipaddress.ip_address(address).is_private: raise ValueError()
            self.config.setdefault('known_devices', []).append(address)
            self.rebuild_devices(); self.device_entry.set('')
        except ValueError: self.status_var.set('请输入有效的局域网 IPv4 地址')

    def discover(self):
        if self.busy or self.provider:
            self.status_var.set('请先停止共享，再修改设备'); return
        async def read():
            def collect():
                result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                    "Get-NetNeighbor -AddressFamily IPv4 | Where-Object {$_.State -in 'Reachable','Stale','Delay'} | Select-Object -ExpandProperty IPAddress | ConvertTo-Json -Compress"],
                    capture_output=True, timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                values = json.loads(result.stdout.decode('utf-8-sig') or '[]')
                return [values] if isinstance(values, str) else values
            return await asyncio.to_thread(collect)
        def accepted(values):
            import ipaddress
            self.config['known_devices'] = sorted(set(self.config.get('known_devices', [])) | {x for x in values if ipaddress.ip_address(x).is_private and not ipaddress.ip_address(x).is_link_local})
            self.rebuild_devices(); self.status_var.set('已读取邻居缓存；在线状态与设备名称需自行核对。')
        self.submit(read(), accepted)

    def filter_games(self):
        self.library_grid.reset()

    def select_game_id(self, identity):
        self.line_sequence += 1
        self.selected_game = self.library.by_id.get(identity)
        self.lines, self.all_lines = [], []
        self.line['values']=[];self.line_var.set('请选择区服');self.line.configure(state='disabled')
        if not self.selected_game:
            self.areas=[];self.area['values']=[];self.selected_title_var.set('请选择一个游戏');return
        self.selected_title_var.set(self.selected_game['title'])
        self.areas = self.selected_game['areas']
        self.area['values'] = [str(r.get('title') or r.get('name') or r['id']) for r in self.areas]
        saved=self.config.get('game_profiles',{}).get(str(identity),{})
        preferred=saved.get('area_id',self.config['profile']['area_id'] if identity==self.config['game_id'] else None)
        index = next((i for i, r in enumerate(self.areas) if r['id'] == preferred), 0)
        if self.areas: self.area.current(index)
        if hasattr(self, 'line_refresh_timer'):
            self.root.after_cancel(self.line_refresh_timer)
        self.line_refresh_timer = self.root.after(400, self.fetch_lines)

    def fetch_lines(self):
        if hasattr(self,'line_refresh_timer'):
            self.root.after_cancel(self.line_refresh_timer)
            del self.line_refresh_timer
        if not self.areas or not self.config.get('account',{}).get('access_token') or self.closing: return
        game, area = self.selected_game['id'], self.areas[self.area.current()]['id']
        self.line_sequence += 1
        sequence = self.line_sequence
        self.lines, self.all_lines = [], []
        self.line['values']=[];self.line_var.set('正在获取官方线路…');self.line.configure(state='disabled')
        async def read(): return await asyncio.to_thread(self.catalog.lines, game, area)
        def accepted(data):
            if sequence != self.line_sequence or not self.selected_game or self.selected_game['id'] != game or self.areas[self.area.current()]['id'] != area: return
            self.lines = data['lines']; self.line['values'] = [r['title'] for r in self.lines]
            self.all_lines = data.get('all_lines',[])
            if self.lines:
                saved=self.config.get('game_profiles',{}).get(str(game),{})
                preferred=saved.get('line_id') if saved.get('area_id')==area else self.config['profile']['line_id'] if game==self.config['game_id'] and area==self.config['profile']['area_id'] else None
                self.line.current(next((i for i, r in enumerate(self.lines) if r['id'] == preferred), 0))
                self.line.configure(state='readonly')
            else:self.line_var.set('当前区服暂无可用线路')
            self.status_var.set(f"已选择 {self.selected_game['title']} · {len(self.lines)} 条适用线路")
        self.submit(read(), accepted)

    def save_game_profile(self):
        if not self.selected_game or not self.lines or self.line.current()<0 or self.area.current()<0:return
        self.config.setdefault('game_profiles',{})[str(self.selected_game['id'])]={'area_id':self.areas[self.area.current()]['id'],'line_id':self.lines[self.line.current()]['id']}
        self.store.save(self.config)

    def sync_catalog(self,path=None):
        if self.busy or self.provider:
            self.status_var.set('请先停止共享，再同步目录');return
        self.busy=True
        self.status_var.set('正在读取鲜牛客户端的完整游戏目录…')
        async def read():return await asyncio.to_thread(self.repository.sync,path)
        def accepted(games):
            self.busy=False
            if path:
                self.config['official_catalog_path']=str(path);self.store.save(self.config)
            self.games=games;self.library.replace(games);self.library_grid.reset()
            self.select_game_id(self.library.selected_id)
            self.status_var.set(f'已从鲜牛客户端读取完整目录：{len(games):,} 款。同步目录不会启动计时。')
        self.submit(read(),accepted)

    def choose_catalog_file(self):
        if self.busy or self.provider:return
        from tkinter import filedialog
        path=filedialog.askopenfilename(parent=self.root,title='选择鲜牛公开游戏目录 gamelist.xml',filetypes=[('鲜牛游戏目录','gamelist.xml'),('XML 文件','*.xml')])
        if path:self.sync_catalog(path)

    def show_all_lines(self):
        dialog=self.tk.Toplevel(self.root);dialog.title('官方完整线路');dialog.geometry('920x430')
        frame=self.ttk.Frame(dialog,padding=16);frame.pack(fill='both',expand=True)
        self.ttk.Label(frame,text=self.selected_game['title'] if self.selected_game else '请先选择游戏',style='SPGame.CardTitle.TLabel').pack(anchor='w',pady=(0,10))
        columns=('title','compatible','entry','exit','isp')
        tree=self.ttk.Treeview(frame,columns=columns,show='headings',selectmode='browse')
        for key,title,width in [('title','线路',220),('compatible','当前区服',90),('entry','入口',150),('exit','出口',150),('isp','运营商',150)]:
            tree.heading(key,text=title);tree.column(key,width=width,minwidth=70)
        tree.pack(fill='both',expand=True)
        for row in self.all_lines:tree.insert('', 'end',iid=str(row['id']),values=(row['title'],'适用' if row['compatible'] else '不适用',row.get('entry',''),row.get('exit',''),row.get('isp','') or row.get('provider','')))
        def choose():
            if self.busy or self.provider:self.status_var.set('请先停止共享，再切换线路');return
            selected=tree.selection()
            if not selected:return
            identity=int(selected[0])
            index=next((i for i,row in enumerate(self.lines) if row['id']==identity),None)
            if index is None:self.status_var.set('这条线路不适用于当前区服');return
            self.line.current(index);self.save_game_profile();dialog.destroy()
        self.ttk.Button(frame,text='使用所选线路',command=choose).pack(anchor='e',pady=(12,0))
        tree.bind('<Double-1>',lambda _:choose())

    def refresh_member(self):
        if not self.config.get('account', {}).get('access_token') or self.closing: return
        async def read():
            if self.provider: return await self.provider.member_refresh()
            # Account read does not start a session or recover paid timing.
            from xianniu_router.control import call_api
            from xianniu_router.member_time import balances
            data = await asyncio.to_thread(call_api, copy.deepcopy(self.config), '/client/member/details',
                                          {'access_token': self.config['account']['access_token']})
            return {**balances(data), 'pause_state': data.get('pause_state'), 'updated_at': int(time.time())}
        self.submit(read(), self.show_member)

    def show_member(self, member):
        self.account_var.set('鲜牛账号：官方会话已确认')
        stamp = time.strftime('%H:%M:%S', time.localtime(member.get('updated_at', time.time())))
        paused = '暂停' if member.get('pause_state') in (0, '0') else '计时中' if member.get('pause_state') is not None else '未知'
        self.member_var.set(f"官方剩余：{duration(member.get('remaining_seconds'))}　试用：{duration(member.get('trial_seconds'))}　{paused}　查询 {stamp}")

    def periodic_member(self):
        self.refresh_member()
        self.root.after(60000, self.periodic_member)

    def login(self):
        if self.busy or self.provider:
            self.status_var.set('请先停止共享，再切换账号'); return
        if self.config.get('external_session_owner'):
            self.status_var.set('当前复用其他入口会话。登录前先在高级设置解除复用，并核对同账号会话归属。'); return
        self.qr_generation += 1
        generation = self.qr_generation
        dialog = self.tk.Toplevel(self.root); dialog.title('鲜牛官方微信登录'); dialog.geometry('430x510')
        label = self.ttk.Label(dialog, text='正在获取官方二维码…'); label.pack(pady=12)
        image_label = self.ttk.Label(dialog); image_label.pack(pady=8)
        self.ttk.Label(dialog, text='请自行扫码并在微信确认。\n授权结果只保存在当前 Windows 用户私有目录。', justify='center').pack()
        def closed():
            self.qr_generation += 1; dialog.destroy()
        dialog.protocol('WM_DELETE_WINDOW', closed)
        def show_image(data):
            if generation != self.qr_generation: return
            import base64
            image_label.image = self.tk.PhotoImage(data=base64.b64encode(data).decode('ascii'))
            image_label.configure(image=image_label.image)
            label.configure(text='请用微信扫描鲜牛官方二维码')
        async def flow():
            from xianniu_router.auth_web import create_qr, poll_qr
            from xianniu_router.auth_api import authenticate, authorization_code
            state, image = await asyncio.to_thread(create_qr, self.config['dns_server'])
            self.events.put(('success', show_image, image))
            while generation == self.qr_generation:
                result = await asyncio.to_thread(poll_qr, state)
                if generation != self.qr_generation: return None
                if result['status'] == 'authorized':
                    account = await asyncio.to_thread(authenticate, copy.deepcopy(self.config), 'other', {'code': authorization_code(result)})
                    return account
                if result['status'] in ('expired', 'cancelled'):
                    raise ValueError('二维码已过期或已取消，请关闭后重新扫码')
                await asyncio.sleep(2)
        def accepted(account):
            if not account or generation != self.qr_generation: return
            self.config['account'] = {'access_token': account['access_token']}
            self.config['login_info'] = {'method': 'wechat', 'at': int(time.time())}
            self.store.save(self.config); closed(); self.update_account(); self.refresh_member()
        self.submit(flow(), accepted)

    def advanced(self):
        if self.busy or self.provider:
            self.status_var.set('请先停止共享，再修改高级设置'); return
        dialog = self.tk.Toplevel(self.root); dialog.title('鲜牛共享设置'); dialog.geometry('700x560')
        frame = self.ttk.Frame(dialog, padding=18); frame.pack(fill='both', expand=True)
        fields = {}
        for i, (key, title) in enumerate([('listen_host', '电脑当前 LAN IPv4（127.0.0.1 为仅本机）'), ('http_port', 'HTTP 端口'), ('socks_port', 'SOCKS5 端口'), ('dns_server', '实际局域网 DNS')]):
            self.ttk.Label(frame, text=title).grid(row=i, column=0, sticky='w', pady=8)
            var = self.tk.StringVar(value=str(self.config[key])); fields[key] = var
            self.ttk.Entry(frame, textvariable=var, width=25).grid(row=i, column=1, padx=12)
        exclusive = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(frame, variable=exclusive, text='我已在其他入口停止同账号会话，改由 Windows 独占管理').grid(row=4, column=0, columnspan=2, sticky='w', pady=12)
        self.ttk.Label(frame, text='此选项会解除“复用现有会话”，但不会替你停止 N1 或官方客户端。\n停止与暂停计时不同；本预览不会自动暂停全账号时长。\n热点/ICS 会引入新子网、DHCP 与 NAT，当前不自动启用。', wraplength=600).grid(row=5, column=0, columnspan=2, sticky='w')
        def save():
            import ipaddress
            try:
                updated = copy.deepcopy(self.config)
                updated.update({key: (int(var.get()) if key.endswith('_port') else var.get().strip()) for key, var in fields.items()})
                ipaddress.IPv4Address(updated['listen_host']); ipaddress.IPv4Address(updated['dns_server'])
                if exclusive.get():
                    updated['session_mode'] = 'managed'; updated.pop('external_session_owner', None)
                updated['exclusive_confirmed'] = exclusive.get()
                self.store.save(updated); self.config.clear(); self.config.update(updated)
                self.update_account(); self.update_entry(); dialog.destroy()
            except Exception as error: self.status_var.set(error_text(error))
        self.ttk.Button(frame, text='保存独立预览设置', command=save).grid(row=6, column=0, columnspan=2, pady=18)
        def firewall():
            if not getattr(sys, 'frozen', False):
                self.status_var.set('入站规则助手位于可安装预览包中'); return
            # User initiates this optional step and handles the Windows UAC prompt.
            os.startfile(str(Path(sys.executable).parent / ('AllowStarPassGamesLan.cmd' if self.embedded else 'AllowLan.cmd')))
        self.ttk.Button(frame, text='局域网入站规则（需管理员）', command=firewall).grid(row=7, column=0, columnspan=2)
        self.ttk.Label(frame, textvariable=self.owner_var, wraplength=640).grid(row=8, column=0, columnspan=2, sticky='w', pady=14)
        self.ttk.Label(frame, text='Steam 商店明确域名默认直连。手动 HTTP 代理只带入遵循代理的 TCP，\n完整游戏 UDP 需要实际入口。其他目标经鲜牛，失败不会改走其他出口。').grid(row=9, column=0, columnspan=2, sticky='w')

    def start(self):
        if self.busy or self.provider: return
        self.busy = True
        try:
            if not self.selected_game or not self.areas:raise ValueError('请先从游戏库选择游戏和区服')
            self.save_game_profile()
            config = copy.deepcopy(self.config)
            config['devices'] = [ip for ip, var in self.device_vars.items() if var.get()]
            if config['session_mode'] == 'borrowed' and (self.selected_game['id'] != config['game_id'] or self.areas[self.area.current()]['id'] != config['profile']['area_id']):
                raise ValueError('复用会话只能使用原入口的游戏和区服；切换方案请在原入口操作')
            if config['session_mode'] == 'managed':
                if not self.lines or self.line.current() < 0: raise ValueError('请先获取并选择官方线路')
                config['game_id'] = self.selected_game['id']
                config['profile'] = {'area_id': self.areas[self.area.current()]['id'], 'line_id': self.lines[self.line.current()]['id'], 'isp_type': 3}
            self.config.clear(); self.config.update(config); self.store.save(config)
        except Exception as error:
            self.busy = False; self.status_var.set(error_text(error)); return
        self.status_var.set('正在检查端口、会话归属并准备共享…')
        async def launch():
            provider = Provider(config, self.store)
            await provider.start(exclusive=config.get('exclusive_confirmed', False))
            return provider
        def accepted(provider):
            self.provider = provider; self.busy = False
            self.status_var.set('共享入口已就绪；请让目标设备显式接入。等待真实转发验证。')
        self.submit(launch(), accepted)

    def stop(self):
        if self.busy:
            self.status_var.set('正在完成会话操作，完成后可停止'); return
        if not self.provider: return
        self.busy = True
        provider = self.provider
        async def end():
            await provider.stop()
            return provider.status()
        def accepted(status):
            self.provider = None; self.busy = False
            self.status_var.set(status['last_error'] or '共享已停止，监听和连接已关闭。官方计时未自动暂停。')
        self.submit(end(), accepted)

    def poll(self):
        for _ in range(50):
            try: kind, callback, value = self.events.get_nowait()
            except queue.Empty: break
            if kind == 'error':
                self.busy = False; self.status_var.set(value)
            elif callback: callback(value)
        locked=self.busy or self.provider is not None
        self.start_button.configure(state='disabled' if locked else 'normal')
        self.area.configure(state='disabled' if locked or not self.areas else 'readonly')
        self.line.configure(state='disabled' if locked or not self.lines else 'readonly')
        self.library_grid.sync_button.configure(state='disabled' if locked else 'normal')
        for widget in self.cards.winfo_children():
            if widget.winfo_class()=='TCheckbutton':widget.configure(state='disabled' if locked else 'normal')
        if self.provider and not self.busy:
            status = self.provider.status()
            c = status['counters']
            self.status_var.set(status['last_error'] or f"{'共享运行中' if status['running'] else '共享已停止'}　鲜牛 TCP {c['tcp_connections']}　UDP 包 {c['udp_packets']}　发送 {c['sent']} B / 接收 {c['received']} B　续期 {status['renewals']} 次；游戏/NAT 待验收")
            if status['member']: self.show_member(status['member'])
        if self.closing and not self.busy:
            if self.provider:
                self.stop()
            else:
                self.loop.call_soon_threadsafe(self.loop.stop)
                self.store.unlock()
                self.closed=True
                self.root.destroy(); return
        self.root.after(200, self.poll)

    def pause(self):
        if self.busy or not self.provider:
            self.status_var.set('请在本预览独占会话运行时使用“停止并暂停计时”'); return
        self.busy = True
        def accepted(member):
            self.provider = None; self.busy = False
            self.show_member(member); self.status_var.set('本预览共享已停止，官方已确认暂停账号计时。')
        self.submit(self.provider.stop_and_pause(), accepted)

    def close(self):
        self.qr_generation += 1
        self.closing = True
        self.status_var.set('正在停止本预览拥有的连接与会话…')


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='strict')
    parser = argparse.ArgumentParser(description='StarPass Xianniu Windows preview')
    parser.add_argument('--private-dir', type=Path)
    parser.add_argument('--import-private', type=Path)
    parser.add_argument('--borrowed-owner')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--seconds', type=int, default=300)
    parser.add_argument('--exclusive', action='store_true')
    parser.add_argument('--smoke-test', action='store_true')
    args = parser.parse_args(argv)
    if args.smoke_test:
        from .storage import crypt
        sample = b'fixture-only'
        assert crypt(crypt(sample), True) == sample
        assert len(json.loads(catalog_path().read_text(encoding='utf-8'))) > 1000
        import tkinter
        import ssl
        context = ssl.create_default_context()
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        tkinter.Tcl().eval('info patchlevel')
        print(json.dumps({'smoke': True, 'version': __version__, 'dpapi': True, 'catalog': True, 'tcl': True, 'tls_context':True}))
        return 0
    store = Store(args.private_dir)
    try: store.lock()
    except Exception as error:
        print(error_text(error)); return 1
    if args.import_private:
        value = json.loads(args.import_private.read_text(encoding='utf-8-sig'))
        old = store.load()
        allowed = ('account', 'auth', 'node', 'hardware', 'game_id', 'profile', 'dns_server', 'login_info')
        old.update({k: value[k] for k in allowed if k in value})
        for key in ('listen_host', 'http_port', 'socks_port', 'devices', 'known_devices'):
            if key in value: old[key] = value[key]
        old.update(client_os_info='StarPass Windows Preview', client_os_version='Windows')
        if args.borrowed_owner:
            old.update(session_mode='borrowed', external_session_owner=args.borrowed_owner, exclusive_confirmed=False)
        else:
            old.update(session_mode='managed', exclusive_confirmed=False)
            old.pop('external_session_owner', None)
        store.save(old)
        print(json.dumps({'imported_private': True, 'session_mode': old['session_mode']}))
        return 0
    if args.headless:
        if not 10 <= args.seconds <= 86400: parser.error('--seconds must be 10..86400')
        async def serve():
            provider = Provider(store.load(), store)
            try:
                await provider.start(exclusive=args.exclusive)
                for _ in range((args.seconds + 4) // 5):
                    print(json.dumps(provider.status(), ensure_ascii=True), flush=True)
                    await asyncio.sleep(min(5, args.seconds))
            finally:
                await provider.stop()
                print(json.dumps({'stopped': provider.status()}, ensure_ascii=True), flush=True)
        try: asyncio.run(serve()); return 0
        except Exception as error: print(error_text(error), flush=True); return 1
    import tkinter as tk
    root = tk.Tk()
    App(root, store)
    root.mainloop()
    return 0
