"""Paged game tiles, real official icons, and persistent individual selections."""
import asyncio
import hashlib
import http.client
import io
import json
import math
from pathlib import Path
import socket
import ssl
import time
import tkinter as tk
from tkinter import ttk
from urllib.parse import urlsplit

from PIL import Image, ImageOps, ImageTk
from xianniu_router.dns import resolve_real


class IconCache:
    def __init__(self, root, resolver):
        self.root, self.resolver = Path(root), resolver
        self.root.mkdir(parents=True,exist_ok=True)

    def read(self, url):
        target = urlsplit(url)
        if target.scheme != 'https' or target.hostname != 'picture.xianniu.com' or target.port not in (None,443) or target.username or target.password or not target.path.startswith('/game/'):
            return None
        path = self.root/(hashlib.sha256(url.encode()).hexdigest()+'.img')
        if path.exists():
            raw = path.read_bytes()
        else:
            address = resolve_real(target.hostname,self.resolver)
            connection = http.client.HTTPSConnection(target.hostname,timeout=5)
            try:
                sock = socket.create_connection((address,443),timeout=5)
                try: connection.sock = ssl.create_default_context().wrap_socket(sock,server_hostname=target.hostname)
                except BaseException: sock.close();raise
                connection.request('GET',target.path,headers={'User-Agent':'StarPass-GameLibrary/0.1'})
                reply = connection.getresponse()
                raw = reply.read(2*1024*1024+1)
                if reply.status != 200 or len(raw) > 2*1024*1024: return None
            finally: connection.close()
        with Image.open(io.BytesIO(raw)) as image:
            if image.width > 2048 or image.height > 2048: return None
            thumbnail = ImageOps.fit(image.convert('RGBA'),(56,56),method=Image.Resampling.LANCZOS)
        if not path.exists():
            temporary = path.with_suffix('.tmp')
            temporary.write_bytes(raw);temporary.replace(path)
            self.trim()
        return thumbnail

    def trim(self):
        files = sorted(self.root.glob('*.img'),key=lambda p:p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for path in files:
            if total <= 128*1024*1024: break
            total -= path.stat().st_size;path.unlink(missing_ok=True)


class GameGrid(ttk.Frame):
    PAGE_SIZE = 24
    def __init__(self, master, app, model):
        super().__init__(master,style='Card.TFrame',padding=12)
        self.app, self.model = app, model
        self.offset, self.generation = 0, 0
        self.icon_cache = IconCache(app.store.root/'game-icons',app.config['dns_server'])
        self.icon_slots = asyncio.Semaphore(4)
        self.pending = set()
        self.memory_icons = {}
        self.query, self.category = tk.StringVar(), tk.StringVar(value='')
        self.page_number = tk.StringVar(value='1')
        self.tiles, self.images = {}, {}
        heading = ttk.Frame(self,style='Card.TFrame');heading.pack(fill='x')
        ttk.Label(heading,text='游戏库',style='CardTitle.TLabel').pack(side='left')
        self.source_var = tk.StringVar()
        ttk.Label(heading,textvariable=self.source_var,style='CardMuted.TLabel').pack(side='left',padx=12)
        self.sync_button = ttk.Menubutton(heading,text='同步官方目录',style='Compact.TMenubutton')
        menu=tk.Menu(self.sync_button,tearoff=False)
        menu.add_command(label='读取已安装鲜牛的目录',command=app.sync_catalog)
        menu.add_command(label='选择 gamelist.xml 文件…',command=app.choose_catalog_file)
        self.sync_button.configure(menu=menu)
        self.sync_button.pack(side='right')
        tabs = ttk.Frame(self,style='Card.TFrame');tabs.pack(fill='x',pady=(8,6))
        self.tab_buttons = {}
        for key,label in [('', '全部游戏'),('mine','我的游戏'),('pc','PC'),('console','PS / Xbox'),('switch','Switch'),('recent','最近选择')]:
            button = ttk.Button(tabs,text=label,command=lambda k=key:self.set_category(k),style='Compact.TButton')
            button.pack(side='left',padx=(0,5));self.tab_buttons[key]=button
        search = ttk.Frame(self,style='Card.TFrame');search.pack(fill='x')
        ttk.Label(search,text='搜索游戏',style='CardMuted.TLabel').pack(side='left',padx=(0,8))
        self.search_entry = ttk.Entry(search,textvariable=self.query)
        self.search_entry.pack(side='left',fill='x',expand=True)
        self.search_entry.bind('<KeyRelease>',self.search_changed)
        self.search_entry.bind('<Return>',lambda _:self.reset())
        ttk.Button(search,text='清空',command=self.clear_search,style='Compact.TButton').pack(side='left',padx=(8,0))
        self.result_var = tk.StringVar()
        ttk.Label(self,textvariable=self.result_var,style='CardMuted.TLabel').pack(anchor='w',pady=(4,3))
        surface = ttk.Frame(self,style='Card.TFrame');surface.pack(fill='both',expand=True)
        self.canvas = tk.Canvas(surface,background='white',highlightthickness=0,height=300)
        scrollbar = ttk.Scrollbar(surface,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y');self.canvas.pack(side='left',fill='both',expand=True)
        self.grid_frame = tk.Frame(self.canvas,background='white')
        self.canvas_item = self.canvas.create_window((0,0),window=self.grid_frame,anchor='nw')
        self.grid_frame.bind('<Configure>',lambda _:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.canvas_item,width=e.width))
        self.canvas.bind('<MouseWheel>',self.wheel)
        pager = ttk.Frame(self,style='Card.TFrame');pager.pack(fill='x',side='bottom',before=surface,pady=(8,0))
        self.previous = ttk.Button(pager,text='上一页',command=lambda:self.change_page(-1),style='Compact.TButton');self.previous.pack(side='left')
        self.next = ttk.Button(pager,text='下一页',command=lambda:self.change_page(1),style='Compact.TButton');self.next.pack(side='left',padx=6)
        self.page_var = tk.StringVar()
        ttk.Label(pager,textvariable=self.page_var,style='CardMuted.TLabel').pack(side='left',padx=8)
        ttk.Button(pager,text='跳转',command=self.jump,style='Compact.TButton').pack(side='right')
        self.page_entry = ttk.Entry(pager,textvariable=self.page_number,width=5);self.page_entry.pack(side='right',padx=6)
        self.page_entry.bind('<Return>',lambda _:self.jump())
        app.root.bind('<Control-f>',lambda _:self.search_entry.focus_set())
        app.root.bind('<Control-l>',lambda _:self.page_entry.focus_set())
        app.root.bind('<Alt-Right>',lambda _:self.change_page(1))
        app.root.bind('<Alt-Left>',lambda _:self.change_page(-1))
        self.refresh()

    def wheel(self,event):
        self.canvas.yview_scroll(-int(event.delta/120),'units')
        return 'break'

    def search_changed(self,event=None):
        if hasattr(self,'search_timer'):self.after_cancel(self.search_timer)
        self.search_timer = self.after(200,self.reset)

    def clear_search(self): self.query.set('');self.reset()
    def reset(self): self.offset=0;self.refresh()
    def set_category(self,key):self.category.set(key);self.reset()
    def change_page(self,direction):self.offset=max(0,self.offset+direction*self.PAGE_SIZE);self.refresh()

    def jump(self):
        try:
            page = int(self.page_number.get())
            if not 1 <= page <= self.pages: raise ValueError()
            self.offset=(page-1)*self.PAGE_SIZE;self.refresh()
        except ValueError:self.app.status_var.set('请输入有效页码')

    def refresh(self):
        self.generation += 1
        try: result = self.model.page(self.query.get(),self.category.get(),self.offset,self.PAGE_SIZE)
        except ValueError as error:self.app.status_var.set(str(error));return
        self.offset = result['offset'];self.filtered = result['games']
        self.pages=max(1,math.ceil(result['total']/self.PAGE_SIZE))
        page=self.offset//self.PAGE_SIZE+1
        self.page_var.set(f'{page} / {self.pages} 页');self.page_number.set(str(page))
        self.previous.configure(state='normal' if page>1 else 'disabled')
        self.next.configure(state='normal' if page<self.pages else 'disabled')
        self.source_var.set(f"{self.app.repository.info['label']} · {len(self.model.games):,} 款")
        self.result_var.set(f"找到 {result['total']:,} 款 · 显示 {self.offset+1 if result['total'] else 0}—{self.offset+len(self.filtered)}")
        for key,button in self.tab_buttons.items():button.configure(style='SelectedTab.TButton' if key==self.category.get() else 'Compact.TButton')
        for child in self.grid_frame.winfo_children():child.destroy()
        self.tiles={};self.images={}
        for column in range(6):self.grid_frame.columnconfigure(column,weight=1,uniform='games')
        for index,game in enumerate(self.filtered):self.make_tile(game,index)
        if not self.filtered:
            tk.Label(self.grid_frame,text='还没有收藏的游戏，点击游戏卡片的 ☆ 即可添加' if self.category.get()=='mine' else '没有匹配游戏，试试简称、英文或部分名称',background='white',foreground='#64748b',pady=50).grid(column=0,row=0,columnspan=6)
        self.canvas.yview_moveto(0)

    def make_tile(self,game,index):
        identity=game['id'];selected=identity==self.model.selected_id
        color='#edf3ff' if selected else 'white'
        tile=tk.Frame(self.grid_frame,background=color,highlightthickness=1,highlightbackground='#4777e6' if selected else '#edf0f5',cursor='hand2')
        tile.grid(row=index//6,column=index%6,sticky='nsew',padx=4,pady=4)
        tile.columnconfigure(0,weight=1)
        top=tk.Frame(tile,background=color);top.grid(row=0,column=0,sticky='ew');top.columnconfigure(0,weight=1)
        favorite=identity in self.app.config.get('favorite_games',[])
        tk.Button(top,text='★' if favorite else '☆',font=('Segoe UI',10),background=color,foreground='#c68d24' if favorite else '#94a3b8',borderwidth=0,padx=4,pady=0,cursor='hand2',command=lambda:self.favorite(identity)).grid(row=0,column=1,sticky='e')
        icon=tk.Label(tile,text=game['title'][:2],font=('Microsoft YaHei UI',15,'bold'),foreground='#4970aa',background=color,width=4,height=2)
        icon.grid(row=1,column=0,pady=(0,4))
        label=tk.Label(tile,text=game['title'],font=('Microsoft YaHei UI',9),background=color,foreground='#2455ca' if selected else '#334155',wraplength=110,height=2,anchor='n')
        label.grid(row=2,column=0,sticky='ew',padx=4,pady=(0,8))
        for widget in (tile,top,icon,label):
            widget.bind('<Button-1>',lambda _,g=game:self.choose(g))
            widget.bind('<MouseWheel>',self.wheel)
        self.tiles[identity]=tile
        self.load_icon(game,icon,self.generation)

    def choose(self,game):
        if self.app.busy or self.app.provider:
            self.app.status_var.set('请先停止共享，再切换游戏');return
        self.model.select(game['id']);self.app.store.save(self.app.config)
        self.app.select_game_id(game['id'])
        self.refresh()

    def favorite(self,identity):
        self.model.toggle_favorite(identity);self.app.store.save(self.app.config);self.refresh()

    def load_icon(self,game,label,generation):
        url=game.get('icon','')
        if not url:return
        if url in self.memory_icons:
            self.show_icon(label,self.memory_icons[url],generation,game['id']);return
        if len(self.pending)>=64:return
        key=(generation,game['id']);self.pending.add(key)
        async def load():
            async with self.icon_slots:
                try:return await asyncio.to_thread(self.icon_cache.read,url)
                except Exception:return None
        def accepted(bitmap):
            self.pending.discard(key)
            if bitmap is not None:
                self.memory_icons[url]=bitmap
                if len(self.memory_icons)>192:self.memory_icons.pop(next(iter(self.memory_icons)))
                self.show_icon(label,bitmap,generation,game['id'])
        self.app.submit(load(),accepted)

    def show_icon(self,label,bitmap,generation,identity):
        if generation!=self.generation or not label.winfo_exists():return
        photo=ImageTk.PhotoImage(bitmap,master=label)
        self.images[identity]=photo
        label.configure(image=photo,text='',width=56,height=56)
