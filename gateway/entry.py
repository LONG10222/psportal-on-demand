#!/usr/bin/python3
"""Persistent explicit LAN entries. Feature OFF means direct, never a dead port."""
import argparse,asyncio,contextvars,ipaddress,json,os,signal,socket,struct,subprocess,sys,time,threading
from pathlib import Path
sys.path.insert(0,'/usr/lib/xianniu-router')
from starpass_http.proxy import ProxyServer,MAX_HEADER_BYTES
from metrics import MeteredProxy
from starpass_http.policy import Route,destination,DestinationDenied,ResolutionFailed
from xianniu_router.dns import resolve_real


def option(config,key,default=''):
    try:
        p=subprocess.run(['uci','-q','get',config+'.'+key],capture_output=True,text=True,timeout=3)
        return p.stdout.strip() if p.returncode==0 else default
    except (OSError,subprocess.TimeoutExpired):return default


def service_running(name):
    try:
        p=subprocess.run(['ubus','-t','2','call','service','list',json.dumps({'name':name})],capture_output=True,text=True,timeout=3)
        if p.returncode:return None
        d=json.loads(p.stdout or '{}')
        return any(v.get('running') for v in d.get(name,{}).get('instances',{}).values())
    except (ValueError,OSError,subprocess.TimeoutExpired):return None


class RouterState:
    def __init__(self,kind):
        self.kind=kind;self.snapshot=('direct',None,'');self.last=0;self.lock=threading.Lock()
    @property
    def route(self):return self.snapshot[0]
    def refresh(self):
        with self.lock:
            if time.monotonic()-self.last<.5:return
            self.snapshot=self.read();self.last=time.monotonic()
    def read(self):
        if self.kind=='accelerator':
            try:d=json.loads(Path('/var/run/xianniu-router.json').read_text())
            except (OSError,ValueError):d={}
            if d.get('running') and service_running('xianniu-router'):return ('socks',('127.0.0.1',10889),'')
        elif option('portalproxy','main.starpass_enabled','0')=='1':
            if option('openclash','config.enable')=='1' and service_running('openclash'):
                auth=''
                import base64
                out=subprocess.run(['uci','-q','show','openclash'],capture_output=True,text=True,timeout=3)
                sections=[line.split('=',1)[0].split('.',1)[1] for line in out.stdout.splitlines() if line.endswith('=authentication')]
                for section in sections:
                    if option('openclash',section+'.enabled')=='1':
                        user=option('openclash',section+'.username');password=option('openclash',section+'.password')
                        if user and password:auth=base64.b64encode((user+':'+password).encode()).decode();break
                return ('starpass',('127.0.0.1',int(option('openclash','config.http_port','7890'))),auth)
        elif option('portalproxy','main.enabled','0')=='1' and service_running('portalproxy'):
            return ('game',('127.0.0.1',int(option('portalproxy','main.entry_backend_port','18880'))),'')
        return ('direct',None,'')


class SwitchingCore:
    def __init__(self,state):self.state=state;self.selected=contextvars.ContextVar('selected_route');self.client=contextvars.ContextVar('client_ip',default='')
    def set_client(self,ip):self.client.set(ip)
    def status(self):return {'engine':'lan-entry','route':self.state.route}
    async def acquire_for_request(self,host,port):
        await asyncio.to_thread(self.state.refresh)
        selected=self.state.snapshot
        if self.state.route=='game' and self.client.get() not in ('127.0.0.1',option('portalproxy','main.client_ip')):selected=('direct',None,'')
        self.selected.set(selected)
        return selected[1] or ('127.0.0.1',1)
    async def release(self):pass
    async def open_connection(self,host,port):
        route,endpoint,auth=self.selected.get()
        if route=='direct':
            address=host
            if destination(host)=='name':
                address=await asyncio.to_thread(resolve_real,host,option('portalproxy','main.local_dns'))
            if destination(address) not in ('external','local'):raise DestinationDenied('Unsafe DNS response')
            return await asyncio.open_connection(address,port)
        reader,writer=await asyncio.open_connection(*endpoint,limit=MAX_HEADER_BYTES)
        try:
            if route=='socks':
                writer.write(b'\x05\x01\x00');await writer.drain()
                if await reader.readexactly(2)!=b'\x05\x00':raise OSError('SOCKS handshake rejected')
                name=host.encode('idna')
                if len(name)>253:raise ValueError('Invalid hostname')
                writer.write(b'\x05\x01\x00\x03'+bytes([len(name)])+name+struct.pack('!H',port));await writer.drain()
                response=await reader.readexactly(4)
                if response[:3]!=b'\x05\x00\x00':raise OSError('SOCKS connect rejected')
                size=4 if response[3]==1 else 16 if response[3]==4 else (await reader.readexactly(1))[0] if response[3]==3 else 0
                if not size:raise OSError('Invalid SOCKS response')
                await reader.readexactly(size+2)
            else:
                authority=host+':'+str(port)
                lines=['CONNECT '+authority+' HTTP/1.1','Host: '+authority]
                if auth:lines.append('Proxy-Authorization: Basic '+auth)
                writer.write(('\r\n'.join(lines)+'\r\n\r\n').encode('ascii'));await writer.drain()
                header=await reader.readuntil(b'\r\n\r\n')
                if len(header)>MAX_HEADER_BYTES or header.split(b'\r\n',1)[0].split(b' ')[1]!=b'200':raise OSError('Local proxy rejected CONNECT')
            return reader,writer
        except BaseException:
            writer.close()
            raise


async def resolve(host,port):
    kind=destination(host)
    if kind=='local':return Route('local',host)
    if kind in ('name','external') and ':' not in host:return Route('external')
    raise DestinationDenied('Unsupported destination')


_sync_failure_until=0
def sync_backend():
    global _sync_failure_until
    if time.monotonic()<_sync_failure_until:return
    import fcntl
    from control import action
    with open('/tmp/portalproxy-features.lock','a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        try:action('sync')
        except Exception:_sync_failure_until=time.monotonic()+30


async def run(kind):
    bind=option('portalproxy','main.listen_ip')
    if not ipaddress.IPv4Address(bind).is_private or bind.startswith('127.'):raise ValueError('Set a LAN listen_ip')
    mask=option('network','lan.netmask','255.255.255.0')
    net=ipaddress.IPv4Network(bind+'/'+mask,strict=False)
    if not net.is_private:raise ValueError('LAN subnet is required')
    port=int(option('portalproxy','main.listen_port','10081')) if kind=='shared' else int(option('xianniu-router','main.http_port','10082'))
    state=RouterState(kind);core=SwitchingCore(state)
    async def metered_resolve(host,port):
        route=await resolve(host,port)
        server.set_destination(route.kind)
        return route
    server=MeteredProxy({'listen_host':bind,'listen_port':port,'allowed_clients':['127.0.0.1'],
        'allowed_networks':[str(net)],'destination_resolver':metered_resolve,'request_timeout':120,'max_connections':128},core)
    await server.start();event=asyncio.Event();loop=asyncio.get_running_loop()
    for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,event.set)
    path=Path('/tmp/portalproxy/entry-'+kind+'.json');path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    previous=None
    try:
        while not event.is_set():
            if kind=='shared':await asyncio.to_thread(sync_backend)
            await asyncio.to_thread(state.refresh)
            current=state.snapshot[:2]
            if previous is not None and previous!=current:
                # An established TCP stream cannot be moved between exits.
                for task in list(server._tasks):task.cancel()
                await asyncio.gather(*list(server._tasks),return_exceptions=True)
            previous=current
            value={'running':True,'route':state.route,'port':port,'updated_at':int(time.time()),'stats':server.snapshot(),'traffic':server.meter.sample()}
            temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value));os.chmod(temp,0o600);temp.replace(path)
            try:await asyncio.wait_for(event.wait(),.5)
            except asyncio.TimeoutError:pass
    finally:
        await server.close();path.unlink(missing_ok=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('kind',choices=['shared','accelerator'])
    os.umask(0o077);asyncio.run(run(parser.parse_args().kind))
