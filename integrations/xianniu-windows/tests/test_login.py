import asyncio
from io import BytesIO
import queue
import threading
import time
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace

from PIL import Image
from starpass_xianniu.app import App
from starpass_xianniu.login_image import qr_photo


def picture(kind='JPEG'):
    stream=BytesIO()
    Image.new('RGB',(470,470),'white').save(stream,kind)
    return stream.getvalue()


class LoginTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from starpass_xianniu.ui_style import ScopedTtk
        self.root=tk.Tk();self.root.withdraw()
        self.app=App.__new__(App)
        self.app.root=self.root;self.app.tk=tk;self.app.ttk=ScopedTtk()
        self.app.busy=False;self.app.provider=None;self.app.qr_generation=0
        self.app.simple=False;self.app.quick_pending=None
        self.app.pending_catalog=None
        self.app.config={'dns_server':'192.0.2.1'}
        self.app.status_var=tk.StringVar(self.root)
        self.app.events=queue.Queue()
        self.app.loop=asyncio.new_event_loop()
        self.thread=threading.Thread(target=self.app.loop.run_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.app.qr_generation+=1
        async def drain():
            tasks=[t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
        asyncio.run_coroutine_threadsafe(drain(),self.app.loop).result(3)
        self.app.loop.call_soon_threadsafe(self.app.loop.stop);self.thread.join(2);self.app.loop.close()
        for timer in self.root.tk.call('after','info'):self.root.after_cancel(timer)
        self.root.destroy()

    def test_failed_widget_callback_does_not_freeze_event_pump_or_shutdown(self):
        import tkinter as tk
        self.app.areas=[];self.app.lines=[];self.app.closing=False
        for name in ('start_button','area','line'):setattr(self.app,name,Mock())
        self.app.library_grid=SimpleNamespace(sync_button=Mock())
        self.app.cards=Mock();self.app.cards.winfo_children.return_value=[]
        delivered=[]
        def bad_image(value):raise tk.TclError('fixture image failure')
        self.app.events.put(('success',bad_image,None))
        self.app.events.put(('success',delivered.append,'next-event'))
        self.app.poll()
        self.assertEqual(delivered,['next-event'])
        self.assertIn('TclError',self.app.status_var.get())
        self.assertTrue(self.root.tk.call('after','info'))

    def test_official_jpeg_and_png_render_in_tk_at_bounded_size(self):
        for kind in ('JPEG','PNG'):
            image=qr_photo(picture(kind),self.root)
            self.assertEqual(image.width(),310);self.assertEqual(image.height(),310)

    def test_invalid_or_oversized_images_are_rejected(self):
        for data in (b'not an image',b'x'*1048577):
            with self.assertRaises((ValueError,OSError)):qr_photo(data,self.root)

    def test_fetch_failure_is_shown_inside_login_dialog_and_can_retry(self):
        with patch('xianniu_router.auth_web.create_qr',side_effect=TimeoutError):
            self.app.login()
            kind,callback,message=self.app.events.get(timeout=3)
        self.assertEqual(kind,'error');self.assertTrue(callable(callback))
        callback(message)
        labels=[w.cget('text') for w in self.app.login_dialog.winfo_children() if w.winfo_class()=='TLabel']
        self.assertTrue(any('TimeoutError' in label for label in labels))
        self.assertTrue(any(w.cget('text')=='重新获取二维码' for w in self.app.login_dialog.winfo_children() if w.winfo_class()=='TButton'))

    def test_live_flow_renders_jpeg_and_blocks_start_while_authorizing(self):
        gate=threading.Event()
        def pending(state):
            gate.wait(2);return {'status':'expired'}
        with patch('xianniu_router.auth_web.create_qr',return_value=({},picture())),patch('xianniu_router.auth_web.poll_qr',side_effect=pending):
            self.app.login()
            kind,callback,data=self.app.events.get(timeout=3)
            self.assertEqual(kind,'success');callback(data)
            dialog=self.app.login_dialog
            self.app.login();self.assertIs(self.app.login_dialog,dialog)
            self.app.start();self.assertIn('微信登录',self.app.status_var.get())
            self.assertIsNone(self.app.provider)
            labels=[w for w in dialog.winfo_children() if w.winfo_class()=='TLabel']
            self.assertTrue(any(w.cget('image') for w in labels))
            gate.set()
            kind,callback,message=self.app.events.get(timeout=3)
            self.assertEqual(kind,'error');callback(message)
            self.assertIn('过期',self.app.status_var.get())


if __name__=='__main__':unittest.main()
