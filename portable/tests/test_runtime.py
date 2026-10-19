"""Offline metrics, live owned-selector controls and measured policy regression tests."""
import asyncio
import io
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from portalproxy import backend
from portalproxy.config import DEFAULTS, render, validate
from portalproxy.core import CoreManager, CoreError
from portalproxy.existing_proxy import ExistingProxy
from portalproxy.policy import FastestSelection
from portalproxy.proxy import ProxyServer
from portalproxy.runtime import RuntimeControl, validate_command


def samples(a=100, b=200, c=None):
    values = [{'name': 'HK', 'healthy': True, 'delay_ms': a},
              {'name': 'JP', 'healthy': True, 'delay_ms': b}]
    if c is not None:
        values.append({'name': 'US', 'healthy': True, 'delay_ms': c})
    return values


class FastestPolicyTests(unittest.TestCase):
    def test_actual_zero_latency_is_healthy(self):
        self.assertEqual(FastestSelection().choose(samples(a=0), now=0), 'HK')

    def test_sustained_advantage_and_hold_down(self):
        policy = FastestSelection()
        self.assertEqual(policy.choose(samples(), now=0), 'HK')
        self.assertEqual(policy.choose(samples(a=200, b=50), now=2), 'HK')
        self.assertEqual(policy.choose(samples(a=200, b=50), now=29), 'HK')
        self.assertEqual(policy.choose(samples(a=200, b=50), now=30), 'JP')
        self.assertEqual(policy.choose(samples(a=0, b=200), now=31), 'JP')
        self.assertEqual(policy.choose(samples(a=0, b=200), now=61), 'HK')

    def test_partial_round_breaks_consecutive_challenge(self):
        policy = FastestSelection()
        policy.choose(samples(), now=0)
        policy.choose(samples(a=200, b=50), now=31)
        self.assertEqual(policy.rounds, 1)
        self.assertEqual(policy.choose(samples(a=200, b=50), now=32, measured=False), 'HK')
        self.assertEqual((policy.challenger, policy.rounds), ('', 0))
        self.assertEqual(policy.choose(samples(a=200, b=50), now=33), 'HK')
        self.assertEqual(policy.choose(samples(a=200, b=50), now=34), 'JP')

    def test_deadband_candidate_change_and_failed_incumbent(self):
        policy = FastestSelection()
        policy.choose(samples(), now=0)
        self.assertEqual(policy.choose(samples(a=100, b=50), now=31), 'HK')
        self.assertEqual(policy.choose(samples(a=200, b=50, c=100), now=32), 'HK')
        self.assertEqual(policy.choose(samples(a=200, b=100, c=30), now=33), 'HK')
        self.assertEqual(policy.choose(samples(a=200, b=50, c=100), now=34), 'HK')
        self.assertEqual(policy.choose(samples(a=200, b=50, c=100), now=35), 'JP')
        failed = samples(a=0, b=50)
        failed[1].update(healthy=False, delay_ms=None)
        self.assertEqual(policy.choose(failed, now=36), 'HK')
        self.assertEqual(policy.choose([], now=37), '')


class RuntimeSchemaTests(unittest.TestCase):
    def sample(self):
        return dict(event='status', state='listening', connected_clients=1, active_connections=2,
                    client_ips=['192.168.1.3'], node_management=True, busy=False,
                    last_command_id=1, nodes=[{'name': 'Tokyo', 'healthy': True, 'delay_ms': 0}],
                    groups=[{'name': 'Proxy', 'selected': 'Tokyo', 'eligible_node_count': 1}],
                    selection_group='Proxy', selection_mode='fixed')

    def test_valid_record_and_unknown_data_stripped(self):
        record = self.sample()
        record['secret'] = 'never forward'
        result = backend.parse_status(json.dumps(record))
        self.assertEqual(result['nodes'][0]['delay_ms'], 0)
        self.assertEqual(result['groups'][0]['name'], 'Proxy')
        self.assertNotIn('secret', result)

    def test_malformed_records_are_rejected(self):
        changes = ({'connected_clients': True}, {'busy': 'false'}, {'node_management': 1},
                   {'last_command_id': -1}, {'error': ['bad']}, {'client_ips': [None]},
                   {'client_ips': [['nested']]}, {'active_connections': 0},
                   {'nodes': [{'name': 'node', 'healthy': 'yes', 'delay_ms': 1}]},
                   {'nodes': [{'name': '\ud800'}]}, {'groups': [{'name': 2}]},
                   {'nodes': [{'name': 'node', 'delay_ms': float('nan')}]})
        for change in changes:
            with self.subTest(change=repr(change)):
                self.assertIsNone(backend.parse_status(json.dumps(dict(self.sample(), **change))))

    def test_recursive_and_duplicate_records_are_rejected(self):
        self.assertIsNone(backend.parse_status('[' * 20000 + '0' + ']' * 20000))
        for key, duplicate in (('nodes', {'name':'Tokyo','healthy':True}),
                               ('groups', {'name':'Proxy','selected':'Tokyo'})):
            value = self.sample()
            value[key] = [duplicate, duplicate]
            self.assertIsNone(backend.parse_status(json.dumps(value)))

    def test_maximum_escaped_node_and_group_inventory_fits(self):
        from portalproxy.runtime import MAX_STATUS_BYTES
        value = self.sample()
        names = [str(i).zfill(4) + '\\' * 252 for i in range(1000)]
        value['nodes'] = [{'name':name, 'healthy':True, 'delay_ms':0} for name in names]
        value['groups'] = [{'name':name, 'selected':name, 'eligible_node_count':1000} for name in names]
        raw = json.dumps(value, ensure_ascii=False)
        self.assertLess(len(raw.encode('utf-8')), MAX_STATUS_BYTES)
        self.assertEqual(len(backend.parse_status(raw)['nodes']), 1000)

    def test_commands_are_bounded_and_typed(self):
        for value in ({'command':'select','selection_mode':'fastest','switch_threshold_ms':True},
                      {'command':'prepare','request_id':-1}, {'command':'test','selection_group':'\n'},
                      {'command':'select','selection_mode':'fixed','preferred_node':12},
                      {'command':'prepare','arbitrary_url':'https://secret'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_command(value)
        process = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
        backend.send_command(process, 'select', selection_mode='fastest', request_id=3, selection_group='Proxy')
        self.assertEqual(json.loads(process.stdin.getvalue())['request_id'], 3)

    def test_merged_history_and_policies_are_bounded_and_redacted(self):
        record = dict(self.sample(), clients=[{'ip': '192.168.1.3', 'active': 2, 'requests': 4, 'last_seen': 10.0, 'secret': 'drop'}],
                      node_policies={'Proxy': {'mode': 'manual', 'name': 'Tokyo'}})
        record['nodes'][0]['type'] = 'Shadowsocks'
        parsed = backend.parse_status(json.dumps(record))
        self.assertEqual(parsed['node_policies']['Proxy']['name'], 'Tokyo')
        self.assertEqual(parsed['nodes'][0]['type'], 'Shadowsocks')
        self.assertNotIn('secret', parsed['clients'][0])
        record['clients'][0]['active'] = True
        self.assertIsNone(backend.parse_status(json.dumps(record)))
        from portalproxy.runtime import validate_legacy_command
        for name in ('bad\nname', 'bad\x7fname'):
            with self.assertRaises(ValueError):
                validate_legacy_command({'action': 'select', 'id': 1, 'group': 'Proxy', 'name': name})

    def test_render_has_complete_owned_selector_and_legacy_policy(self):
        result = render(dict(DEFAULTS, preferred_node='Tokyo', selection_mode='fixed'), 'secret')
        selector, legacy = result['proxy-groups']
        self.assertEqual(selector['type'], 'select')
        self.assertEqual(selector['use'], ['SUBSCRIPTION'])
        self.assertEqual(legacy['type'], 'fallback')
        self.assertIn('香港', legacy['filter'])
        self.assertFalse(result['tun']['enable'])


class DistinctClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_real_sockets_count_one_device_and_cleanup(self):
        proxy = ProxyServer(dict(listen_host='127.0.0.1', listen_port=0,
            allowed_clients=['127.0.0.1'], request_timeout=10), SimpleNamespace())
        await proxy.start()
        connections = []
        try:
            port = proxy.bound_addresses[0][1]
            for _ in range(2):
                connections.append(await asyncio.open_connection('127.0.0.1', port))
            for _ in range(20):
                if proxy.stats['active'] == 2: break
                await asyncio.sleep(.01)
            self.assertEqual(proxy.status()['connected_clients'], 1)
            self.assertEqual(proxy.status()['active_connections'], 2)
            self.assertEqual(proxy.status()['state'], 'listening')
            connections[0][1].close()
            await connections[0][1].wait_closed()
            for _ in range(20):
                if proxy.stats['active'] == 1: break
                await asyncio.sleep(.01)
            self.assertEqual(proxy.status()['connected_clients'], 1)
        finally:
            for _, writer in connections: writer.close()
            await proxy.close()
        self.assertEqual(proxy.status()['connected_clients'], 0)
        self.assertEqual(proxy.status()['active_connections'], 0)
        self.assertEqual(proxy.status()['state'], 'stopped')

    async def test_distinct_peer_refcounts_without_network_aliases(self):
        class PeerWriter:
            def __init__(self, peer): self.peer = peer
            def get_extra_info(self, key): return (self.peer, 12345) if key == 'peername' else None
            def close(self): pass
            async def wait_closed(self): pass
        proxy = ProxyServer(dict(listen_host='127.0.0.1', listen_port=0,
            allowed_clients=['192.168.1.2','192.168.1.3'], request_timeout=10), SimpleNamespace())
        tasks = [asyncio.create_task(proxy._handle(asyncio.StreamReader(), PeerWriter(ip)))
                 for ip in ('192.168.1.2','192.168.1.2','192.168.1.3')]
        try:
            for _ in range(20):
                if proxy.stats['active'] == 3: break
                await asyncio.sleep(.01)
            self.assertEqual(proxy.status()['connected_clients'], 2)
            self.assertEqual(proxy.status()['active_connections'], 3)
            tasks[0].cancel()
            await asyncio.gather(tasks[0], return_exceptions=True)
            self.assertEqual(proxy.status()['connected_clients'], 2)
            tasks[1].cancel()
            await asyncio.gather(tasks[1], return_exceptions=True)
            self.assertEqual(proxy.status()['client_ips'], ['192.168.1.3'])
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self.assertEqual(proxy.status()['connected_clients'], 0)
        self.assertEqual(proxy.status()['active_connections'], 0)

    async def test_denied_clients_are_never_counted(self):
        proxy = ProxyServer(dict(listen_host='127.0.0.1', listen_port=0,
            allowed_clients=['127.0.0.2']), SimpleNamespace())
        await proxy.start()
        reader, writer = await asyncio.open_connection('127.0.0.1', proxy.bound_addresses[0][1])
        self.assertIn(b'403', await reader.read())
        self.assertEqual(proxy.status()['connected_clients'], 0)
        writer.close()
        await proxy.close()


class OwnedSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = dict(DEFAULTS, data_dir=self.tmp.name)
        self.core = CoreManager(self.cfg)
        self.selected = {'PORTAL': 'PORTAL-AUTO', 'Work / Proxy': 'Tokyo'}
        self.inventory = {'PORTAL': {'type':'Selector','all':['PORTAL-AUTO','Tokyo','Hong Kong','REJECT'], 'now':'PORTAL-AUTO'},
            'PORTAL-AUTO': {'type':'Fallback','all':['Tokyo','Hong Kong'], 'now':'Hong Kong'},
            'Work / Proxy': {'type':'Selector','all':['Tokyo','Hong Kong','DIRECT','Nested'], 'now':'Tokyo'},
            'GLOBAL': {'type':'Selector','all':['Tokyo'], 'now':'Tokyo'},
            'Nested': {'type':'URLTest','all':['Tokyo'], 'now':'Tokyo'},
            'Tokyo': {'type':'Shadowsocks','alive':True,'history':[{'delay':50}]},
            'Hong Kong': {'type':'Shadowsocks','alive':True,'history':[{'delay':100}]},
            'DIRECT': {'type':'Direct'}}
        self.calls = []
        def request(path, method='GET', payload=None, timeout=2):
            from urllib.parse import unquote
            self.calls.append((path, method, payload))
            if path == '/providers/proxies': return {'providers': {}}
            if path == '/proxies':
                for group, selected in self.selected.items(): self.inventory[group]['now'] = selected
                return {'proxies': self.inventory}
            if '/delay?' in path:
                return {'delay': 0 if 'Tokyo' in path else 100}
            group = unquote(path.removeprefix('/proxies/'))
            if method == 'PUT':
                self.selected[group] = payload['name']
                return {}
            return {'now': self.selected[group]}
        self.core._request = request
        self.core.acquire = AsyncMock(return_value=('127.0.0.1', 10082))
        self.core.release = AsyncMock()

    async def asyncTearDown(self):
        await self.core.close()
        self.tmp.cleanup()

    async def test_live_manual_then_measured_fastest_keeps_full_pool(self):
        await self.core.select_node('fixed', 'Hong Kong')
        self.assertEqual(self.selected['PORTAL'], 'Hong Kong')
        await self.core.select_node('fixed', 'Tokyo')
        self.assertEqual(self.selected['PORTAL'], 'Tokyo')
        await self.core.select_node('fastest')
        self.assertEqual(self.selected['PORTAL'], 'Tokyo')
        self.assertEqual({n['name'] for n in self.core.nodes}, {'Tokyo','Hong Kong'})
        self.assertEqual(self.core.nodes[0]['delay_ms'], 0)
        self.assertTrue(any('/delay?' in path for path, _, _ in self.calls))
        self.assertFalse(any(path.startswith('/configs') for path, _, _ in self.calls))

    async def test_group_policies_and_protocols_share_one_runtime(self):
        self.cfg['profile_file'] = '/fixture.yaml'
        self.core.profile_groups = {'Work / Proxy', 'Nested'}
        self.selected['Nested'] = 'Tokyo'
        await self.core.nodes.command('nodes')
        state = await self.core.nodes.command('select', 'Work / Proxy', 'Hong Kong')
        self.assertEqual(state['current'], 'Hong Kong')
        self.assertEqual(state['rows'][0]['type'], 'Shadowsocks')
        self.assertEqual(self.core.status()['node_policies']['Work / Proxy'], {'mode': 'manual', 'name': 'Hong Kong'})
        await self.core.select_node('fastest', selection_group='Nested')
        self.assertEqual(self.core.nodes.policies['Nested'], {'mode': 'latency'})
        self.assertEqual(self.core.nodes.policies['Work / Proxy']['name'], 'Hong Kong')
        await self.core.nodes.restore()
        self.assertEqual(self.selected['Work / Proxy'], 'Hong Kong')

    async def test_background_other_group_preserves_display_and_manual_policy(self):
        self.cfg['profile_file'] = '/fixture.yaml'
        self.core.profile_groups = {'Work / Proxy', 'Other'}
        self.inventory['Other'] = {'type': 'Fallback', 'all': ['Tokyo', 'Hong Kong'], 'now': 'Tokyo'}
        self.selected['Other'] = 'Tokyo'
        await self.core.select_node('fastest', selection_group='Other')
        await self.core.select_node('fixed', 'Hong Kong', selection_group='Work / Proxy')
        self.core.state = 'running'
        self.core.process = SimpleNamespace(returncode=0)
        self.core.nodes.last_test['Other'] = 0
        await self.core.nodes.tick()
        self.assertEqual(self.core.selection_group, 'Work / Proxy')
        self.assertEqual(self.core.selection_mode, 'fixed')
        self.assertEqual(self.core.config['preferred_node'], 'Hong Kong')
        self.assertEqual(self.core.selected, 'Hong Kong')
        self.assertEqual(self.core.nodes.policies['Other'], {'mode': 'latency'})
        self.core.process = None
        self.core.state = 'stopped'
        calls = len(self.calls)
        await self.core.nodes.tick()
        self.assertEqual(len(self.calls), calls)

    async def test_fallback_fixed_override_is_verified_and_restored(self):
        self.cfg['profile_file'] = '/fixture.yaml'
        self.core.profile_groups = {'Work / Proxy'}
        self.inventory['Work / Proxy']['type'] = 'Fallback'
        original = self.core._request
        def request(path, method='GET', payload=None, timeout=2):
            result = original(path, method, payload, timeout)
            if path == '/proxies/Work%20%2F%20Proxy' and method == 'GET':
                return {'now': 'Tokyo', 'fixed': self.selected['Work / Proxy']}
            return result
        self.core._request = request
        await self.core.select_node('fixed', 'Hong Kong', selection_group='Work / Proxy')
        self.assertEqual(self.selected['Work / Proxy'], 'Hong Kong')
        # The desired fixed override and effective healthy route are distinct.
        self.assertEqual(self.core.selected, 'Tokyo')
        self.assertEqual(self.core.nodes.policies['Work / Proxy']['name'], 'Hong Kong')
        await self.core.nodes.restore()
        self.assertEqual(self.selected['Work / Proxy'], 'Hong Kong')

    async def test_failed_fallback_change_restores_unfixed_original_policy(self):
        self.cfg['profile_file'] = '/fixture.yaml'
        self.core.profile_groups = {'Work / Proxy'}
        self.inventory['Work / Proxy']['type'] = 'Fallback'
        original = self.core._request
        fixed, verification_failed, deleted = '', False, False
        def request(path, method='GET', payload=None, timeout=2):
            nonlocal fixed, verification_failed, deleted
            if path == '/proxies/Work%20%2F%20Proxy':
                if method == 'PUT':
                    fixed = payload['name']
                    return {}
                if method == 'DELETE':
                    fixed, deleted = '', True
                    return {}
                if fixed == 'Hong Kong' and not verification_failed:
                    verification_failed = True
                    raise OSError('fixture verification failure')
                return {'now': fixed or 'Tokyo', 'fixed': fixed}
            return original(path, method, payload, timeout)
        self.core._request = request
        with self.assertRaises(CoreError):
            await self.core.select_node('fixed', 'Hong Kong', selection_group='Work / Proxy')
        self.assertTrue(deleted)
        self.assertEqual(fixed, '')
        self.assertEqual(self.core.nodes.policies, {})

    async def test_legacy_and_structured_commands_share_busy_gate(self):
        gate = asyncio.Event()
        async def prepare(*args):
            await gate.wait()
        self.core.prepare = prepare
        proxy = ProxyServer(dict(listen_host='127.0.0.1', listen_port=10081, allowed_clients=['127.0.0.1']), self.core)
        control = RuntimeControl(proxy, self.core, emit=lambda *args, **kwargs: None)
        control.accept('{"command":"prepare","request_id":1}')
        pending = control.task
        with patch('portalproxy.runtime.emit') as emit:
            control.accept('{"action":"select","id":2,"group":"PORTAL","name":"Tokyo"}')
            self.assertEqual(emit.call_args.args[0]['kind'], 'control_error')
            self.assertEqual(emit.call_args.args[0]['id'], 2)
            self.assertFalse(any(method == 'PUT' for _, method, _ in self.calls))
        gate.set()
        await pending

    async def test_missing_fixed_node_does_not_change_selection(self):
        await self.core.select_node('fixed', 'Tokyo')
        with self.assertRaises(CoreError): await self.core.select_node('fixed', 'missing')
        self.assertEqual(self.selected['PORTAL'], 'Tokyo')
        self.assertEqual(self.core.config['selection_mode'], 'fixed')

    async def test_profile_explicit_owned_group_preserves_graph(self):
        self.cfg['profile_file'] = '/not-read-in-fixture.yaml'
        self.core.profile_groups = {'Work / Proxy', 'Nested'}
        await self.core.prepare()
        self.assertEqual([g['name'] for g in self.core.groups], ['Work / Proxy', 'Nested'])
        self.assertEqual(self.core.nodes, [])
        self.assertFalse(any(method == 'PUT' for _, method, _ in self.calls))
        with self.assertRaises(CoreError): await self.core.select_node('fixed', 'Tokyo', selection_group='GLOBAL')
        await self.core.test_nodes('Work / Proxy')
        self.assertEqual(self.selected['Work / Proxy'], 'Tokyo')
        self.assertEqual({n['name'] for n in self.core.nodes}, {'Tokyo','Hong Kong'})
        with self.assertRaises(CoreError): await self.core.select_node('fixed', 'DIRECT', selection_group='Work / Proxy')
        with self.assertRaises(CoreError): await self.core.select_node('fixed', 'Nested', selection_group='Work / Proxy')
        await self.core.select_node('fixed', 'Hong Kong', selection_group='Work / Proxy')
        self.assertEqual(self.selected['Work / Proxy'], 'Hong Kong')
        await self.core.select_node('fastest', selection_group='Work / Proxy')
        self.assertEqual(self.selected['Work / Proxy'], 'Tokyo')
        self.assertFalse(any(path.startswith('/configs') for path, _, _ in self.calls))
        self.assertTrue(any(path == '/proxies/Work%20%2F%20Proxy' and method == 'PUT' for path, method, _ in self.calls))

    async def test_profile_partial_put_failure_restores_exact_previous_choice(self):
        self.cfg['profile_file'] = '/fixture.yaml'
        self.core.profile_groups = {'Work / Proxy'}
        await self.core.test_nodes('Work / Proxy')
        original = self.core._request
        changed = False
        failed = False
        def request(path, method='GET', payload=None, timeout=2):
            nonlocal changed, failed
            if method == 'PUT' and payload['name'] == 'Hong Kong': changed = True
            if path == '/proxies/Work%20%2F%20Proxy' and method == 'GET' and changed and not failed:
                failed = True
                raise OSError('fixture verification failure')
            return original(path, method, payload, timeout)
        self.core._request = request
        with self.assertRaises(CoreError):
            await self.core.select_node('fixed', 'Hong Kong', selection_group='Work / Proxy')
        self.assertEqual(self.selected['Work / Proxy'], 'Tokyo')
        self.assertEqual(self.core.selected, 'Tokyo')
        self.assertEqual(self.core.selection_mode, 'profile')

    async def test_unverifiable_partial_selection_clears_stale_selection(self):
        self.cfg['profile_file'] = '/fixture.yaml'
        self.core.profile_groups = {'Work / Proxy'}
        await self.core.test_nodes('Work / Proxy')
        original = self.core._request
        changed = False
        def request(path, method='GET', payload=None, timeout=2):
            nonlocal changed
            if changed:
                raise OSError('fixture controller unavailable')
            result = original(path, method, payload, timeout)
            if method == 'PUT' and payload['name'] == 'Hong Kong': changed = True
            return result
        self.core._request = request
        with self.assertRaises(CoreError):
            await self.core.select_node('fixed', 'Hong Kong', selection_group='Work / Proxy')
        self.assertEqual(self.selected['Work / Proxy'], 'Hong Kong')
        self.assertEqual(self.core.selected, '')
        self.assertIn('unverified', self.core.last_error)

    async def test_failed_new_group_choice_preserves_prior_policy_scope(self):
        self.cfg['profile_file'] = '/fixture.yaml'
        self.inventory['Other'] = {'type':'Selector','all':['Tokyo'], 'now':'Tokyo'}
        self.selected['Other'] = 'Tokyo'
        self.core.profile_groups = {'Work / Proxy', 'Other'}
        await self.core.select_node('fastest', selection_group='Work / Proxy')
        old_fastest = dict(vars(self.core.fastest))
        with self.assertRaises(CoreError):
            await self.core.select_node('fixed', 'missing', selection_group='Other')
        self.assertEqual(self.core.selection_group, 'Work / Proxy')
        self.assertEqual(self.core.selection_mode, 'fastest')
        self.assertEqual(vars(self.core.fastest), old_fastest)
        self.assertEqual(self.selected['Other'], 'Tokyo')

    async def test_provider_nodes_use_provider_health_endpoint(self):
        original = self.core._request
        provider_nodes = [dict(self.inventory.pop(name), name=name) for name in ('Tokyo','Hong Kong')]
        def request(path, method='GET', payload=None, timeout=2):
            if path == '/providers/proxies':
                return {'providers': {'SUBSCRIPTION': {'proxies': provider_nodes}}}
            if '/healthcheck?' in path:
                self.calls.append((path, method, payload))
                return {'delay': 20 if '/Tokyo/' in path else 100}
            return original(path, method, payload, timeout)
        self.core._request = request
        await self.core.select_node('fastest')
        self.assertEqual(self.selected['PORTAL'], 'Tokyo')
        self.assertTrue(any(path.startswith('/providers/proxies/SUBSCRIPTION/Tokyo/healthcheck?') for path, _, _ in self.calls))
        self.assertFalse(any('/delay?' in path for path, _, _ in self.calls))

    async def test_missing_metadata_is_not_a_selectable_leaf(self):
        del self.inventory['Tokyo']
        await self.core._refresh_nodes()
        self.assertEqual([n['name'] for n in self.core.nodes], ['Hong Kong'])
        with self.assertRaises(CoreError): await self.core.select_node('fixed', 'Tokyo')

    async def test_external_leaf_protocols_are_not_native_subset(self):
        for name, kind in (('WireGuard node','WireGuard'),('SSH node','Ssh'),('Mieru node','Mieru'),('New adapter','FutureAdapter')):
            self.inventory[name] = {'type':kind, 'alive':True, 'history':[{'delay':10}]}
            self.inventory['PORTAL']['all'].append(name)
        self.inventory['Bypass'] = {'type':'PassRule'}
        self.inventory['PORTAL']['all'].append('Bypass')
        await self.core._refresh_nodes()
        names = {n['name'] for n in self.core.nodes}
        self.assertTrue({'WireGuard node','SSH node','Mieru node','New adapter'} <= names)
        self.assertNotIn('Bypass', names)

    async def test_controller_response_limit_is_explicit(self):
        response = io.BytesIO(b'x' * (1024 * 1024 + 1))
        opener = SimpleNamespace(open=lambda *args, **kwargs: response)
        with patch('portalproxy.core.urllib.request.build_opener', return_value=opener):
            with self.assertRaisesRegex(CoreError, 'Controller response too large'):
                CoreManager._request(self.core, '/proxies')

    async def test_partial_probe_keeps_healthy_results_without_hysteresis_round(self):
        await self.core._refresh_nodes()
        original = self.core._request
        async def request(func, path, *args):
            if '/delay?' in path:
                if '/Hong%20Kong/' in path:
                    await asyncio.sleep(1)
                return {'delay': 10}
            return original(path, *args)
        self.core.config['selection_mode'] = 'fastest'
        with patch('portalproxy.core.asyncio.to_thread', side_effect=request):
            await self.core._probe_nodes(budget=.02)
        self.assertEqual(self.core.selected, 'Tokyo')
        self.assertFalse(self.core.probe_complete)
        self.assertEqual((self.core.probe_tested, self.core.probe_total), (1, 2))
        self.core.fastest.current, self.core.fastest.switched_at = 'Hong Kong', -100
        with patch('portalproxy.core.asyncio.to_thread', side_effect=request):
            await self.core._probe_nodes(budget=.02)
        self.assertEqual(self.core.fastest.current, 'Hong Kong')
        self.assertEqual(self.core.fastest.rounds, 0)

    async def test_cancelled_probe_does_not_publish_completed_subset(self):
        await self.core._refresh_nodes()
        before = [dict(node) for node in self.core.nodes]
        original = self.core._request
        started = asyncio.Event()
        async def request(func, path, *args):
            if '/delay?' in path:
                if '/Hong%20Kong/' in path:
                    started.set()
                    await asyncio.sleep(10)
                return {'delay': 0}
            return original(path, *args)
        with patch('portalproxy.core.asyncio.to_thread', side_effect=request):
            task = asyncio.create_task(self.core._probe_nodes(budget=5))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(self.core.nodes, before)
        self.assertEqual(self.core.probe_tested, 0)

    async def test_linked_proxy_refuses_node_commands(self):
        core = ExistingProxy({'existing_proxy_port': 7890})
        proxy = ProxyServer(dict(listen_host='127.0.0.1', listen_port=10081, allowed_clients=['127.0.0.1']), core)
        control = RuntimeControl(proxy, core, emit=lambda *args, **kwargs: None)
        control.accept('{"command":"prepare","request_id":7}')
        await control.task
        self.assertFalse(control.snapshot()['node_management'])
        self.assertEqual(control.last_command_id, 7)
        self.assertIn('delegated', control.command_error)
        self.assertEqual(core.active, 0)

    async def test_busy_control_keeps_status_responsive(self):
        gate = asyncio.Event()
        self.core.prepare = AsyncMock(side_effect=lambda *args: gate.wait())
        async def prepare(*args): await gate.wait()
        self.core.prepare = prepare
        proxy = ProxyServer(dict(listen_host='127.0.0.1', listen_port=10081, allowed_clients=['127.0.0.1']), self.core)
        records = []
        control = RuntimeControl(proxy, self.core, emit=lambda value, **kwargs: records.append(json.loads(value)))
        control.accept('{"command":"prepare","request_id":1}')
        pending = control.task
        control.accept('{"command":"test","request_id":2}')
        self.assertTrue(control.snapshot()['busy'])
        self.assertIn('already', control.command_error)
        control.accept('{"command":"status"}')
        gate.set()
        await pending
        self.assertEqual(control.last_command_id, 1)
        self.assertFalse(control.snapshot()['busy'])
