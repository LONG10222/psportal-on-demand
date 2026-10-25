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
