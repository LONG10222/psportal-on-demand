"""Lazy in-window accelerator workspace; normal StarPass modes remain untouched."""
import queue
import threading
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk

from .accelerator_registry import PROVIDERS,discover,launch_client
from . import product_modes


class GamesHub:
    def __init__(self,host,frame):
        self.host,self.frame=host,frame
        self.xianniu=None
        self.closed=False
        self.selected='xianniu'
        self.events=queue.Queue()
        self.providers={row['key']:row for row in discover({'installations':[],'processes':[]})}
        frame.rowconfigure(1,weight=1)
        header=ttk.Frame(frame,style='Portal.Page.TFrame');header.grid(row=0,column=0,sticky='ew',pady=(0,10))
        self.buttons={}
        ttk.Label(header,text='游戏加速',style='Portal.Section.TLabel').pack(side='left',padx=(0,16))
        self.mode_var=tk.StringVar(value=self.host.view.tr('Accelerator mode'))
        self.mode_combo=ttk.Combobox(header,textvariable=self.mode_var,state='readonly',width=12,
            values=tuple(self.host.view.tr(product_modes.LABELS[m]) for m in product_modes.MODES))
        self.mode_combo.pack(side='left',padx=(0,12));self.mode_combo.current(3)
        self.mode_combo.bind('<<ComboboxSelected>>',self.change_mode)
        for spec in PROVIDERS[:1]:
            button=ttk.Button(header,text=spec.title+(' · 内置' if spec.built_in else ' · 客户端'),command=lambda key=spec.key:self.select(key))
            button.pack(side='left',padx=(0,8));self.buttons[spec.key]=button
        more=ttk.Menubutton(header,text='更多')
        menu=tk.Menu(more,tearoff=False)
        menu.add_command(label='鲜牛',command=lambda:self.select('xianniu'))
        menu.add_command(label='网易 UU 客户端联动',command=lambda:self.select('uu'))
        menu.add_command(label='雷神客户端联动',command=lambda:self.select('leigod'))
        menu.add_separator();menu.add_command(label='检测已安装加速器',command=self.detect)
        more.configure(menu=menu);more.pack(side='right')
        ttk.Button(header,text='设置',command=self.settings).pack(side='right',padx=8)
        self.body=tk.Frame(frame,background='#f4f6fa');self.body.grid(row=1,column=0,sticky='nsew')
        self.native_frame=tk.Frame(self.body,background='#f4f6fa')
        self.linked_frame=ttk.Frame(self.body,padding=22,style='Portal.Card.TFrame')
        self.title=tk.StringVar();self.description=tk.StringVar();self.status=tk.StringVar()
        ttk.Label(self.linked_frame,textvariable=self.title,style='Portal.Section.TLabel').pack(anchor='w')
        ttk.Label(self.linked_frame,textvariable=self.status,style='Portal.CardNote.TLabel').pack(anchor='w',pady=12)
        ttk.Label(self.linked_frame,textvariable=self.description,wraplength=700,style='Portal.CardNote.TLabel').pack(anchor='w',pady=(0,18))
        self.open_button=ttk.Button(self.linked_frame,text='打开官方客户端',command=self.open_client);self.open_button.pack(anchor='w')
        ttk.Button(self.linked_frame,text='使用客户端明确提供的标准代理入口（高级）',command=self.standard_proxy).pack(anchor='w',pady=12)
        ttk.Label(self.linked_frame,text='尚未确认公开的可嵌入引擎或账号/游戏库接口。检测安装与打开客户端，不代表 TCP/UDP 已被星渡接管。',wraplength=700,style='Portal.CardNote.TLabel').pack(anchor='w',pady=(8,0))
        self.select('xianniu')
        self.detect()
        frame.after(150,self.poll)

    @property
    def running(self):return bool(self.xianniu and (self.xianniu.busy or self.xianniu.provider))

    def change_mode(self,event=None):
        mode=('game','mixed','clash','accelerator')[self.mode_combo.current()]
        if getattr(self.host.workspace_hub,'independent_services',False):
            self.host.open_workspace({'game':'game','mixed':'subscription','clash':'clash','accelerator':'accelerator'}[mode]);return
        self.host.set_product_mode(mode)
        if self.host.product_mode()=='accelerator':self.mode_combo.current(3)

    def refresh_mode(self):
        self.mode_combo.configure(values=tuple(self.host.view.tr(product_modes.LABELS[m]) for m in product_modes.MODES))
        self.mode_combo.current(3 if getattr(self.host.workspace_hub,'independent_services',False) else product_modes.MODES.index(self.host.product_mode()))

    def select(self,key):
        if self.running and key!=self.selected:
            self.host.view.subtitle.set('请先停止当前游戏共享，再切换加速器');return
        self.selected=key
        if self.xianniu:self.xianniu.active=key=='xianniu'
        self.native_frame.pack_forget();self.linked_frame.pack_forget()
        if key=='xianniu':
            self.native_frame.pack(fill='both',expand=True)
            if self.xianniu is None:
                store=None
                try:
                    if not getattr(sys,'frozen',False):
                        repo=Path(__file__).resolve().parents[2]
                        for source in ('xianniu-windows','xianniu-router'):
                            path=str(repo/'integrations'/source/'src')
                            if path not in sys.path:sys.path.insert(0,path)
                    from starpass_xianniu.storage import Store
                    from starpass_xianniu.app import App
                    store=Store();store.lock()
                    self.xianniu=App(self.native_frame,store,embedded=True)
                    self.apply_theme()
                except Exception:
                    if store:store.unlock()
                    ttk.Label(self.native_frame,text='内置鲜牛暂不可用。请关闭独立预览后重试，并确认使用了完整星渡集成包。',wraplength=650).pack(padx=20,pady=20)
        else:
            self.linked_frame.pack(fill='both',expand=True)
            row=self.providers[key]
            self.title.set(row['title']+' · 已安装客户端联动')
            self.status.set(('已检测到安装' if row['installed'] else '尚未检测到安装')+(' · 客户端运行中' if row['running'] else ''))
            self.description.set('账号登录、游戏选择、计时和主机设置暂由官方客户端管理。星渡只读取安装位置与运行状态，不读取其密码、短信或会话令牌。')
            self.open_button.configure(state='normal' if row['executables'] else 'disabled')

    def detect(self):
        def work():self.events.put(discover())
        threading.Thread(target=work,daemon=True).start()

    def apply_theme(self):
        colors=self.host.view.palette
        self.body.configure(background=colors['page']);self.native_frame.configure(background=colors['page'])
        if self.xianniu:
            from starpass_xianniu.ui_style import apply_palette
            apply_palette(self.xianniu,colors,self.host.view.font_family)

    def poll(self):
        if self.closed:return
        try:
            rows=self.events.get_nowait();self.providers={r['key']:r for r in rows}
            for row in rows:
                if row['key'] in self.buttons:self.buttons[row['key']].configure(text=row['title'])
            if self.selected!='xianniu':self.select(self.selected)
        except queue.Empty:pass
        self.frame.after(150,self.poll)

    def open_client(self):
        try:launch_client(self.providers[self.selected])
        except ValueError as error:self.status.set(str(error))

    def settings(self):
        if self.selected=='xianniu' and self.xianniu:self.xianniu.quick_settings()
        else:self.host.view.subtitle.set('当前客户端联动的账号与游戏设置请在官方客户端中完成。')

    def standard_proxy(self):
        self.host.set_product_mode('accelerator')
        self.host.view.show('Overview')
        self.host.xianniu_message='标准入口需要重新进行协议与 TLS 检查；现有通用中转仍限 Steam 网页 TCP，不能视为本品牌游戏 UDP 已适配。'
        self.host.view.refresh()

    def close(self):
        if self.xianniu and not self.xianniu.closed:self.xianniu.close()

    def shutdown_complete(self):
        self.closed=not self.xianniu or self.xianniu.closed
        return self.closed
