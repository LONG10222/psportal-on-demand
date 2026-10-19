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
    """Compatibility view over the single owned selector/policy implementation.

    The public list view is the current group's runtime inventory; older desktop
    command/event clients use the same controller, validation and saved policies.
    No second background selector is allowed to fight CoreManager's decisions.
    """
    def __init__(self, core):
        self.core = core
        self.policies = validate_policies(core.config.get('node_policies', {}))
        self.lock = asyncio.Lock()
        self.last_test = {}
        self.messages = {}
        self.active_group = None
        self.fastest = {}

    def __iter__(self):
        return iter(self.core.node_rows)

    def __len__(self):
        return len(self.core.node_rows)

    def __getitem__(self, key):
        return self.core.node_rows[key]

    def __eq__(self, other):
        return self.core.node_rows == other

    async def request(self, path, method='GET', payload=None, timeout=2):
        return await asyncio.to_thread(self.core._request, path, method, payload, timeout)

    async def inventory(self):
        await self.core._refresh_nodes()
        return self.core.owned_inventory

    def group(self, inventory, name):
        # Only explicit owned groups with eligible leaf members are actionable;
        # fallback/url-test use Mihomo's fixed override, leaving rules unchanged.
        item = inventory.get(name, {}) if valid_name(name) else {}
        allowed = ({group['name'] for group in self.core.groups}
                   if self.core.config.get('profile_file') else {'PORTAL'})
        if name not in allowed or not isinstance(item, dict) or item.get('type') not in ('Selector', 'select', 'Fallback', 'URLTest'):
            raise ValueError('Choose a selectable proxy group')
        return item

    def save_policy(self, group, mode, name=''):
        if group not in self.policies and len(self.policies) >= 32:
            raise ValueError('At most 32 group policies can be saved')
        if mode in ('fixed', 'fastest'):
            self.policies[group] = (dict(mode='manual', name=name) if mode == 'fixed' else dict(mode='latency'))
        else:
            self.policies.pop(group, None)
        self.core.config['node_policies'] = dict(self.policies)

    async def restore(self):
        if not self.policies:
            return
        inventory = await self.inventory()
        previous_group = self.core.selection_group
        previous_mode = self.core.profile_mode
        try:
            for group, policy in self.policies.items():
                item = self.group(inventory, group)
                if policy['mode'] == 'manual':
                    await self.core._refresh_nodes(group)
                    if policy['name'] not in {node['name'] for node in self.core.node_rows}:
                        raise ValueError('Saved node is missing; import the subscription again')
                    await self.core._put_selection(policy['name'])
                else:
                    self.last_test[group] = 0
        finally:
            self.core.selection_group = previous_group
            self.core.profile_mode = previous_mode
            await self.core._refresh_nodes()

    def snapshot(self, inventory, selected=None):
        groups = ([item['name'] for item in self.core.groups]
                  if self.core.config.get('profile_file') else (['PORTAL'] if 'PORTAL' in inventory else []))
        selected = selected or self.active_group or self.core.selection_group
        group = selected if selected in groups else (groups[0] if groups else '')
        item = inventory.get(group, {})
        members = next((entry['members'] for entry in self.core.groups if entry['name'] == group), None)
        known = {row['name']: row for row in self.core.node_rows} if (not self.core.config.get('profile_file') or group == self.core.selection_group) else {}
        rows = []
        for name in item.get('all', []):
            node = inventory.get(name, {})
            if (not valid_name(name) or not isinstance(node, dict)
                    or name in self.core.ambiguous_nodes
                    or (members is not None and name not in members)
                    or node.get('all') is not None or str(node.get('type', '')).lower() in
                    ('direct', 'reject', 'rejectdrop', 'compatible', 'pass', 'passrule', 'rematch', 'dns',
                     'relay', 'selector', 'select', 'fallback', 'urltest', 'url-test', 'loadbalance', 'load-balance')
                    or not node.get('type')):
                continue
            history = node.get('history') or []
            delay = known.get(name, {}).get('delay_ms', history[-1].get('delay') if isinstance(history, list) and history and isinstance(history[-1], dict) else None)
            rows.append(dict(name=name, type=str(node.get('type', ''))[:32],
                             delay=delay if type(delay) in (int, float) and 0 <= delay <= 86400000 else None,
                             selected=name == item.get('now')))
            if len(rows) == 500:
                break
        current = item.get('now', '')
        return dict(kind='nodes', groups=groups[:128], group=group,
                    current=current if valid_name(current) else '', rows=rows,
                    total=len(item.get('all', [])), policies=dict(self.policies),
                    message=self.messages.get(group, ''))

    async def command(self, action, group=None, name=None, background=False):
        from .core import CoreError
        async with self.lock:
            if action not in ('nodes', 'select', 'test', 'latency'):
                raise ValueError('Unknown node action')
            reserved = False
            if background:
                # Reserve atomically before calling the shared command so an
                # idle stop can never turn a periodic probe into a wakeup.
                async with self.core.lock:
                    if self.core.state != 'running' or self.core.process is None:
                        return
                    self.core.active += 1
                    reserved = True
            try:
                if action == 'nodes':
                    await self.core.acquire()
                    try:
                        async with self.core.lock:
                            await self.core._refresh_nodes()
                            if self.core.config.get('profile_file'):
                                chosen = group or self.active_group or next((g['name'] for g in self.core.groups), None)
                                if chosen:
                                    await self.core._refresh_nodes(chosen)
                    finally:
                        await self.core.release()
                elif action == 'select':
                    await self.core.select_node('fixed', name, selection_group=group)
                    self.messages[group] = 'Node switched. Existing connections keep their route.'
                elif action == 'test':
                    await self.core.test_nodes(group)
                    self.messages[group] = ('Latency test finished.' if any(n.get('healthy') for n in self.core.node_rows)
                                            else 'All latency probes failed; current selection kept.')
                else:
                    try:
                        await self.core.select_node('fastest', selection_group=group)
                        self.messages[group] = 'Lowest-latency node selected.'
                    except CoreError as exc:
                        if str(exc) != 'No healthy proxy node is available':
                            raise
                        # Keep the requested automatic policy for later retry,
                        # while select_node restores the exact existing route.
                        self.save_policy(group or 'PORTAL', 'fastest')
                        self.messages[group] = 'All latency probes failed; current selection kept.'
                    self.last_test[group or 'PORTAL'] = time.monotonic()
                if group and not background:
                    self.active_group = group
                return self.snapshot(self.core.owned_inventory, group)
            finally:
                if reserved:
                    await self.core.release()

    async def tick(self):
        if self.lock.locked():
            return
        interval = max(30, self.core.config.get('health_interval', 300))
        for group, policy in list(self.policies.items()):
            if (self.core.state != 'running' or policy['mode'] != 'latency'
                    or time.monotonic() - self.last_test.get(group, 0) < interval):
                continue
            # Scope background probes to each saved group, restoring the group
            # currently shown by the window afterward.
            previous_group = self.core.selection_group
            previous_mode = self.core.profile_mode
            previous_config = (self.core.config['selection_mode'], self.core.config['preferred_node'])
            previous_fastest = self.core.fastest
            try:
                await self.command('latency', group, background=True)
            except (OSError, ValueError, RuntimeError):
                self.last_test[group] = time.monotonic()
                self.messages[group] = 'Latency test failed; current selection kept.'
            finally:
                if self.core.config.get('profile_file') and previous_group != self.core.selection_group:
                    async with self.core.lock:
                        self.core.selection_group = previous_group
                        self.core.profile_mode = previous_mode
                        self.core.config['selection_mode'], self.core.config['preferred_node'] = previous_config
                        self.core.fastest = previous_fastest
                        if self.core.state == 'running':
                            await self.core._refresh_nodes()
