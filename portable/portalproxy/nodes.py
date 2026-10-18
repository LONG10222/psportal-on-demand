"""Node controls for our owned Mihomo only; no existing-client controller access."""
import asyncio
import time
from urllib.parse import quote, urlencode

GROUP_TYPES = {'Selector', 'URLTest', 'Fallback'}
SKIP_TYPES = {'Direct', 'DIRECT', 'Reject', 'RejectDrop', 'Compatible', 'Pass', 'Dns'}


def valid_name(value):
    return (isinstance(value, str) and bool(value) and len(value.encode('utf-8')) <= 256
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def validate_policies(value):
    if not isinstance(value, dict) or len(value) > 32:
        raise ValueError('node_policies must contain at most 32 groups')
    result = {}
    for group, policy in value.items():
        if not valid_name(group) or not isinstance(policy, dict):
            raise ValueError('Invalid node policy')
        mode = policy.get('mode')
        if mode not in ('manual', 'latency') or (mode == 'manual' and not valid_name(policy.get('name'))):
            raise ValueError('Invalid node policy')
        result[group] = dict(mode=mode, **({'name': policy['name']} if mode == 'manual' else {}))
    return result


class NodeControl:
    def __init__(self, core):
        self.core = core
        self.policies = validate_policies(core.config.get('node_policies', {}))
        self.lock = asyncio.Lock()
        self.last_test = {}
        self.delays = {}
        self.messages = {}
        self.active_group = None

    async def request(self, path, method='GET', payload=None, timeout=2):
        return await asyncio.to_thread(self.core._request, path, method, payload, timeout)

    async def inventory(self):
        data = await self.request('/proxies')
        result = data.get('proxies', {})
        if not isinstance(result, dict):
            raise ValueError('Invalid node inventory')
        return result

    def group(self, inventory, name):
        item = inventory.get(name, {}) if valid_name(name) else {}
        if item.get('type') not in GROUP_TYPES or not isinstance(item.get('all'), list):
            raise ValueError('Choose a selectable proxy group')
        return item

    async def select(self, group, name):
        path = '/proxies/' + quote(group, safe='')
        await self.request(path, 'PUT', {'name': name})
        current = await self.request(path)
        # Fallback / URLTest report a fixed override, Selector reports now.
        if current.get('fixed', current.get('now')) != name and current.get('now') != name:
            raise ValueError('Node selection could not be verified')

    async def restore(self):
        if not self.policies:
            return
        inventory = await self.inventory()
        for group, policy in self.policies.items():
            if policy['mode'] == 'manual':
                item = self.group(inventory, group)
                if policy['name'] not in item['all']:
                    raise ValueError('Saved node is missing; import the subscription again')
                await self.select(group, policy['name'])
            else:
                self.last_test[group] = 0

    def snapshot(self, inventory, selected=None):
        groups = [name for name, item in inventory.items() if valid_name(name)
                  and isinstance(item, dict) and item.get('type') in GROUP_TYPES][:128]
        selected = selected or self.active_group
        group = selected if selected in groups else next((g for g in groups if g != 'GLOBAL'), groups[0] if groups else '')
        item = inventory.get(group, {})
        rows = []
        for name in item.get('all', []):
            node = inventory.get(name, {})
            if not valid_name(name) or not isinstance(node, dict):
                continue
            if node.get('type') in SKIP_TYPES:
                continue
            history = node.get('history') or []
            delay = self.delays.get((group, name), history[-1].get('delay') if history and isinstance(history[-1], dict) else None)
            rows.append(dict(name=name, type=str(node.get('type', ''))[:32],
                             delay=delay if type(delay) is int and delay > 0 else None,
                             selected=name == item.get('now')))
            if len(rows) == 500:
                break
        current = item.get('now', '')
        return dict(kind='nodes', groups=groups, group=group, current=current if valid_name(current) else '',
                    rows=rows, total=len(item.get('all', [])), policies=self.policies,
                    message=self.messages.get(group, ''))

    async def test(self, inventory, group, choose=False):
        item = self.group(inventory, group)
        names = [name for name in item['all'] if valid_name(name)
                 and inventory.get(name, {}).get('type') not in SKIP_TYPES][:500]
        if not names:
            raise ValueError('No proxy nodes available in this group')
        # Four concurrent probes; each uses the owned core and a fixed health URL.
        # Failed probes are never treated as zero-latency winners.
        semaphore = asyncio.Semaphore(4)
        async def probe(name):
            async with semaphore:
                try:
                    query = urlencode({'url': self.core.config['health_url'], 'timeout': 3000})
                    result = await self.request('/proxies/' + quote(name, safe='') + '/delay?' + query, timeout=4)
                    delay = result.get('delay')
                    delay = delay if type(delay) is int and 0 < delay <= 65535 else None
                except (OSError, ValueError, RuntimeError):
                    delay = None
                self.delays[group, name] = delay
                return name, delay
        results = await asyncio.gather(*(probe(name) for name in names))
        self.last_test[group] = time.monotonic()
        alive = [(delay, name) for name, delay in results if delay is not None]
        if choose:
            if not alive:
                self.messages[group] = 'All latency probes failed; current selection kept.'
                return
            delay, name = min(alive)
            await self.select(group, name)
            self.messages[group] = 'Lowest-latency node selected.'
        else:
            self.messages[group] = 'Latency test finished.' if alive else 'All latency probes failed; current selection kept.'

    async def command(self, action, group=None, name=None, background=False):
        async with self.lock:
            if action in ('select', 'latency') and group not in self.policies and len(self.policies) >= 32:
                raise ValueError('At most 32 group policies can be saved')
            if background:
                # Check and reserve atomically: an idle stop must never be
                # followed by a background probe that wakes the core again.
                async with self.core.lock:
                    if self.core.state != 'running' or self.core.process is None:
                        return
                    self.core.active += 1
            else:
                await self.core.acquire()
            try:
                inventory = await self.inventory()
                if action == 'select':
                    item = self.group(inventory, group)
                    if not valid_name(name) or name not in item['all'] or inventory.get(name, {}).get('type') in SKIP_TYPES:
                        raise ValueError('Choose a proxy node from this group')
                    await self.select(group, name)
                    self.policies[group] = dict(mode='manual', name=name)
                    self.messages[group] = 'Node switched. Existing connections keep their route.'
                elif action in ('latency', 'test'):
                    self.group(inventory, group)
                    if action == 'latency':
                        self.policies[group] = dict(mode='latency')
                    await self.test(inventory, group, choose=action == 'latency')
                elif action != 'nodes':
                    raise ValueError('Unknown node action')
                if group and not background:
                    self.active_group = group
                self.core.config['node_policies'] = dict(self.policies)
                return self.snapshot(await self.inventory(), group)
            finally:
                await self.core.release()

    async def tick(self):
        if self.lock.locked():
            return
        interval = max(30, self.core.config.get('health_interval', 300))
        for group, policy in list(self.policies.items()):
            if (self.core.state != 'running' or policy['mode'] != 'latency'
                    or time.monotonic() - self.last_test.get(group, 0) < interval):
                continue
            try:
                await self.command('latency', group, background=True)
            except (OSError, ValueError, RuntimeError):
                self.last_test[group] = time.monotonic()
                self.messages[group] = 'Latency test failed; current selection kept.'
