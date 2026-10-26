"""Device and loopback inputs share exactly one owned core and its policies."""
import asyncio
from .proxy import ProxyServer


class SharedProxy:
    def __init__(self, config, core):
        self.primary = ProxyServer(config, core)
        local = dict(config, listen_host='127.0.0.1', allowed_clients=['127.0.0.1'],
                     listen_port=config['local_proxy_port'], product_mode='clash', shared_core=False)
        self.local = ProxyServer(local, core)

    async def start(self):
        try:
            await self.primary.start()
            await self.local.start()
        except BaseException:
            await self.close()
            raise

    async def close(self):
        await asyncio.gather(self.primary.close(), self.local.close())

    def snapshot(self):
        rows = [self.primary.snapshot(), self.local.snapshot()]
        clients = {}
        for row in rows:
            for client in row['clients']:
                previous = clients.setdefault(client['ip'], dict(ip=client['ip'], active=0, requests=0, last_seen=0))
                for key in ('active','requests'): previous[key] += client[key]
                previous['last_seen'] = max(previous['last_seen'], client['last_seen'])
        result = {key: sum(row[key] for row in rows) for key in self.primary.stats}
        result.update(kind='statistics', clients=list(clients.values())[:256],
                      devices=sum(row['active'] > 0 for row in clients.values()), truncated=len(clients)>256)
        return result

    def status(self):
        first, second = self.primary.status(), self.local.status()
        result = dict(first)
        statistics = self.snapshot()
        active = [row for row in statistics['clients'] if row['active']]
        result.update(shared_core=True, local_address=second['address'],
                      connected_clients=len(active), active_connections=statistics['active'],
                      client_ips=sorted(row['ip'] for row in active), clients=statistics['clients'],
                      stats={key: statistics[key] for key in self.primary.stats})
        result['traffic'] = {scope: {key: first['traffic'][scope][key]+second['traffic'][scope][key]
                                   for key in first['traffic'][scope]} for scope in ('local','external')}
        priorities = ('preparing','waking','forwarding','error','listening','stopped')
        result['state'] = min((first['state'],second['state']), key=priorities.index)
        result['error'] = first.get('error') or second.get('error','')
        return result
