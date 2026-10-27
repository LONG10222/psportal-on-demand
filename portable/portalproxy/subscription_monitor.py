"""Scoped, bounded accounting refresh. URLs never enter the public snapshot."""
import hashlib
import queue
import threading
import time
from urllib.parse import urlsplit


def quota_snapshot(value):
    if not isinstance(value,dict):return None
    result={key:value[key] for key in ('upload','download','total','expire','updated_at')
            if type(value.get(key)) is int and 0<=value[key]<=(253402300799 if key in ('expire','updated_at') else 2**63-1)}
    if not any(key in result for key in ('upload','download','total','expire')):return None
    for key,limit in (('source',253),('provider_name',120),('source_kind',32)):
        if isinstance(value.get(key),str):result[key]=''.join(c for c in value[key] if ord(c)>=32 and ord(c)!=127)[:limit]
    return result


def descriptor(url='', cached=None, *, identity='', name='', linked=False):
    if not isinstance(url, str): url = ''
    if url:
        try:
            parsed = urlsplit(url)
            if (len(url) > 8192 or parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.isascii()
                    or parsed.username or parsed.password or parsed.fragment or parsed.port not in (None, 443)
                    or any(ord(c) <= 32 for c in url) or any(c in parsed.netloc for c in '\\%')):
                url = ''
        except ValueError: url = ''
    key = hashlib.sha256((identity+'\0'+url).encode()).hexdigest()
    return dict(key=key, url=url, cached=quota_snapshot(cached), name=name[:120], linked=linked)


def fetch(url):
    from .core import download_subscription
    return download_subscription(url, None, headers_only=True)


class AccountingMonitor:
    def __init__(self, loader=fetch, clock=time.monotonic):
        self.loader, self.clock = loader, clock
        self.events = queue.Queue()
        self.current = None
        self.info = None
        self.busy = False
        self.next_refresh = 0
        self.last_attempt = -100
        self.message = '尚无订阅数据'
        self.saved = {}

    def tick(self, source, *, visible=True, force=False):
        if source['key'] != (self.current or {}).get('key'):
            if self.current and self.info:
                self.saved[self.current['key']]=dict(self.info)
                while len(self.saved)>8:self.saved.pop(next(iter(self.saved)))
            self.current = source
            cached=source.get('cached') if isinstance(source.get('cached'),dict) else None
            saved=self.saved.get(source['key'])
            candidate=cached if cached and (not saved or cached.get('updated_at',0)>saved.get('updated_at',0)) else saved or cached
            self.info=dict(candidate) if candidate else None
            self.next_refresh = 0
            self.last_attempt = -100
        else:
            self.current = source
        while True:
            try: key, result = self.events.get_nowait()
            except queue.Empty: break
            self.busy = False
            if key != source['key']: continue
            result=quota_snapshot(result)
            has_data = result is not None
            if has_data:
                complete=all(type(result.get(k)) is int and result[k]>=0 for k in ('upload','download','total'))
                previous_complete=isinstance(self.info,dict) and all(type(self.info.get(k)) is int for k in ('upload','download','total'))
                if previous_complete and not complete:
                    self.message='更新失败或数据不完整 · 保留上次数据'
                    continue
                self.info = dict(result)
                self.info['source_kind'] = 'clash-live' if source['linked'] else 'server'
                if source['name']: self.info['provider_name'] = source['name']
                self.message = '自动刷新 · 每 60 秒向服务端核对'
            else:
                self.message = '更新失败或服务端未提供用量 · 保留上次数据'
        if not source['url']:
            self.message = '更新失败，读取配置中 · 保留上次数据' if source.get('stale') else '本地快照 · 没有可刷新的订阅链接'
            return
        now = self.clock()
        if not visible or self.busy or now-self.last_attempt < 5 or (not force and now < self.next_refresh): return
        self.busy = True
        self.last_attempt = now
        self.next_refresh = now+60
        self.message = '正在向订阅服务端刷新…'
        key, url = source['key'], source['url']
        def work():
            try: result = self.loader(url)
            except Exception: result = None
            self.events.put((key, result))
        threading.Thread(target=work, daemon=True).start()
