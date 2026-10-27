"""Scoped ttk defaults; embedded accelerator pages never restyle the host."""
from tkinter import ttk


class ScopedTtk:
    classes={'Frame','Label','Button','Combobox','Entry','Checkbutton','LabelFrame','Menubutton','Scrollbar','Treeview'}
    def __getattr__(self,name):
        original=getattr(ttk,name)
        if name not in self.classes:return original
        def create(*args,**kwargs):
            default='Treeview' if name=='Treeview' else 'TLabelframe' if name=='LabelFrame' else 'Vertical.TScrollbar' if name=='Scrollbar' else 'T'+name
            kwargs.setdefault('style','SPGame.'+default)
            return original(*args,**kwargs)
        return create


def apply_palette(app, colors, face='Microsoft YaHei UI'):
    """Retheme embedded controls without changing the host or account settings."""
    import tkinter as tk
    app.palette=colors
    style=ttk.Style(app.root)
    for name in ScopedTtk.classes:
        suffix='Treeview' if name=='Treeview' else 'TLabelframe' if name=='LabelFrame' else 'Vertical.TScrollbar' if name=='Scrollbar' else 'T'+name
        style.configure('SPGame.'+suffix,background=colors['page'],foreground=colors['text'])
    for name in ('SPGame.Card.TFrame','SPGame.Card.TLabel','SPGame.CardTitle.TLabel','SPGame.Card.TCheckbutton','SPGame.CardMuted.TLabel'):
        style.configure(name,background=colors['card'],foreground=colors['text'])
    for name in ('SPGame.Muted.TLabel','SPGame.CardMuted.TLabel'):style.configure(name,foreground=colors['note'])
    for name in ('SPGame.TButton','SPGame.Compact.TButton','SPGame.Compact.TMenubutton'):
        style.configure(name,background=colors['button'],foreground=colors['text'])
        style.map(name,background=[('disabled',colors['disabled']),('active',colors['hover'])],foreground=[('disabled',colors['disabled_text']),('!disabled',colors['text'])],font=[('disabled',(face,9))])
    for name in ('SPGame.Accent.TButton','SPGame.SelectedTab.TButton'):
        style.configure(name,background=colors['accent'],foreground=colors['accent_text'],font=(face,11,'bold'))
        style.map(name,background=[('disabled',colors['disabled']),('active',colors['accent_hover'])],foreground=[('disabled',colors['disabled_text'])])
    for name in ('SPGame.TEntry','SPGame.TCombobox'):
        style.configure(name,fieldbackground=colors['entry'],foreground=colors['text'],background=colors['button'],arrowcolor=colors['text'])
        style.map(name,fieldbackground=[('disabled',colors['disabled']),('!disabled',colors['entry'])],foreground=[('disabled',colors['disabled_text']),('!disabled',colors['text'])])
    style.map('SPGame.Card.TCheckbutton',background=[('active',colors['card']),('!active',colors['card'])],foreground=[('disabled',colors['disabled_text']),('!disabled',colors['text'])])
    mapping={'#f4f6fa':colors['page'],'white':colors['card'],'#ffffff':colors['card'],'#eef1f6':colors['disabled'],
        '#17243b':colors['text'],'#334155':colors['text'],'#64748b':colors['note'],'#94a3b8':colors['disabled_text'],'#2455ca':colors['status']}
    def visit(widget):
        if not isinstance(widget,ttk.Widget):
            saved=getattr(widget,'_starpass_original_colors',{})
            for option in ('background','foreground','insertbackground','highlightbackground'):
                try:
                    original=saved.setdefault(option,widget.cget(option))
                    if original in mapping:widget.configure(**{option:mapping[original]})
                except tk.TclError:pass
            widget._starpass_original_colors=saved
        for child in widget.winfo_children():visit(child)
    visit(app.root)
    app.library_grid.canvas.configure(background=colors['card'])
    app.library_grid.grid_frame.configure(background=colors['card'])
    app.library_grid.refresh()
