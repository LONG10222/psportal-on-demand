"""Clash-inspired local desktop layout. No networking or lifecycle ownership."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from . import i18n

PAGES = ('Overview', 'Profiles', 'Proxies', 'Rules', 'LAN sharing', 'Settings', 'Logs')
SUBTITLES = dict(zip(PAGES, (
    'A clear view of the listener, engine and device connection.',
    'Import a provider or keep using your HTTPS subscription.',
    'Choose how nodes are selected without changing engines.',
    'Inspect or import a local profile to view its original rules.',
    'Give another device an address it can connect to.',
    'Keep the complete external core and the experimental embedded option.',
    'Original diagnostics, with sensitive values redacted.',
)))


class DesktopView:
    def __init__(self, app):
        self.app = app
        self.root = root = app.root
        self.language = i18n.load_language(app.path)
        self.bindings = []
        self.theme = i18n.load_theme(app.path)
        self._preview_rendered = None
        self.page = 'Overview'
        self.core_state = 'stopped'
        self.status = 'Stopped'
        self.preview = None
        self.subscription_info = None
        self.advanced = False
        self.advanced_sections = []
        self.setup_network = ''
        self.nav = {}
        self.frames = {}
        self._styles()
        root.title('PS Portal On-Demand')
        root.geometry('1120x800')
        root.minsize(1040, 740)
        root.configure(background=self.palette['page'])
        root.protocol('WM_DELETE_WINDOW', app.close)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        sidebar = ttk.Frame(root, style='Portal.Side.TFrame', padding=(24, 30))
        sidebar.grid(row=0, column=0, sticky='nsew')
        ttk.Label(sidebar, text='ONDEMAND', style='Portal.Brand.TLabel').pack(anchor='w')
        self.label(sidebar, 'On-demand LAN proxy', style='Portal.SideNote.TLabel').pack(anchor='w', pady=(5, 35))
        self.label(sidebar, 'Workspace', style='Portal.SideNote.TLabel').pack(anchor='w', pady=(0, 10))
        for name in PAGES:
            button = self.button(sidebar, name, command=lambda p=name: self.show(p), style='Portal.Nav.TButton')
            button.pack(fill='x', pady=4, ipady=7)
            self.nav[name] = button
        self.advanced_var = tk.StringVar()
        self.advanced_button = ttk.Button(sidebar, textvariable=self.advanced_var,
            command=lambda: self.set_advanced(not self.advanced), style='Portal.Nav.TButton')
        self.advanced_button.pack(fill='x', pady=(15, 4))
        ttk.Frame(sidebar, style='Portal.Side.TFrame').pack(fill='y', expand=True)
        self.label(sidebar, 'No system proxy, DNS, VPN or firewall settings are changed.',
                   style='Portal.SideNote.TLabel', wraplength=170, justify='left').pack(anchor='w', pady=(30, 0))

        content = ttk.Frame(root, padding=(30, 24), style='Portal.Page.TFrame')
        content.grid(row=0, column=1, sticky='nsew')
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)
        header = ttk.Frame(content, style='Portal.Page.TFrame')
        header.grid(row=0, column=0, sticky='ew')
        header.columnconfigure(0, weight=1)
        self.title = tk.StringVar()
        self.subtitle = tk.StringVar()
        ttk.Label(header, textvariable=self.title, style='Portal.Title.TLabel').grid(row=0, column=0, sticky='w')
        language = ttk.Frame(header, style='Portal.Page.TFrame')
        language.grid(row=0, column=1, sticky='e')
        self.label(language, 'Language', style='Portal.Note.TLabel').pack(side='left', padx=10)
        self.language_var = tk.StringVar(value='简体中文' if self.language == 'zh' else 'English')
        self.language_combo = ttk.Combobox(language, values=('简体中文', 'English'), textvariable=self.language_var,
                                         state='readonly', width=12)
        self.language_combo.pack(side='left')
        self.language_combo.bind('<<ComboboxSelected>>', self._language_selected)
        ttk.Label(header, textvariable=self.subtitle, style='Portal.Note.TLabel', wraplength=760).grid(row=1, column=0, columnspan=2, sticky='w', pady=(8, 18))
        app.path_var = tk.StringVar(value=str(app.path))
        config_bar = ttk.Frame(content, style='Portal.Page.TFrame')
        config_bar.grid(row=1, column=0, sticky='ew', pady=(0, 18))
        self.advanced_sections.append(config_bar)
        config_bar.columnconfigure(0, weight=1)
        ttk.Label(config_bar, textvariable=app.path_var, style='Portal.Note.TLabel', wraplength=610).grid(row=0, column=0, sticky='w')
        app.choose_button = self.button(config_bar, 'Choose config…', command=app.choose_config)
        app.choose_button.grid(row=0, column=1, sticky='e')
        stage = ttk.Frame(content, style='Portal.Page.TFrame')
        stage.grid(row=2, column=0, sticky='nsew')
        stage.rowconfigure(0, weight=1); stage.columnconfigure(0, weight=1)
        for name in PAGES:
            page = ttk.Frame(stage, style='Portal.Page.TFrame')
            page.grid(row=0, column=0, sticky='nsew')
            page.columnconfigure(0, weight=1)
            self.frames[name] = page

        profile = self.card(self.frames['Profiles'], 'Subscription and provider')
        self.fields(profile, ('subscription_url', 'subscription_file', 'profile_file'))
        self.label(profile, 'Full profile preserves outbound nodes, groups and rules. This host manages only its listener and controller overlay.',
                   wraplength=680, style='Portal.CardNote.TLabel').grid(row=8, column=0, columnspan=3, sticky='w', pady=(10, 0))
        row = ttk.Frame(profile, style='Portal.Card.TFrame')
        row.grid(row=9, column=0, columnspan=3, sticky='ew', pady=14)
        self.inspect_button = self.button(row, 'Inspect local YAML', command=app.inspect_provider)
        self.inspect_button.pack(side='left')
        app.inputs.append((self.inspect_button, 'normal'))
        self.import_button = self.button(row, 'Import subscription', command=app.import_subscription)
        self.import_button.pack(side='left', padx=8)
        app.inputs.append((self.import_button, 'normal'))
        self.preview_var = tk.StringVar()
        ttk.Label(profile, textvariable=self.preview_var, style='Portal.CardNote.TLabel', wraplength=680).grid(row=10, column=0, columnspan=3, sticky='w')

        proxies = self.card(self.frames['Proxies'], 'Selection policy')
        self.fields(proxies, ('selection_mode', 'preferred_node'))
        self.label(proxies, 'HK → JP → other regions. Prefer keeps fallback; fixed never switches silently.',
                   wraplength=680, style='Portal.CardNote.TLabel').grid(row=5, column=0, columnspan=3, sticky='w', pady=16)
        self.label(proxies, 'Full profile uses its original groups and rules; provider selection fields do not override them.',
                   wraplength=680, style='Portal.CardNote.TLabel').grid(row=6, column=0, columnspan=3, sticky='w')

        inventory = self.card(self.frames['Proxies'], 'Node inventory', row=1, padding=(24, 16))
        self.node_table = self.table(inventory, ('Name', 'Protocol'), height=4)
        self.label(inventory, 'Local file preview only. First 500 entries; no latency test or node switch is performed.',
                   wraplength=680, style='Portal.CardNote.TLabel').grid(row=2, column=0, columnspan=3, sticky='w', pady=(12, 0))
        rules = self.card(self.frames['Rules'], 'Imported rules')
        self.rule_table = self.table(rules, ('Imported rules',), height=12)
        self.label(rules, 'Local file preview only. First 500 entries; no latency test or node switch is performed.',
                   wraplength=680, style='Portal.CardNote.TLabel').grid(row=2, column=0, columnspan=3, sticky='w', pady=(12, 0))

        guide = self.card(self.frames['LAN sharing'], 'Device Wi-Fi setup')
        self.guide_var = tk.StringVar()
        ttk.Label(guide, textvariable=self.guide_var, style='Portal.CardTitle.TLabel', wraplength=680,
                  justify='left').grid(row=1, column=0, columnspan=3, sticky='w', pady=(0, 16))
        self.label(guide, 'Join the same Wi-Fi. In the device Wi-Fi settings choose HTTP Proxy → Manual, enter the server and port above, and leave authentication off.',
                   wraplength=680, style='Portal.CardNote.TLabel', justify='left').grid(row=2, column=0, columnspan=3, sticky='w')
        actions = ttk.Frame(guide, style='Portal.Card.TFrame')
        actions.grid(row=3, column=0, columnspan=3, sticky='w', pady=(18, 0))
        self.button(actions, 'Copy address', command=app.copy_address).pack(side='left')
        self.button(actions, 'Export connection guide…', command=app.export_guide).pack(side='left', padx=8)
        share = self.card(self.frames['LAN sharing'], 'Access control', row=1, padding=(24, 16))
        self.advanced_sections.append(share)
        self.fields(share, ('listen_host', 'listen_port', 'allowed_clients'))
        self.label(share, 'Devices must support manual HTTP proxy settings. UDP and traffic that ignores proxy settings are not included.',
                   wraplength=680, style='Portal.CardNote.TLabel').grid(row=6, column=0, columnspan=3, sticky='w', pady=15)
        row = ttk.Frame(share, style='Portal.Card.TFrame')
        row.grid(row=7, column=0, columnspan=3, sticky='w')
        self.button(row, 'Copy address', command=app.copy_address).pack(side='left')
        self.button(row, 'Export connection guide…', command=app.export_guide).pack(side='left', padx=8)
        self.button(row, 'Export Clash client…', command=app.export_client).pack(side='left')

        settings = self.card(self.frames['Settings'], 'Engine configuration')
        self.fields(settings, ('engine_mode', 'core_path', 'native_path', 'idle_seconds', 'backend_port', 'api_port'))
        app.mode_note_var = tk.StringVar()
        ttk.Label(settings, textvariable=app.mode_note_var, style='Portal.CardNote.TLabel', wraplength=690).grid(row=9, column=0, columnspan=3, sticky='w', pady=(14, 4))
        self.label(settings, 'After all related streams close, the idle countdown begins. Active streams protect the core.',
                   wraplength=690, style='Portal.CardNote.TLabel').grid(row=10, column=0, columnspan=3, sticky='w')

        self.label(settings, 'Appearance').grid(row=11, column=0, sticky='w', pady=(18, 0))
        self.theme_var = tk.StringVar()
        self.theme_combo = ttk.Combobox(settings, textvariable=self.theme_var, state='readonly', width=18)
        self.theme_combo.grid(row=11, column=1, sticky='w', pady=(18, 0))
        self.theme_combo.bind('<<ComboboxSelected>>', lambda _: app.set_theme(
            'dark' if self.theme_combo.current() == 0 else 'light'))

        self._overview()

        logs = self.frames['Logs']; logs.rowconfigure(0, weight=1)
        app.log_widget = ScrolledText(logs, height=16, state='disabled', wrap='word',
            background='#101a30', foreground='#dce5f4', insertbackground='white',
            relief='flat', borderwidth=0, padx=18, pady=16, font=('Menlo', 11))
        app.log_widget.grid(row=0, column=0, sticky='nsew')
        self.label(logs, 'Original diagnostics, with sensitive values redacted.', style='Portal.Note.TLabel').grid(row=1, column=0, sticky='w', pady=12)

        footer = ttk.Frame(content, style='Portal.Page.TFrame')
        footer.grid(row=3, column=0, sticky='ew', pady=(18, 0))
        app.save_button = self.button(footer, 'Save / validate', command=app.save)
        app.save_button.pack(side='left')
        app.start_button = self.button(footer, 'Start listener', command=app.start, style='Portal.Accent.TButton')
        app.start_button.pack(side='left', padx=10)
        app.stop_button = self.button(footer, 'Stop', command=app.stop, state='disabled')
        app.stop_button.pack(side='left')
        app.status_var = tk.StringVar()
        ttk.Label(footer, textvariable=app.status_var, style='Portal.Status.TLabel').pack(side='right')
        self.refresh()
        self.set_advanced(False)
        self.show('Overview')

    def _styles(self):
        dark = self.theme == 'dark'
        self.palette = c = dict(
            page='#1e202a' if dark else '#f5f7fb',
            side='#2c2f3b' if dark else '#edf1f8',
            card='#262935' if dark else '#ffffff',
            text='#edf0f7' if dark else '#172541',
            note='#a7afc2' if dark else '#65748c',
            entry='#232632' if dark else '#f7f9fd',
            edge='#454b60' if dark else '#dce3ef',
            selected='#304f7d' if dark else '#dde8ff',
            hover='#373e52' if dark else '#e0e8f8',
            button='#323747' if dark else '#e9eef8',
            accent='#3189fa')
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=('Helvetica Neue', 12), background=c['card'], foreground=c['text'])
        for name, bg in (('Page', 'page'), ('Side', 'side'), ('Card', 'card')):
            style.configure('Portal.' + name + '.TFrame', background=c[bg])
        style.configure('Portal.Title.TLabel', background=c['page'], foreground=c['text'], font=('Helvetica Neue', 25, 'bold'))
        style.configure('Portal.Brand.TLabel', background=c['side'], foreground=c['accent'], font=('Helvetica Neue', 18, 'bold'))
        style.configure('Portal.SideNote.TLabel', background=c['side'], foreground=c['note'], font=('Helvetica Neue', 11))
        style.configure('Portal.Note.TLabel', background=c['page'], foreground=c['note'])
        style.configure('Portal.Card.TLabel', background=c['card'], foreground=c['text'])
        style.configure('Portal.CardTitle.TLabel', background=c['card'], foreground=c['text'], font=('Helvetica Neue', 14, 'bold'))
        style.configure('Portal.CardNote.TLabel', background=c['card'], foreground=c['note'], font=('Helvetica Neue', 11))
        style.configure('Portal.Metric.TLabel', background=c['card'], foreground=c['text'], font=('Helvetica Neue', 19, 'bold'))
        style.configure('Portal.Status.TLabel', background=c['page'], foreground=c['accent'])
        for name, bg, fg in (('Nav', 'side', 'note'), ('Selected', 'selected', 'text')):
            style.configure('Portal.' + name + '.TButton', background=c[bg], foreground=c[fg], borderwidth=0, anchor='w', padding=(14, 10))
            style.map('Portal.' + name + '.TButton', background=[('active', c['hover'])])
        style.configure('TButton', background=c['button'], foreground=c['text'], borderwidth=0, padding=(12, 9))
        style.map('TButton', background=[('active', c['hover'])], foreground=[('disabled', c['note'])])
        style.configure('Portal.Accent.TButton', background=c['accent'], foreground='white', padding=(18, 10))
        style.map('Portal.Accent.TButton', background=[('active', '#2477e5'), ('disabled', c['button'])], foreground=[('disabled', c['note'])])
        style.configure('TEntry', padding=(9, 7), fieldbackground=c['entry'], foreground=c['text'], insertcolor=c['text'], bordercolor=c['edge'], lightcolor=c['edge'], darkcolor=c['edge'])
        style.map('TEntry', fieldbackground=[('disabled', c['card'])], foreground=[('disabled', c['note'])])
        style.configure('TCombobox', padding=(7, 6), background=c['button'], fieldbackground=c['entry'], foreground=c['text'], arrowcolor=c['text'], bordercolor=c['edge'], lightcolor=c['edge'], darkcolor=c['edge'])
        style.map('TCombobox', fieldbackground=[('readonly', c['entry']), ('disabled', c['card'])], foreground=[('disabled', c['note']), ('readonly', c['text'])], selectbackground=[('readonly', c['selected'])], selectforeground=[('readonly', c['text'])])
        style.configure('Treeview', background=c['entry'], fieldbackground=c['entry'], foreground=c['text'], borderwidth=0, rowheight=27)
        style.configure('Treeview.Heading', background=c['button'], foreground=c['note'], relief='flat', padding=7)
        style.map('Treeview', background=[('selected', c['selected'])], foreground=[('selected', c['text'])])
        style.configure('Portal.Horizontal.TProgressbar', background=c['accent'], troughcolor=c['button'],
                        lightcolor=c['accent'], darkcolor=c['accent'], borderwidth=0)
        self.root.option_add('*TCombobox*Listbox.background', c['card'])
        self.root.option_add('*TCombobox*Listbox.foreground', c['text'])
        self.root.option_add('*TCombobox*Listbox.selectBackground', c['selected'])

    def set_theme(self, theme):
        if theme not in ('dark', 'light'):
            raise ValueError('unsupported theme')
        self.theme = theme
        self._styles()
        self.root.configure(background=self.palette['page'])
        self.refresh()

    def table(self, parent, columns, height):
        frame = ttk.Frame(parent, style='Portal.Card.TFrame')
        frame.grid(row=1, column=0, columnspan=3, sticky='ew')
        frame.columnconfigure(0, weight=1)
        table = ttk.Treeview(frame, columns=columns, show='headings', height=height)
        for key in columns:
            table.heading(key, text=self.tr(key))
            table.column(key, width=220 if len(columns) > 1 else 580, minwidth=90, stretch=True)
        table.grid(row=0, column=0, sticky='ew')
        scroll = ttk.Scrollbar(frame, orient='vertical', command=table.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        table.configure(yscrollcommand=scroll.set)
        return table

    def tr(self, key, **values):
        return i18n.text(key, self.language, **values)

    def label(self, parent, key, **kwargs):
        var = tk.StringVar(value=self.tr(key))
        self.bindings.append((var, key))
        kwargs.setdefault('style', 'Portal.Card.TLabel')
        return ttk.Label(parent, textvariable=var, **kwargs)

    def button(self, parent, key, **kwargs):
        var = tk.StringVar(value=self.tr(key))
        self.bindings.append((var, key))
        return ttk.Button(parent, textvariable=var, **kwargs)

    def card(self, parent, title, row=0, padding=24):
        card = ttk.Frame(parent, padding=padding, style='Portal.Card.TFrame')
        card.grid(sticky='new', row=row, column=0, pady=(0, 16))
        card.columnconfigure(1, weight=1)
        self.label(card, title, style='Portal.CardTitle.TLabel').grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 20))
        return card

    def fields(self, parent, names):
        from .desktop import FIELDS
        titles = dict(FIELDS, profile_file='Full profile file')
        for row, key in enumerate(names, start=1):
            self.label(parent, titles[key]).grid(row=row, column=0, sticky='w', padx=(0, 18), pady=8)
            variable = tk.StringVar()
            variable.trace_add('write', self.app._changed)
            self.app.vars[key] = variable
            if key in ('selection_mode', 'engine_mode'):
                choices = ('auto', 'prefer', 'fixed') if key == 'selection_mode' else ('external', 'embedded')
                entry = ttk.Combobox(parent, textvariable=variable, values=choices, state='readonly', width=34)
                normal = 'readonly'
            else:
                entry = ttk.Entry(parent, textvariable=variable, show='•' if key == 'subscription_url' else '', width=38)
                normal = 'normal'
            entry.grid(row=row, column=1, columnspan=1 if key in ('core_path', 'native_path', 'subscription_file', 'profile_file') else 2, sticky='ew')
            self.app.inputs.append((entry, normal))
            if key in ('selection_mode', 'preferred_node'):
                self.app.profile_selection_inputs.append((entry, normal))
            if key in ('core_path', 'native_path', 'backend_port', 'api_port'):
                self.app.engine_inputs[key] = [entry]
            if key in ('core_path', 'native_path', 'subscription_file', 'profile_file'):
                command = {'core_path': self.app.choose_core, 'native_path': self.app.choose_native,
                           'subscription_file': self.app.choose_provider, 'profile_file': self.app.choose_profile}[key]
                browse = self.button(parent, 'Browse…', command=command)
                browse.grid(row=row, column=2, padx=(8, 0))
                self.app.inputs.append((browse, 'normal'))
                if key in self.app.engine_inputs:
                    self.app.engine_inputs[key].append(browse)

    def _overview(self):
        page = self.frames['Overview']
        quick = self.card(page, 'Paste your subscription to get started.')
        entry = ttk.Entry(quick, textvariable=self.app.vars['subscription_url'], show='•')
        entry.grid(row=1, column=0, columnspan=2, sticky='ew', padx=(0, 12))
        quick.columnconfigure(0, weight=1)
        self.app.inputs.append((entry, 'normal'))
        self.quick_button = self.button(quick, 'Prepare & start', command=self.app.quick_start, style='Portal.Accent.TButton')
        self.quick_button.grid(row=1, column=2, sticky='e')
        self.quick_note_var = tk.StringVar()
        ttk.Label(quick, textvariable=self.quick_note_var, style='Portal.CardNote.TLabel', wraplength=680,
                  justify='left').grid(row=2, column=0, columnspan=3, sticky='w', pady=(12, 0))
        self.subscription_var = tk.StringVar()
        ttk.Label(quick, textvariable=self.subscription_var, style='Portal.Card.TLabel', wraplength=680,
                  justify='left').grid(row=3, column=0, columnspan=3, sticky='w', pady=(14, 0))
        self.quota_bar = ttk.Progressbar(quick, style='Portal.Horizontal.TProgressbar', maximum=100)
        self.quota_bar.grid(row=4, column=0, columnspan=3, sticky='ew', pady=(10, 0))
        link = ttk.Frame(quick, style='Portal.Card.TFrame')
        link.grid(row=5, column=0, columnspan=3, sticky='ew', pady=(16, 0))
        self.link_button = self.button(link, 'Share existing Clash / system proxy', command=self.app.use_existing_proxy)
        self.link_button.pack(side='left')
        self.link_var = tk.StringVar()
        ttk.Label(link, textvariable=self.link_var, style='Portal.CardNote.TLabel', wraplength=350).pack(side='left', padx=12)
        metrics = ttk.Frame(page, style='Portal.Page.TFrame')
        metrics.grid(row=1, column=0, sticky='ew')
        metrics.columnconfigure((0, 1, 2), weight=1)
        self.metric_vars = {}
        for col, key in enumerate(('Listener', 'Upstream core', 'Current engine')):
            frame = ttk.Frame(metrics, padding=20, style='Portal.Card.TFrame')
            frame.grid(row=0, column=col, sticky='nsew', padx=(0, 12 if col < 2 else 0))
            self.label(frame, key, style='Portal.CardNote.TLabel').pack(anchor='w')
            var = tk.StringVar(); self.metric_vars[key] = var
            ttk.Label(frame, textvariable=var, style='Portal.Metric.TLabel', wraplength=200).pack(anchor='w', pady=(14, 0))
        panel = ttk.Frame(page, padding=26, style='Portal.Card.TFrame')
        panel.grid(row=2, column=0, sticky='ew', pady=18)
        self.label(panel, 'Your devices, one connection.', style='Portal.CardTitle.TLabel').pack(anchor='w')
        self.address_var = tk.StringVar()
        ttk.Label(panel, textvariable=self.address_var, style='Portal.Metric.TLabel').pack(anchor='w', pady=(18, 12))
        self.label(panel, 'The listener can stay available while the upstream core sleeps. Listening does not prove an Internet connection.',
                   style='Portal.CardNote.TLabel', wraplength=680).pack(anchor='w')
        actions = ttk.Frame(panel, style='Portal.Card.TFrame'); actions.pack(anchor='w', pady=(22, 0))
        for title, page_name in (('LAN sharing', 'LAN sharing'),):
            self.button(actions, title, command=lambda p=page_name: self.show(p)).pack(side='left', padx=(0, 10))
        note = ttk.Frame(page, padding=22, style='Portal.Card.TFrame')
        note.grid(row=3, column=0, sticky='ew')
        self.label(note, 'Opening or switching language never starts a connection.', style='Portal.CardNote.TLabel', wraplength=680).pack(anchor='w')
        self.label(note, 'Stop the listener before editing configuration. Language and navigation stay available.',
                   style='Portal.CardNote.TLabel', wraplength=680).pack(anchor='w', pady=(10, 0))
        panel.grid_remove()
        note.grid_remove()

    def set_advanced(self, enabled):
        self.advanced = bool(enabled)
        for name, button in self.nav.items():
            button.pack_forget()
            if self.advanced or name in ('Overview', 'LAN sharing'):
                button.pack(fill='x', pady=4, ipady=7, before=self.advanced_button)
        for section in self.advanced_sections:
            section.grid() if self.advanced else section.grid_remove()
        for button in (self.app.save_button, self.app.start_button):
            button.pack_forget()
            if self.advanced:
                button.pack(side='left', padx=(0, 10), before=self.app.stop_button)
        if not self.advanced and self.page not in ('Overview', 'LAN sharing'):
            self.show('Overview')
        self.refresh()

    def show(self, page):
        if page not in self.frames:
            raise ValueError('invalid page')
        self.page = page
        self.frames[page].tkraise()
        for name, button in self.nav.items():
            button.configure(style='Portal.Selected.TButton' if name == page else 'Portal.Nav.TButton')
        self.refresh()

    def _language_selected(self, _=None):
        self.app.set_language('zh' if self.language_var.get() == '简体中文' else 'en')

    def set_language(self, language):
        if language not in ('zh', 'en'):
            raise ValueError('unsupported language')
        self.language = language
        self.language_var.set('简体中文' if language == 'zh' else 'English')
        for variable, key in self.bindings:
            variable.set(self.tr(key))
        self.refresh()

    def refresh(self):
        if not hasattr(self, 'metric_vars') or not hasattr(self.app, 'status_var'):
            return
        if hasattr(self, 'theme_combo'):
            self.theme_combo.configure(values=(self.tr('Dark'), self.tr('Light')))
            self.theme_combo.current(0 if self.theme == 'dark' else 1)
        for table, columns in ((self.node_table, ('Name', 'Protocol')), (self.rule_table, ('Imported rules',))):
            for key in columns:
                table.heading(key, text=self.tr(key))
        if self._preview_rendered is not self.preview:
            for table in (self.node_table, self.rule_table):
                table.delete(*table.get_children())
            if self.preview:
                for row in self.preview.get('node_rows', ()):
                    self.node_table.insert('', 'end', values=row)
                for rule in self.preview.get('rule_rows', ()):
                    self.rule_table.insert('', 'end', values=(rule,))
            self._preview_rendered = self.preview
        self.advanced_var.set(self.tr('Simple view' if self.advanced else 'Advanced settings…'))
        from .subscription_info import display, usage_percent
        self.subscription_var.set(display(self.subscription_info, self.language))
        percent = usage_percent(self.subscription_info)
        if percent is None:
            self.quota_bar.grid_remove()
        else:
            self.quota_bar.configure(value=percent)
            self.quota_bar.grid()
        existing = self.app.existing_proxy
        self.link_var.set(self.tr('Detected local HTTP proxy: {host}:{port}', **existing) if existing else self.tr('No local HTTP system proxy detected.'))
        self.quick_note_var.set(self.tr('Detect the LAN address and keep port 10081 when available. Devices on the current local subnet will be allowed to connect.') +
            ('\n' + self.tr('Current local subnet: {subnet}', subnet=self.setup_network) if self.setup_network else ''))
        self.title.set(self.tr(self.page))
        self.subtitle.set(self.tr(SUBTITLES[self.page]))
        self.app.status_var.set(self.tr(self.status))
        self.metric_vars['Listener'].set(self.tr(self.status))
        self.metric_vars['Upstream core'].set(self.tr(self.core_state))
        mode = self.app.vars.get('engine_mode')
        self.metric_vars['Current engine'].set(self.tr('Embedded · experimental' if mode and mode.get() == 'embedded' else 'External Mihomo'))
        if self.app.raw.get('existing_proxy_port'):
            self.metric_vars['Current engine'].set(self.tr('Existing proxy'))
            self.metric_vars['Upstream core'].set(self.tr('Managed by existing client'))
        host = self.app.vars.get('listen_host'); port = self.app.vars.get('listen_port')
        address = f'{host.get()}:{port.get()}' if host and host.get() and port and port.get() else self.tr('Not configured')
        self.address_var.set(address)
        self.guide_var.set(self.tr('Server: {host}\nPort: {port}', host=host.get(), port=port.get())
                           if host and host.get() and port and port.get() else self.tr('Prepare the subscription on Overview first.'))
        if self.preview:
            message = self.tr('Provider nodes: {nodes} · groups: {groups} · rules: {rules}', **{k: self.preview[k] for k in ('nodes', 'groups', 'rules')})
            if self.preview['kind'] == 'profile':
                message += '\n' + self.tr('Full profile detected. Preserve its rules with Full profile mode; provider mode only consumes nodes.')
            self.preview_var.set(message)
        elif hasattr(self, 'preview_var'):
            self.preview_var.set(self.tr('No provider inspected.'))

    def observe(self, line):
        if line.startswith('Core: '):
            state = line[6:].strip()
            if state in ('starting', 'running', 'stopped', 'failed'):
                self.core_state = state
        elif line.startswith('Core startup failed:'):
            self.core_state = 'failed'
        self.refresh()
