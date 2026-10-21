"""Nonblocking, explicitly requested package download UI. No silent installation."""
import queue
import threading
from . import __version__, app_updates


def show(app):
    import tkinter as tk
    from tkinter import ttk, filedialog
    existing = getattr(app, '_update_window', None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        return
    window = tk.Toplevel(app.root)
    app._update_window = window
    window.title(app._t('Application updates'))
    window.transient(app.root)
    window.geometry('620x420')
    window.minsize(380, 320)
    frame = ttk.Frame(window, padding=16)
    frame.pack(fill='both', expand=True)
    status = tk.StringVar(value=app._t('Check official desktop releases. Your configuration is not changed.'))
    ttk.Label(frame, text='StarPass ' + __version__).pack(anchor='w')
    ttk.Label(frame, textvariable=status, wraplength=550).pack(fill='x', pady=12)
    progress = ttk.Progressbar(frame, mode='determinate')
    progress.pack(fill='x')
    buttons = ttk.Frame(frame)
    buttons.pack(fill='x', pady=12)
    palette = app.view.palette
    notes = tk.Text(frame, height=6, wrap='word', state='disabled', background=palette['entry'], foreground=palette['text'], insertbackground=palette['text'])
    notes.pack(fill='both', expand=True)
    ttk.Label(frame, text=app._t('Manual update: stop sharing, close StarPass, extract into a new folder and launch. Keep the old folder for rollback. Never delete your user configuration.'), wraplength=550).pack(fill='x', pady=10)
    events = queue.Queue()
    cancel = threading.Event()
    state = {'busy': False, 'update': None, 'closed': False, 'after': None}

    def resized(event):
        if event.widget is not window:
            return
        for button in buttons.winfo_children():
            button.pack_configure(side='top' if event.width < 520 else 'left', fill='x' if event.width < 520 else 'none', padx=0 if event.width < 520 else 4, pady=3)
        for child in frame.winfo_children():
            if isinstance(child, ttk.Label):
                child.configure(wraplength=max(280, event.width - 40))
    window.bind('<Configure>', resized)

    def close(event=None):
        if event is not None and event.widget is not window:
            return
        cancel.set()
        state['closed'] = True
        if state['after'] is not None:
            window.after_cancel(state['after'])
            state['after'] = None
        if event is None:
            window.destroy()
    window.protocol('WM_DELETE_WINDOW', close)
    window.bind('<Destroy>', close, add='+')

    def run(kind, work):
        state['busy'] = True
        check_button.configure(state='disabled')
        download_button.configure(state='disabled')
        cancel.clear()
        def worker():
            try:
                events.put((kind, work()))
            except app_updates.UpdateError as exc:
                events.put(('validation_error', str(exc)))
            except FileExistsError:
                events.put(('validation_error', 'Choose a new filename; existing files are never overwritten.'))
            except Exception:
                events.put(('error', kind))
        threading.Thread(target=worker, daemon=True).start()

    def check():
        state['update'] = None
        status.set(app._t('Checking for updates…'))
        run('checked', lambda: app_updates.check(__version__))

    def download():
        update = state['update']
        if update is None or state['busy']:
            return
        path = filedialog.asksaveasfilename(parent=window, title=app._t('Save verified update package'), initialfile=update.name)
        if not path:
            return
        status.set(app._t('Downloading and verifying update…'))
        progress['value'] = 0
        run('downloaded', lambda: app_updates.download(update, path, cancel,
            lambda done, total: events.put(('progress', done * 100 / total))))

    check_button = ttk.Button(buttons, text=app._t('Check updates'), command=check)
    check_button.pack(side='left')
    download_button = ttk.Button(buttons, text=app._t('Download verified package'), command=download, state='disabled')
    download_button.pack(side='left', padx=8)

    def poll():
        if state['closed']:
            return
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == 'progress':
                    progress['value'] = value
                    continue
                state['busy'] = False
                check_button.configure(state='normal')
                if kind == 'checked':
                    update, published = value
                    state['update'] = update
                    status.set(app._t('Update available: ') + '.'.join(map(str, update.version)) if update else app._t('No newer matching desktop release in the latest 100 releases.' if published else 'No official release for this desktop platform has been published in the latest 100 releases.'))
                    notes.configure(state='normal')
                    notes.delete('1.0', 'end')
                    if update:
                        notes.insert('1.0', update.notes)
                    notes.configure(state='disabled')
                elif kind == 'downloaded':
                    progress['value'] = 100
                    status.set(app._t('Package verified and saved. It is not installed. Follow the manual update instructions below.') + '\n' + str(value))
                elif kind == 'validation_error':
                    status.set(app._t(value))
                else:
                    status.set(app._t('Update check failed. Check your network and retry; installed version status is unknown.' if value == 'checked' else 'Download failed or cancelled. Check network, storage and permissions; choose a new filename and retry. Existing application and configuration are unchanged.'))
                download_button.configure(state='normal' if state['update'] is not None else 'disabled')
        except queue.Empty:
            pass
        state['after'] = window.after(100, poll)
    poll()
