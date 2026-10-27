"""Independent LAN ingress; it never owns or starts an Internet upstream."""
import asyncio
import copy
import ipaddress
import threading
from .proxy import ProxyServer


class SwitchingUpstream:
    def __init__(self):
        self.endpoint=None;self.tasks=set();self.active=0

    def change(self, endpoint):
        if endpoint==self.endpoint:return
        self.endpoint=endpoint
        # Only Internet streams use acquire. LAN streams remain uninterrupted.
        for task in tuple(self.tasks):task.cancel()

    async def acquire(self):
        if self.endpoint is None:raise RuntimeError('No active upstream')
        self.tasks.add(asyncio.current_task());self.active+=1
        return self.endpoint

    async def release(self):
        self.tasks.discard(asyncio.current_task());self.active=max(0,self.active-1)

    def status(self):
        return dict(core_state='external',node_management=False,error='',preparing=False)


def validate(values):
    def local(value):
        try:
            address=ipaddress.IPv4Address(value)
            return address==ipaddress.IPv4Address('127.0.0.1') or any(address in ipaddress.IPv4Network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))
        except (ValueError,TypeError):return False
    host=values.get('listen_host');clients=values.get('allowed_clients');port=values.get('listen_port')
    if not local(host) or not isinstance(clients,list) or not 1<=len(clients)<=256 or not all(local(c) for c in clients):raise ValueError('请选择局域网和允许接入的设备')
    if type(port) is not int or not 1024<=port<=65535:raise ValueError('共享端口无效')
    return dict(listen_host=host,listen_port=port,allowed_clients=list(dict.fromkeys(clients)),request_timeout=90,max_connections=128)


class GameSharing:
    def __init__(self):
        self.thread=None;self.loop=None;self.signal=None;self.proxy=None;self.core=None
        self.lock=threading.Lock();self.snapshot_value={};self.closing=False;self.endpoint=None

    @property
    def active(self):return bool(self.thread and self.thread.is_alive())

    @property
    def ready(self):return bool(self.snapshot().get('running')) and not self.closing

    def snapshot(self):
        with self.lock:return copy.deepcopy(self.snapshot_value)

    def start(self, values):
        if self.active:raise ValueError('游戏共享正在运行')
        values=validate(values);self.closing=False
        with self.lock:self.snapshot_value={'state':'preparing','running':False}
        self.thread=threading.Thread(target=lambda:asyncio.run(self._run(values)),daemon=True)
        self.thread.start()

    async def _run(self, values):
        self.loop=asyncio.get_running_loop();self.signal=asyncio.Event()
        self.core=SwitchingUpstream();self.core.change(self.endpoint)
        self.proxy=ProxyServer(values,self.core)
        try:
            await self.proxy.start()
            if self.closing:self.signal.set()
            while not self.signal.is_set():
                value=self.proxy.status();value['upstream_ready']=self.core.endpoint is not None
                with self.lock:self.snapshot_value=value
                try:await asyncio.wait_for(self.signal.wait(),.2)
                except asyncio.TimeoutError:pass
        except Exception:
            with self.lock:self.snapshot_value={'running':False,'state':'error','error':'共享启动失败，请检查端口和网卡'}
        finally:
            await self.proxy.close()
            with self.lock:
                self.snapshot_value['running']=False
                if self.snapshot_value.get('state')!='error':self.snapshot_value['state']='stopped'
            self.loop=None;self.closing=False

    def upstream(self, port):
        if port is not None and (type(port) is not int or not 1024<=port<=65535):raise ValueError('上游端口无效')
        endpoint=('127.0.0.1',port) if port is not None else None
        if endpoint==self.endpoint:return
        self.endpoint=endpoint
        loop=self.loop
        if loop and not loop.is_closed():
            def change():
                self.core.change(endpoint);self.proxy.last_error=''
            loop.call_soon_threadsafe(change)

    def stop(self):
        self.closing=True
        loop=self.loop
        if loop and not loop.is_closed():loop.call_soon_threadsafe(self.signal.set)

