"""Clash-inspired local desktop layout. No networking or lifecycle ownership."""
from __future__ import annotations
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from . import i18n, product_modes
from .branding import BRAND_NAME, apply_window_icon, load_avatar

PAGES = ('Overview', 'Profiles', 'Proxies', 'Rules', 'LAN sharing', 'Settings', 'Logs', 'Devices')
SUBTITLES = dict(zip(PAGES, (
    'A clear view of the listener, engine and device connection.',
    'Import a provider or keep using your HTTPS subscription.',
    'Choose how nodes are selected without changing engines.',
    'Inspect or import a local profile to view its original rules.',
    'Give another device an address it can connect to.',
    'Keep the complete external core and the experimental embedded option.',
    'Original diagnostics, with sensitive values redacted.',
    'Devices using this proxy, grouped by source IP.',
)))


def probe_note(runtime, language):
    """Distinguish measured partial rounds from a claim about the entire pool."""
    tested, total = runtime.get('probe_tested'), runtime.get('probe_total')
    if (runtime.get('probe_complete') is False and type(tested) is int
            and type(total) is int and 0 <= tested < total):
        return i18n.text('Partial latency check: {tested}/{total} nodes tested; automatic selection uses available measurements.',
                         language, tested=tested, total=total)
    return ''


def saved_preference_note(runtime, language):
    """A group's saved preference is distinct from its effective healthy node."""
    policy = runtime.get('node_policies', {}).get(runtime.get('selection_group'), {})
    preferred = policy.get('name')
    if policy.get('mode') != 'manual' or not preferred or preferred == runtime.get('selected_node'):
        return ''
    return (i18n.text('Saved manual preference: {node}', language, node=preferred) + '\n' +
            i18n.text("The original group's health rules still apply; its current node can differ from the saved preference.", language))


class DesktopView:
    def __init__(self, app):
        self.app = app
        self.root = root = app.root
        self.language = i18n.load_language(app.path)
        self.bindings = []
        self.theme = i18n.load_theme(app.path)
        self._preview_rendered = None
        self.page = 'Overview'
        self.navigation_generation = 0
        self.core_state = 'stopped'
        self.status = 'Stopped'
        self.preview = None
        self.runtime = None
        self._node_rows_rendered = None
        self.subscription_info = None
        self.node_message = ''
        self._nodes_rendered = None
        self._clients_rendered = None
        self.advanced = False
        self.advanced_sections = []
        self.setup_network = ''
        self.nav = {}
        self.frames = {}
        self.scroll_canvases = []
        self._styles()
        root.title(BRAND_NAME)
        apply_window_icon(root)
        root.geometry('1120x800')
        root.minsize(1040, 740)
        root.configure(background=self.palette['page'])
        root.protocol('WM_DELETE_WINDOW', app.close)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        sidebar = ttk.Frame(root, style='Portal.Side.TFrame', padding=(22, 28))
        sidebar.grid(row=0, column=0, sticky='nsew')
        self.brand_avatar = load_avatar(root, size=48)
        if self.brand_avatar is not None:
            ttk.Label(sidebar, image=self.brand_avatar, style='Portal.SideNote.TLabel').pack(anchor='w', pady=(0, 10))
        ttk.Label(sidebar, text='StarPass', style='Portal.Brand.TLabel').pack(anchor='w')
        self.label(sidebar, 'StarPass · games and everyday browsing', style='Portal.SideNote.TLabel',
                   wraplength=170).pack(anchor='w', pady=(5, 20))
        self.label(sidebar, 'Workspace', style='Portal.SideNote.TLabel').pack(anchor='w', pady=(0, 10))
        for name in PAGES:
            button = self.button(sidebar, name, command=lambda p=name: self.show(p), style='Portal.Nav.TButton')
            button.pack(fill='x', pady=3, ipady=2)
            self.nav[name] = button
        self.advanced_var = tk.StringVar()
        self.advanced_button = ttk.Button(sidebar, textvariable=self.advanced_var,
            command=lambda: self.set_advanced(not self.advanced), style='Portal.Nav.TButton')
        self.advanced_button.pack(fill='x', pady=(15, 4))
        ttk.Frame(sidebar, style='Portal.Side.TFrame').pack(fill='y', expand=True)
        self.label(sidebar, 'No system proxy, DNS, VPN or firewall settings are changed.',
                   style='Portal.SideNote.TLabel', wraplength=170, justify='left').pack(anchor='w', pady=(30, 0))

        content = ttk.Frame(root, padding=(28, 26), style='Portal.Page.TFrame')
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

        proxy_content = self.scroll_page(self.frames['Proxies'], 'Proxies')
        proxies = self.selection_card = self.card(proxy_content, 'Selection policy', row=1)
        self.advanced_sections.append(proxies)
        self.fields(proxies, ('selection_mode', 'preferred_node', 'switch_threshold_ms'))
        self.label(proxies, 'HK → JP → other regions. Prefer keeps fallback; fixed never switches silently.',
                   wraplength=680, style='Portal.CardNote.TLabel').grid(row=5, column=0, columnspan=3, sticky='w', pady=16)
        self.label(proxies, 'Full profile uses its original groups and rules; provider selection fields do not override them.',
                   wraplength=680, style='Portal.CardNote.TLabel').grid(row=6, column=0, columnspan=3, sticky='w')

        inventory = self.card(proxy_content, 'Live proxy nodes', row=0, padding=(24, 16))
        self.node_table = self.live_node_table = self.table(inventory, ('Name', 'Protocol', 'Latency', 'Health', 'Selected'), height=5)
        self.node_table.column('Name', width=220)
        for column in ('Protocol', 'Latency', 'Health', 'Selected'):
            self.node_table.column(column, width=95, minwidth=65)
        self.node_note_var = tk.StringVar()
        ttk.Label(inventory, textvariable=self.node_note_var, wraplength=680,
                  style='Portal.CardNote.TLabel').grid(row=2, column=0, columnspan=3, sticky='w', pady=(12, 0))
        self.node_state_var = tk.StringVar()
        ttk.Label(inventory, textvariable=self.node_state_var, wraplength=680,
                  style='Portal.Card.TLabel').grid(row=3, column=0, columnspan=3, sticky='w', pady=(10, 0))
        self.node_controls = ttk.Frame(inventory, style='Portal.Card.TFrame')
        self.node_controls.grid(row=4, column=0, columnspan=3, sticky='ew', pady=(12, 0))
        self.group_label = self.label(self.node_controls, 'Profile group', style='Portal.CardNote.TLabel')
        self.group_label.grid(row=0, column=0, sticky='w', pady=(0, 12))
        self.selection_group_var = self.group_var = tk.StringVar()
        self.group_combo = ttk.Combobox(self.node_controls, textvariable=self.selection_group_var,
                                        values=(), state='readonly', width=30)
        self.group_combo.grid(row=0, column=1, columnspan=2, sticky='ew', pady=(0, 12))
        self.group_combo.bind('<<ComboboxSelected>>', lambda _: self._refresh_nodes())
        self.prepare_nodes_button = self.button(self.node_controls, 'Load live nodes', command=lambda: app.node_command('prepare'))
        self.prepare_nodes_button.grid(row=1, column=0, sticky='w')
        self.test_nodes_button = self.button(self.node_controls, 'Test latency', command=lambda: app.node_command('test'))
        self.test_nodes_button.grid(row=1, column=1, padx=8)
        self.select_node_button = self.button(self.node_controls, 'Use selected node', command=lambda: app.node_command('select'))
        self.select_node_button.grid(row=1, column=2, sticky='w')
        self.label(self.node_controls, 'Fastest switch threshold (ms)', style='Portal.CardNote.TLabel').grid(row=2, column=0, sticky='w', pady=(14, 0))
        self.switch_threshold_var = tk.StringVar(value='50')
        self.threshold_entry = ttk.Entry(self.node_controls, textvariable=self.switch_threshold_var, width=8)
        self.threshold_entry.grid(row=2, column=1, sticky='w', padx=8, pady=(14, 0))
        self.fastest_button = self.button(self.node_controls, 'Use fastest auto', command=lambda: app.node_command('fastest'))
        self.fastest_button.grid(row=2, column=2, sticky='w', pady=(14, 0))
        self.label(self.node_controls, 'Fastest auto requires a measured improvement, two successful probe rounds and a 30-second cooldown before switching.',
                   style='Portal.CardNote.TLabel', wraplength=680).grid(row=3, column=0, columnspan=3, sticky='w', pady=(12, 0))
        self.label(self.node_controls, 'Live changes apply to this run. Loading or testing nodes makes network requests.',
                   style='Portal.CardNote.TLabel', wraplength=680).grid(row=4, column=0, columnspan=3, sticky='w', pady=(8, 0))
        self.node_buttons = [self.prepare_nodes_button, self.test_nodes_button,
                             self.select_node_button, self.fastest_button]
        self.node_table.bind('<<TreeviewSelect>>', lambda _: self._node_controls())
        self.node_table.bind('<Double-1>', lambda _: app.node_command('select'))
        rules = self.card(self.frames['Rules'], 'Imported rules')
        self.rule_table = self.table(rules, ('Imported rules',), height=12)
        self.label(rules, 'Local file preview only. First 500 entries; no latency test or node switch is performed.',
                   wraplength=680, style='Portal.CardNote.TLabel').grid(row=2, column=0, columnspan=3, sticky='w', pady=(12, 0))

        guide = self.card(self.frames['LAN sharing'], 'Device Wi-Fi setup')
        self.guide_var = tk.StringVar()
        ttk.Label(guide, textvariable=self.guide_var, style='Portal.CardTitle.TLabel', wraplength=680,
                  justify='left').grid(row=1, column=0, columnspan=3, sticky='w', pady=(0, 16))
        self.guide_instructions_var = tk.StringVar()
        ttk.Label(guide, textvariable=self.guide_instructions_var,
                  wraplength=680, style='Portal.CardNote.TLabel', justify='left').grid(row=2, column=0, columnspan=3, sticky='w')
        actions = ttk.Frame(guide, style='Portal.Card.TFrame')
        actions.grid(row=3, column=0, columnspan=3, sticky='w', pady=(18, 0))
        self.button(actions, 'Copy address', command=app.copy_address).pack(side='left')
        self.button(actions, 'Export connection guide…', command=app.export_guide).pack(side='left', padx=8)
        self.lan_runtime_var = tk.StringVar()
        ttk.Label(guide, textvariable=self.lan_runtime_var, style='Portal.CardNote.TLabel',
                  wraplength=680).grid(row=4, column=0, columnspan=3, sticky='w', pady=(16, 0))
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

        devices = self.card(self.frames['Devices'], 'Proxy clients')
        self.client_summary = tk.StringVar()
        ttk.Label(devices, textvariable=self.client_summary, style='Portal.CardNote.TLabel', wraplength=680).grid(row=1, column=0, columnspan=3, sticky='w')
        self.client_table = self.table(devices, ('Device IP', 'Connections', 'Requests', 'Last seen'), height=10)
        self.client_table.master.grid_configure(row=2, pady=14)
        self.label(devices, 'Active counts mean open proxy connections. Recent devices stay visible for five minutes; this is not a list of all Wi-Fi devices.',
            style='Portal.CardNote.TLabel', wraplength=680, justify='left').grid(row=3, column=0, columnspan=3, sticky='w')

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
        self.stop_var = tk.StringVar()
        app.stop_button = ttk.Button(footer, textvariable=self.stop_var, command=app.stop, state='disabled')
        app.stop_button.pack(side='left')
        app.status_var = tk.StringVar()
        ttk.Label(footer, textvariable=app.status_var, style='Portal.Status.TLabel').pack(side='right')
        self.refresh()
        self.set_advanced(False)
        self.show('Overview')

    def _styles(self):
        dark = self.theme == 'dark'
        self.palette = c = dict(
            page='#111326' if dark else '#f4f2fc',
            side='#191a32' if dark else '#ece8f8',
            card='#20213c' if dark else '#ffffff',
            text='#f1f5fa' if dark else '#172b43',
            note='#b9bdd8' if dark else '#585a78',
            entry='#111c2a' if dark else '#f5f8fc',
            edge='#35485f' if dark else '#d7e1ed',
            selected='#39345f' if dark else '#e2dbf8',
            hover='#39375f' if dark else '#e5def8',
            button='#303050' if dark else '#eeeaf8',
            accent='#6250b9',
            status='#b4a9ff' if dark else '#57429d',
            accent_hover='#51409f',
            scroll='#657d9b' if dark else '#7d8da2')
        families = set(tkfont.families(self.root))
        self.font_family = next((name for name in ('Microsoft YaHei UI', 'PingFang SC', 'Noto Sans CJK SC', 'Segoe UI', 'Helvetica Neue', 'DejaVu Sans') if name in families), 'TkDefaultFont')
        face = self.font_family
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=(face, 11), background=c['card'], foreground=c['text'])
        for name, bg in (('Page', 'page'), ('Side', 'side'), ('Card', 'card')):
            style.configure('Portal.' + name + '.TFrame', background=c[bg])
        style.configure('Portal.Title.TLabel', background=c['page'], foreground=c['text'], font=(face, 24, 'bold'))
        style.configure('Portal.Brand.TLabel', background=c['side'], foreground=c['text'], font=(face, 18, 'bold'))
        style.configure('Portal.SideNote.TLabel', background=c['side'], foreground=c['note'], font=(face, 10))
        style.configure('Portal.Note.TLabel', background=c['page'], foreground=c['note'])
        style.configure('Portal.Card.TLabel', background=c['card'], foreground=c['text'])
        style.configure('Portal.CardTitle.TLabel', background=c['card'], foreground=c['text'], font=(face, 15, 'bold'))
        style.configure('Portal.CardNote.TLabel', background=c['card'], foreground=c['note'], font=(face, 10))
        style.configure('Portal.Metric.TLabel', background=c['card'], foreground=c['text'], font=(face, 19, 'bold'))
        style.configure('Portal.Status.TLabel', background=c['page'], foreground=c['status'])
        for name, bg, fg in (('Nav', 'side', 'note'), ('Selected', 'selected', 'text')):
            style.configure('Portal.' + name + '.TButton', background=c[bg], foreground=c[fg], borderwidth=0, anchor='w', padding=(14, 9))
            style.map('Portal.' + name + '.TButton', background=[('active', c['hover'])])
        style.configure('TButton', background=c['button'], foreground=c['text'], borderwidth=0, padding=(12, 9))
        style.map('TButton', background=[('active', c['hover'])], foreground=[('disabled', c['note'])])
        style.configure('Portal.Accent.TButton', background=c['accent'], foreground='white', padding=(22, 12), font=(face, 11, 'bold'))
        style.map('Portal.Accent.TButton', background=[('active', c['accent_hover']), ('disabled', c['button'])], foreground=[('disabled', c['note'])])
        style.configure('Vertical.TScrollbar', background=c['scroll'], troughcolor=c['page'], arrowcolor=c['note'], borderwidth=0, arrowsize=11, lightcolor=c['page'], darkcolor=c['page'])
        style.map('Vertical.TScrollbar', background=[('active', c['note'])])
        style.configure('Portal.Divider.TFrame', background=c['edge'])
        style.configure('Portal.Section.TLabel', background=c['card'], foreground=c['note'], font=(face, 10, 'bold'))
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
        for canvas in self.scroll_canvases:
            canvas.configure(background=self.palette['page'])
        self.refresh()

    def scroll_page(self, parent, name):
        """Keep live controls reachable on compact windows and translated UIs."""
        parent.rowconfigure(0, weight=1)
        canvas = tk.Canvas(parent, background=self.palette['page'], highlightthickness=0,
                           borderwidth=0, width=680, height=400)
        canvas.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(parent, orient='vertical', command=canvas.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        canvas.configure(yscrollcommand=scroll.set)
        body = ttk.Frame(canvas, style='Portal.Page.TFrame')
        body.columnconfigure(0, weight=1)
        item = canvas.create_window((0, 0), window=body, anchor='nw')
        body.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))
        def wheel(event):
            if self.page != name or not canvas.winfo_viewable():
                return
            if not (canvas.winfo_rootx() <= event.x_root < canvas.winfo_rootx() + canvas.winfo_width()
                    and canvas.winfo_rooty() <= event.y_root < canvas.winfo_rooty() + canvas.winfo_height()):
                return
            delta = getattr(event, 'delta', 0)
            number = getattr(event, 'num', None)
            canvas.yview_scroll(-1 if delta > 0 or number == 4 else 1, 'units')
        for event in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            self.root.bind(event, wheel, add='+')
        self.scroll_canvases.append(canvas)
        return body

    def table(self, parent, columns, height):
        frame = ttk.Frame(parent, style='Portal.Card.TFrame')
        frame.grid(row=1, column=0, columnspan=3, sticky='ew')
        frame.columnconfigure(0, weight=1)
        table = ttk.Treeview(frame, columns=columns, show='headings', height=height)
        for key in columns:
            table.heading(key, text=self.tr(key))
            width = (220 if key == 'Name' else 120) if len(columns) > 2 else 220 if len(columns) > 1 else 580
            table.column(key, width=width, minwidth=70, stretch=True)
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
        if title is not None:
            self.label(card, title, style='Portal.CardTitle.TLabel').grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 16))
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
                choices = ('auto', 'prefer', 'fixed', 'fastest') if key == 'selection_mode' else ('external', 'embedded')
                entry = ttk.Combobox(parent, textvariable=variable, values=choices, state='readonly', width=34)
                normal = 'readonly'
            else:
                entry = ttk.Entry(parent, textvariable=variable, show='•' if key == 'subscription_url' else '', width=38)
                normal = 'normal'
            entry.grid(row=row, column=1, columnspan=1 if key in ('core_path', 'native_path', 'subscription_file', 'profile_file') else 2, sticky='ew')
            self.app.inputs.append((entry, normal))
            if key in ('selection_mode', 'preferred_node', 'switch_threshold_ms'):
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
        page = self.scroll_page(self.frames['Overview'], 'Overview')
        quick = self.card(page, None, padding=(24, 20))
        # The approved character remains a local asset. Decoration never owns
        # input focus, network activity, timers, or connection state.
        self.navigator_avatar = load_avatar(self.root, size=128)
        self.navigator_canvas = tk.Canvas(quick, height=142, width=480,
            highlightthickness=0, borderwidth=0, takefocus=0)
        self.navigator_canvas.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 18))
        self.navigator_canvas.bind('<Configure>', lambda _: self._draw_navigator())
        product = ttk.Frame(quick, style='Portal.Card.TFrame')
        product.grid(row=1, column=0, columnspan=3, sticky='ew', pady=(0, 10))
        self.label(product, 'Product mode').pack(side='left', padx=(0, 12))
        variable = self.app.vars['product_mode'] = tk.StringVar(value='game')
        variable.trace_add('write', self.app._changed)
        self.product_mode_combo = ttk.Combobox(product, state='readonly', width=22)
        self.product_mode_combo.pack(side='left')
        self.product_mode_combo.bind('<<ComboboxSelected>>', self._product_mode_selected)
        self.app.inputs.append((self.product_mode_combo, 'readonly'))
        self.product_mode_note = tk.StringVar()
        ttk.Label(quick, textvariable=self.product_mode_note, wraplength=680,
                  style='Portal.CardNote.TLabel', justify='left').grid(
                      row=2, column=0, columnspan=3, sticky='w', pady=(0, 16))
        self.label(quick, 'HTTPS subscription link', style='Portal.Section.TLabel').grid(row=3, column=0, columnspan=3, sticky='w', pady=(0, 8))
        entry = self.subscription_entry = ttk.Entry(quick, textvariable=self.app.vars['subscription_url'], show='•')
        entry.grid(row=4, column=0, columnspan=2, sticky='ew', padx=(0, 12))
        quick.columnconfigure(0, weight=1)
        self.app.inputs.append((entry, 'normal'))
        self.quick_button = self.button(quick, 'Prepare & start', command=self.app.quick_start, style='Portal.Accent.TButton')
        self.quick_button.grid(row=4, column=2, sticky='e')
        self.quick_note_var = tk.StringVar()
        ttk.Label(quick, textvariable=self.quick_note_var, style='Portal.CardNote.TLabel', wraplength=680,
                  justify='left').grid(row=5, column=0, columnspan=3, sticky='w', pady=(10, 0))
        self.subscription_var = tk.StringVar()
        ttk.Label(quick, textvariable=self.subscription_var, style='Portal.CardNote.TLabel', wraplength=680,
                  justify='left').grid(row=6, column=0, columnspan=3, sticky='w', pady=(14, 0))
        self.quota_bar = ttk.Progressbar(quick, style='Portal.Horizontal.TProgressbar', maximum=100)
        self.quota_bar.grid(row=7, column=0, columnspan=3, sticky='ew', pady=(10, 0))
        ttk.Frame(quick, height=1, style='Portal.Divider.TFrame').grid(row=8, column=0, columnspan=3, sticky='ew', pady=(18, 14))
        self.label(quick, 'Already have Clash? Or need help?', style='Portal.Section.TLabel').grid(row=9, column=0, columnspan=3, sticky='w', pady=(0, 10))
        link = ttk.Frame(quick, style='Portal.Card.TFrame')
        link.grid(row=10, column=0, columnspan=3, sticky='ew', pady=(0, 0))
        self.link_button = self.button(link, 'Share existing Clash / system proxy', command=self.app.use_existing_proxy)
        self.link_button.pack(side='left')
        self.link_var = tk.StringVar()
        ttk.Label(link, textvariable=self.link_var, style='Portal.CardNote.TLabel', wraplength=350).pack(side='left', padx=12)
        help_row = ttk.Frame(quick, style='Portal.Card.TFrame')
        help_row.grid(row=11, column=0, columnspan=3, sticky='w', pady=(12, 0))
        self.preflight_button = self.button(help_row, 'Before you start', command=self.app.check_preparation)
        self.preflight_button.pack(side='left')
        self.core_setup_button = self.button(help_row, 'Choose trusted Mihomo…', command=self.app.choose_core)
        self.core_setup_button.pack(side='left', padx=8)
        self.app.inputs.append((self.core_setup_button, 'normal'))
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
        metrics.grid_remove()
        hero = ttk.Frame(page, padding=(24, 20), style='Portal.Card.TFrame')
        hero.grid(row=1, column=0, sticky='ew')
        self.label(hero, 'Service status · next step', style='Portal.Section.TLabel').pack(anchor='w', pady=(0, 10))
        self.hero_var = tk.StringVar()
        self.hero_note_var = tk.StringVar()
        ttk.Label(hero, textvariable=self.hero_var, style='Portal.Metric.TLabel', wraplength=690).pack(anchor='w')
        ttk.Label(hero, textvariable=self.hero_note_var, style='Portal.CardNote.TLabel', wraplength=690,
                  justify='left').pack(anchor='w', pady=(8, 0))
        panel = self.runtime_panel = ttk.Frame(page, padding=(24, 20), style='Portal.Card.TFrame')
        panel.grid(row=2, column=0, sticky='ew', pady=18)
        panel.columnconfigure(0, weight=1)
        self.label(panel, 'Connection address', style='Portal.CardNote.TLabel').grid(row=0, column=0, sticky='w')
        self.address_var = tk.StringVar()
        ttk.Label(panel, textvariable=self.address_var, style='Portal.Metric.TLabel').grid(row=1, column=0, sticky='w', pady=(6, 8))
        self.connection_count_var = tk.StringVar()
        ttk.Label(panel, textvariable=self.connection_count_var, style='Portal.Card.TLabel').grid(row=2, column=0, sticky='w')
        self.label(panel, 'Active devices count distinct source IPs with open connections.',
                   style='Portal.CardNote.TLabel', wraplength=480).grid(row=3, column=0, sticky='w', pady=(5, 0))
        actions = ttk.Frame(panel, style='Portal.Card.TFrame')
        actions.grid(row=0, column=1, rowspan=4, sticky='e', padx=(12, 0))
        self.button(actions, 'Copy address', command=self.app.copy_address).pack(fill='x')
        self.nodes_button = self.button(actions, 'Proxies', command=lambda: self.show('Proxies'))
        self.nodes_button.pack(fill='x', pady=(8, 0))
        note = ttk.Frame(page, padding=22, style='Portal.Card.TFrame')
        note.grid(row=3, column=0, sticky='ew')
        self.label(note, 'Opening or switching language never starts a connection.', style='Portal.CardNote.TLabel', wraplength=680).pack(anchor='w')
        self.label(note, 'Stop the listener before editing configuration. Language and navigation stay available.',
                   style='Portal.CardNote.TLabel', wraplength=680).pack(anchor='w', pady=(10, 0))
        panel.grid_remove()
        note.grid_remove()

    def _draw_navigator(self):
        """Static anime hero; nonessential art stays outside the text column."""
        if not hasattr(self, 'navigator_canvas'):
            return
        canvas = self.navigator_canvas
        width = max(1, canvas.winfo_width())
        dark = self.theme == 'dark'
        bg = '#17192f' if dark else '#eee9fa'
        ink = '#f5f2ff' if dark else '#29223f'
        muted = '#c5bfdf' if dark else '#5f527b'
        orbit = '#484274' if dark else '#c6b8e8'
        canvas.configure(background=bg)
        canvas.delete('all')
        # Right-aligned illustration leaves a bounded text area at every size.
        center = width - 78
        canvas.create_oval(center-88, -34, center+88, 168, outline=orbit, width=2)
        canvas.create_line(center-108, 120, center+78, 24, fill=orbit, width=1)
        for dx, y, r in ((-116, 27, 2), (-92, 62, 1), (-102, 105, 2), (62, 14, 2), (62, 124, 1)):
            x = center + dx
            canvas.create_line(x-r-2, y, x+r+2, y, fill=muted)
            canvas.create_line(x, y-r-2, x, y+r+2, fill=muted)
        if self.navigator_avatar is not None:
            canvas.create_image(center, 71, image=self.navigator_avatar)
        text_width = max(140, width-210)
        y = 18
        for text, color, size, weight in (
            ('STARPASS  /  STAR-SEA', muted, 9, 'bold'),
            (self.tr('Your star-sea navigator'), ink, 19, 'bold'),
            (self.tr('Prepare. Connect. Explore.'), muted, 11, 'normal')):
            item = canvas.create_text(18, y, anchor='nw', text=text, fill=color,
                font=(self.font_family, size, weight), width=text_width, tags=('navigator-text',))
            bounds = canvas.bbox(item)
            y = (bounds[3] if bounds else y + size * 2) + 10
        # Point fonts follow host DPI. Let text determine height rather than
        # overlapping a fixed baseline at large scaling or translated wrapping.
        height = max(142, y + 8)
        if int(canvas.cget('height')) != height:
            canvas.configure(height=height)

    def _product_mode_selected(self, _=None):
        index = self.product_mode_combo.current()
        if 0 <= index < len(product_modes.MODES):
            self.app.set_product_mode(product_modes.MODES[index])

    def set_advanced(self, enabled):
        self.advanced = bool(enabled)
        for name, button in self.nav.items():
            button.pack_forget()
            if self.advanced or name in ('Overview', 'Proxies', 'Devices', 'LAN sharing'):
                button.pack(fill='x', pady=3, ipady=2, before=self.advanced_button)
        for section in self.advanced_sections:
            section.grid() if self.advanced else section.grid_remove()
        for button in (self.app.save_button, self.app.start_button):
            button.pack_forget()
            if self.advanced:
                button.pack(side='left', padx=(0, 10), before=self.app.stop_button)
        if not self.advanced and self.page not in ('Overview', 'Proxies', 'Devices', 'LAN sharing'):
            self.show('Overview')
        self.refresh()

    def show(self, page):
        if page not in self.frames:
            raise ValueError('invalid page')
        if self.page != page:
            self.navigation_generation += 1
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

    def _direct_subscription(self):
        values = self.app.vars
        return (not self.app.raw.get('existing_proxy_port')
                and any(values.get(key) and values[key].get()
                        for key in ('subscription_file', 'subscription_url', 'profile_file')))

    def _node_runtime(self):
        """Normalize owned-child telemetry into one table presentation."""
        runtime = dict(self.runtime or {})
        live = self.app.node_state
        if not live or not self._direct_subscription():
            return runtime
        structured = self.runtime is not None and 'node_management' in self.runtime
        # An acknowledged legacy command may arrive just ahead of its matching
        # status record. Only that newer reply can temporarily fill the table;
        # periodic compatibility records cannot undo prepare/group/fastest.
        fallback = not structured or (getattr(self.app, '_node_protocol', None) == 'legacy'
            and type(live.get('id')) is int and live['id'] > runtime.get('last_command_id', 0))
        if fallback:
            runtime['node_management'] = True
            runtime['groups'] = [dict(name=name) for name in live.get('groups', ())]
            runtime['selection_group'] = live.get('group', '')
            runtime['selected_node'] = live.get('current', '')
            runtime['node_policies'] = live.get('policies', {})
            runtime['nodes'] = [dict(name=row['name'], type=row.get('type', '—'),
                delay_ms=row.get('delay'), healthy=True if row.get('delay') is not None else None)
                for row in live.get('rows', ())]
            policy = live.get('policies', {}).get(live.get('group'), {})
            runtime['selection_mode'] = {'manual': 'fixed', 'latency': 'fastest'}.get(
                policy.get('mode'), runtime.get('selection_mode', 'profile'))
        return runtime

    def _node_controls(self):
        if not hasattr(self, 'node_controls'):
            return
        runtime = self._node_runtime()
        supported = bool(self._direct_subscription() and runtime.get('node_management'))
        # The linked client always owns its own node controls.
        self.node_controls.grid() if supported else self.node_controls.grid_remove()
        active = (supported and self.app.backend.ready
                  and self.app.backend.stopping_since is None
                  and not runtime.get('busy') and not self.app.importing
                  and self.app._pending_node_request is None and not self.app.closing)
        full_profile = bool(self.app.vars.get('profile_file') and self.app.vars['profile_file'].get())
        group_ready = not full_profile or bool(self.selection_group_var.get())
        self.prepare_nodes_button.configure(state='normal' if active else 'disabled')
        self.group_combo.configure(state='readonly' if active else 'disabled')
        for widget in (self.test_nodes_button, self.fastest_button, self.threshold_entry):
            widget.configure(state='normal' if active and group_ready else 'disabled')
        self.select_node_button.configure(state='normal' if active and group_ready and self.node_table.selection() else 'disabled')

    def _refresh_nodes(self):
        direct = self._direct_subscription()
        runtime = self._node_runtime()
        linked = bool(self.app.raw.get('existing_proxy_port'))
        full_profile = bool(self.app.vars.get('profile_file') and self.app.vars['profile_file'].get())
        groups = tuple(group['name'] for group in runtime.get('groups', ()))
        self.group_combo.configure(values=groups)
        if self.selection_group_var.get() not in groups:
            current = runtime.get('selection_group', '')
            self.selection_group_var.set(current if current in groups else groups[0] if len(groups) == 1 else '')
        for widget in (self.group_label, self.group_combo):
            widget.grid() if full_profile or len(groups) > 1 else widget.grid_remove()
        if linked or full_profile or runtime.get('node_management') or not self.advanced:
            self.selection_card.grid_remove()
        else:
            self.selection_card.grid()
        if direct:
            self.nodes_button.pack(fill='x', pady=(8, 0))
        else:
            self.nodes_button.pack_forget()
        preview_rows = (self.preview or {}).get('node_rows', ())
        protocols = dict(preview_rows)
        live = self.app.node_state or {}
        protocols.update((row['name'], row.get('type', '—')) for row in live.get('rows', ()))
        scoped = not full_profile or (self.selection_group_var.get()
                                     and runtime.get('selection_group') == self.selection_group_var.get())
        if runtime.get('node_management') and direct:
            rows = tuple((node['name'], node.get('type', node.get('protocol', protocols.get(node['name'], '—'))),
                          self.tr('{delay} ms', delay=node['delay_ms']) if node.get('delay_ms') is not None else '—',
                          self.tr('Healthy' if node.get('healthy') is True else
                                  'Unavailable' if node.get('healthy') is False else 'Not tested'),
                          self.tr('Current') if node['name'] == runtime.get('selected_node') else '')
                         for node in (runtime.get('nodes', ()) if scoped else ()))
            note = self.tr('Live measurements from this listener. No latency is shown until a probe reports it.')
        else:
            rows = tuple((name, protocol, '—', self.tr('Not tested'), '')
                         for name, protocol in preview_rows) if not linked else ()
            note = self.tr('Local file preview only. Start the listener and load live nodes to test or switch.')
        if rows != self._node_rows_rendered:
            selected = self.node_table.selection()
            selected_name = self.node_table.item(selected[0], 'values')[0] if selected else None
            scroll = self.node_table.yview()
            self.node_table.delete(*self.node_table.get_children())
            for row in rows:
                item = self.node_table.insert('', 'end', values=row)
                if row[0] == selected_name:
                    self.node_table.selection_set(item)
            if scroll:
                self.node_table.yview_moveto(scroll[0])
            self._node_rows_rendered = rows
        if linked:
            description = note = self.tr('Node selection and latency tests are managed by the existing Clash client.')
        elif full_profile and not runtime.get('node_management'):
            description = self.tr('Full profile uses its original groups and rules; provider selection fields do not override them.')
        elif runtime.get('node_management'):
            mode = runtime.get('selection_mode', '')
            selection = runtime.get('selected_node') or self.tr('Not reported')
            description = (self.tr('Current node: {node} · Mode: {mode}', node=selection, mode=self.tr(mode))
                           if scoped else self.tr('Choose a profile group, then load or test its direct nodes.'))
            if full_profile:
                description += '\n' + self.tr('Only the chosen group is managed; original rules and other groups stay unchanged.')
            preference = saved_preference_note(runtime, self.language) if full_profile and scoped else ''
            if preference:
                description += '\n' + preference
            if mode == 'fastest' and runtime.get('switch_threshold_ms') is not None:
                description += '\n' + self.tr('Switch threshold: {threshold} ms', threshold=runtime['switch_threshold_ms'])
            partial = probe_note(runtime, self.language)
            if partial and scoped:
                description += '\n' + partial
            if runtime.get('busy') or self.app._pending_node_request:
                description += '\n' + self.tr('Applying node command…')
            elif runtime.get('command_error'):
                from .desktop import redact_log
                description += '\n' + redact_log(runtime['command_error'], self.app.backend.secrets)
            elif self.node_message:
                description += '\n' + self.tr(self.node_message)
        elif self.app.backend.process is None:
            description = self.tr('Start the listener to load live nodes.')
        else:
            description = self.tr('Live node controls are unavailable for this engine.' if self.runtime else
                                  'Waiting for a live engine report.')
        self.node_note_var.set(note)
        self.node_state_var.set(description)
        self._node_controls()

    def refresh(self):
        self._draw_navigator()
        if not hasattr(self, 'metric_vars') or not hasattr(self.app, 'status_var'):
            return
        if hasattr(self, 'theme_combo'):
            self.theme_combo.configure(values=(self.tr('Dark'), self.tr('Light')))
            self.theme_combo.current(0 if self.theme == 'dark' else 1)
        for table in (self.node_table, self.rule_table, self.client_table):
            for key in table['columns']:
                table.heading(key, text=self.tr(key))
        if self._preview_rendered is not self.preview:
            self.rule_table.delete(*self.rule_table.get_children())
            if self.preview:
                for rule in self.preview.get('rule_rows', ()):
                    self.rule_table.insert('', 'end', values=(rule,))
            self._preview_rendered = self.preview
        product_mode = self.app.product_mode()
        self.product_mode_combo.configure(values=tuple(self.tr(product_modes.LABELS[mode]) for mode in product_modes.MODES))
        if product_mode in product_modes.MODES:
            self.product_mode_combo.current(product_modes.MODES.index(product_mode))
            self.product_mode_note.set(self.tr(product_modes.NOTES[product_mode]))
        self.advanced_var.set(self.tr('Simple view' if self.advanced else 'Advanced settings…'))
        self.stop_var.set(self.tr('Cancel preparation' if self.app.importing else 'Stop'))
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
        self.quick_note_var.set(self.tr('Configure apps manually with the local address below. System proxy and VPN settings stay unchanged.'
            if product_mode == 'clash' else 'Detect the current LAN for quick setup. Manual device lists are kept; automatic lists follow the subnet. Advanced Start keeps your manual address.') +
            ('\n' + self.tr('Current local subnet: {subnet}', subnet=self.setup_network) if self.setup_network and product_mode != 'clash' else ''))
        origin = self.app.raw.get('source_provenance')
        source = next((self.app.vars[key].get().strip() for key in ('profile_file', 'subscription_file')
                       if self.app.vars.get(key) and self.app.vars[key].get().strip()), '')
        if isinstance(origin, dict) and origin.get('kind') == 'local' and origin.get('path') == source:
            self.quick_note_var.set(self.quick_note_var.get() + '\n' + self.tr(
                'Using your selected local file. Import subscription explicitly to replace this override.'))
        self.title.set(self.tr(self.page))
        self.subtitle.set(self.tr(SUBTITLES[self.page]))
        self.app.status_var.set(self.tr(self.status))
        self.metric_vars['Listener'].set(self.tr(self.status))
        self.metric_vars['Upstream core'].set(self.tr(self.core_state))
        mode = self.app.vars.get('engine_mode')
        if mode and mode.get() == 'embedded':
            self.core_setup_button.pack_forget()
        else:
            self.core_setup_button.pack(side='left', padx=8)
        self.metric_vars['Current engine'].set(self.tr('Embedded · experimental' if mode and mode.get() == 'embedded' else 'External Mihomo'))
        if self.app.raw.get('existing_proxy_port'):
            self.metric_vars['Current engine'].set(self.tr('Existing proxy'))
            self.metric_vars['Upstream core'].set(self.tr('Managed by existing client'))
        host = self.app.vars.get('listen_host'); port = self.app.vars.get('listen_port')
        effective_host = '127.0.0.1' if product_mode == 'clash' else host.get() if host else ''
        address = f'{effective_host}:{port.get()}' if effective_host and port and port.get() else self.tr('Not configured')
        self.address_var.set(address)
        self._refresh_runtime(address)
        if effective_host and port and port.get():
            self.runtime_panel.grid()
        else:
            self.runtime_panel.grid_remove()
        self._refresh_nodes()
        self.guide_var.set(self.tr('Server: {host}\nPort: {port}', host=effective_host, port=port.get())
                           if effective_host and port and port.get() else self.tr('Prepare the subscription on Overview first.'))
        self.guide_instructions_var.set(self.tr('Configure apps manually with the local address below. System proxy and VPN settings stay unchanged.'
            if product_mode == 'clash' else 'Join the same Wi-Fi. In the device Wi-Fi settings choose HTTP Proxy → Manual, enter the server and port above, and leave authentication off.'))
        self.guide_instructions_var.set(self.guide_instructions_var.get() + '\n\n' + self.tr(
            'When finished, turn off the proxy setting on the device before stopping StarPass. Do not disable firewall or certificate protection.'))
        if self.preview:
            message = self.tr('Provider nodes: {nodes} · groups: {groups} · rules: {rules}', **{k: self.preview[k] for k in ('nodes', 'groups', 'rules')})
            if self.preview['kind'] == 'profile':
                message += '\n' + self.tr('Full profile detected. Preserve its rules with Full profile mode; provider mode only consumes nodes.')
            self.preview_var.set(message)
        elif hasattr(self, 'preview_var'):
            self.preview_var.set(self.tr('No provider inspected.'))

    def _refresh_runtime(self, address):
        import datetime
        app = self.app
        runtime = self.runtime or {}
        statistics = app.statistics or {}
        devices = runtime.get('connected_clients', statistics.get('devices', '—'))
        active = runtime.get('active_connections', statistics.get('active', '—'))
        counts = self.tr('Active devices: {devices} · Connections: {connections}',
                         devices=devices, connections=active)
        ready = self.status in ('Listening', 'Forwarding')
        title = ('Devices are using the proxy' if isinstance(devices, int) and devices > 0
                 else 'Ready · waiting for a device') if ready else self.status
        self.hero_var.set(self.tr(title))
        from .onboarding import next_step
        guidance = self.tr(next_step(app.product_mode(), ready, devices, statistics.get('errors', 0)))
        core_label = self.tr('Managed by existing client' if app.raw.get('existing_proxy_port') else self.core_state)
        self.hero_note_var.set(core_label + ' · ' + guidance)
        self.connection_count_var.set(counts)
        self.lan_runtime_var.set(counts)
        self.client_summary.set(counts + ' · ' + self.tr('Errors: {count}', count=statistics.get('errors', 0)))
        clients = runtime.get('clients', statistics.get('clients', []))
        client_key = (clients, self.language)
        if self._clients_rendered != client_key:
            self.client_table.delete(*self.client_table.get_children())
            for item in clients:
                seen = item.get('last_seen')
                try:
                    when = datetime.datetime.fromtimestamp(seen).strftime('%H:%M:%S') if seen is not None else '—'
                except (ValueError, TypeError, OverflowError, OSError):
                    when = '—'
                self.client_table.insert('', 'end', values=(item['ip'], item.get('active', 0), item.get('requests', 0), when))
            self._clients_rendered = client_key

    def observe(self, line):
        if line.startswith('Core: '):
            state = line[6:].strip()
            if state in ('starting', 'running', 'stopped', 'failed'):
                self.core_state = state
        elif line.startswith('Core startup failed:'):
            self.core_state = 'failed'
        self.refresh()
