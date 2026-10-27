"""Count explicit-entry bytes only. No packet capture, probes or core wake-up."""
import time
from starpass_http.proxy import ProxyServer

class Meter:
    def __init__(self):
        self.started=time.monotonic();self.previous=self.started
        self.bytes={k:{'upload':0,'download':0} for k in ('local','external')}
        self.last={k:dict(v) for k,v in self.bytes.items()}
        self.rates={k:{'upload':0,'download':0} for k in self.bytes}
    def add(self,kind,direction,size):
        if kind in self.bytes:self.bytes[kind][direction]+=size
    def sample(self):
        now=time.monotonic();elapsed=now-self.previous
        if elapsed>=.5:
            self.rates={k:{d:max(0,(v-self.last[k][d])/elapsed) for d,v in row.items()} for k,row in self.bytes.items()}
            self.last={k:dict(v) for k,v in self.bytes.items()};self.previous=now
        return {'session':self.started,'uptime':max(0,now-self.started),
                'bytes':{k:dict(v) for k,v in self.bytes.items()},'speed':self.rates}

class Reader:
    def __init__(self,raw,record):self.raw=raw;self.record=record
    def __getattr__(self,key):return getattr(self.raw,key)
    async def read(self,*args):
        data=await self.raw.read(*args);self.record(len(data));return data
    async def readuntil(self,*args):
        data=await self.raw.readuntil(*args);self.record(len(data));return data
    async def readexactly(self,*args):
        data=await self.raw.readexactly(*args);self.record(len(data));return data
class Writer:
    def __init__(self,raw,record):self.raw=raw;self.record=record
    def __getattr__(self,key):return getattr(self.raw,key)
    def write(self,data):self.raw.write(data);self.record(len(data))

class MeteredProxy(ProxyServer):
    def __init__(self,config,core):
        super().__init__(config,core);self.meter=Meter()
    async def _handle(self,reader,writer):
        # Context is scoped to one request, including both spawned pump tasks.
        import contextvars
        bucket={'kind':None,'pending':0}
        route_context=_bucket.set(bucket)
        def upload(size):
            if bucket['kind'] is None:bucket['pending']+=size
            else:self.meter.add(bucket['kind'],'upload',size)
        def download(size):self.meter.add(bucket['kind'],'download',size)
        try:await super()._handle(Reader(reader,upload),Writer(writer,download))
        finally:_bucket.reset(route_context)
    def set_destination(self,kind):
        row=_bucket.get();row['kind']=kind
        self.meter.add(kind,'upload',row['pending']);row['pending']=0

import contextvars
_bucket=contextvars.ContextVar('entry_meter_bucket')
