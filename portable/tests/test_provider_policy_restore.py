"""Saved provider policies survive restart, probes, and on-demand sleep.

Controller fixtures are offline. Process tests use only the owned loopback
fake core, not real Mihomo, subscriptions, or external proxy endpoints.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from urllib.parse import unquote

from portalproxy.config import DEFAULTS
from portalproxy.core import CoreError, CoreManager
from test_core import port


class ProviderPolicyRestoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.config = dict(DEFAULTS, data_dir=self.temporary.name,
                           node_policies={'PORTAL': dict(mode='manual', name='Alpha')})
        self.core = CoreManager(self.config)
        self.addAsyncCleanup(self.core.close)
        self.inventory = {
            'PORTAL': dict(type='Selector', all=['PORTAL-AUTO', 'Alpha', 'Beta'], now='PORTAL-AUTO'),
            'PORTAL-AUTO': dict(type='Fallback', all=['Alpha', 'Beta'], now='Beta'),
            'Alpha': dict(type='Http', alive=True),
            'Beta': dict(type='Http', alive=True),
        }
        self.delays = {'Alpha': 80, 'Beta': 10}
        self.writes = []
        self.core._request = self.request

    def request(self, path, method='GET', payload=None, timeout=2):
        if path == '/proxies':
            return {'proxies': copy.deepcopy(self.inventory)}
        if path == '/providers/proxies':
            return {'providers': {}}
        name = unquote(path.removeprefix('/proxies/').split('/delay?', 1)[0])
        if '/delay?' in path:
            return {'delay': self.delays.get(name)}
        if method == 'PUT':
            self.inventory[name]['now'] = payload['name']
            self.writes.append(payload['name'])
            return {}
        return copy.deepcopy(self.inventory[name])

    async def test_saved_manual_restores_mode_and_survives_latency_test(self):
        await self.core.nodes.restore()
        self.assertEqual(self.core.status()['selection_mode'], 'fixed')
        self.assertEqual(self.config['preferred_node'], 'Alpha')
        await self.core._probe_nodes()
        self.assertEqual(self.inventory['PORTAL']['now'], 'Alpha')
        self.assertEqual(self.core.selected, 'Alpha')
        self.assertNotIn('PORTAL-AUTO', self.writes)

    async def test_startup_uses_saved_manual_before_any_automatic_selection(self):
        await self.core._select()
        await self.core.nodes.restore()
        self.assertEqual(self.writes, ['Alpha', 'Alpha'])
        self.assertEqual(self.core.status()['selection_mode'], 'fixed')

    async def test_saved_fastest_restores_mode_and_probes_at_startup(self):
        self.core.nodes.policies['PORTAL'] = dict(mode='latency')
        self.config.update(selection_mode='fixed', preferred_node='Alpha')
        await self.core._select()
        await self.core.nodes.restore()
        self.assertEqual(self.core.selection_mode, 'fastest')
        self.assertEqual(self.config['preferred_node'], '')
        self.assertTrue(self.core.probe_complete)
        self.assertEqual(self.core.probe_tested, 2)
        self.assertEqual(self.inventory['PORTAL']['now'], 'Beta')
        self.assertEqual(self.writes, ['Beta'])
        await self.core._probe_nodes()
        self.assertEqual(self.inventory['PORTAL']['now'], 'Beta')

    async def test_fastest_restore_alone_hydrates_following_probe(self):
        self.core.nodes.policies['PORTAL'] = dict(mode='latency')
        await self.core.nodes.restore()
        await self.core._probe_nodes()
        self.assertEqual(self.core.status()['selection_mode'], 'fastest')
        self.assertEqual(self.inventory['PORTAL']['now'], 'Beta')
        self.assertNotIn('PORTAL-AUTO', self.writes)

    async def test_missing_saved_manual_node_never_falls_back(self):
        self.core.nodes.policies['PORTAL']['name'] = 'Missing'
        with self.assertRaisesRegex(CoreError, 'Fixed node is missing'):
            await self.core._select()
        self.assertEqual(self.writes, [])

    async def test_failed_saved_fastest_probes_never_choose_automatic_fallback(self):
        self.core.nodes.policies['PORTAL'] = dict(mode='latency')
        self.delays = {}
        with self.assertRaisesRegex(CoreError, 'No healthy proxy node'):
            await self.core._select()
        self.assertEqual(self.writes, ['REJECT'])
        self.assertEqual(self.core.selection_mode, 'fastest')

    async def test_no_saved_provider_policy_preserves_explicit_launch_settings(self):
        self.core.nodes.policies = {}
        self.config.update(selection_mode='fixed', preferred_node='Beta')
        await self.core._select()
        self.assertEqual(self.inventory['PORTAL']['now'], 'Beta')
        self.assertEqual(self.config['preferred_node'], 'Beta')

    def test_complete_profiles_do_not_hydrate_provider_policy(self):
        self.config.update(profile_file='owned-profile.yaml', selection_mode='auto', preferred_node='')
        self.core.nodes.restore_provider_policy()
        self.assertEqual((self.config['selection_mode'], self.config['preferred_node']), ('auto', ''))


@unittest.skipIf(os.name == 'nt', 'POSIX shebang fixture; offline policy tests also run on Windows')
class ProviderPolicyLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def lifecycle(self, policy, mode, expected):
        with tempfile.TemporaryDirectory() as folder:
            provider = Path(folder) / 'provider.json'
            provider.write_text(json.dumps({'proxies': []}))
            cfg = dict(DEFAULTS, data_dir=str(Path(folder) / 'runtime'),
                       backend_port=port(), api_port=port(), idle_seconds=.1, wakeup_timeout=15,
                       core_path=str(Path(__file__).with_name('fake_core.py').resolve()),
                       subscription_file=str(provider), node_policies={'PORTAL': policy})
            core = CoreManager(cfg)
            original_request = core._request

            def request(path, method='GET', payload=None, timeout=2):
                if '/delay?' in path:
                    # Fixed offline observations only; no URL probe is sent.
                    return {'delay': 10 if '/Tokyo/' in path else 80}
                return original_request(path, method, payload, timeout)

            core._request = request
            try:
                # Load and test both wake the same owner and must retain intent.
                await core.prepare()
                first_pid = core.process.pid
                for action in (core.prepare, core.test_nodes):
                    await action()
                    self.assertEqual(core.status()['selection_mode'], mode)
                    self.assertEqual(core.selected, expected)
                self.assertEqual(core.process.pid, first_pid)

                core.start_monitor()
                for _ in range(100):
                    if core.process is None:
                        break
                    await asyncio.sleep(.02)
                self.assertIsNone(core.process, 'The idle core must stop')
                await core.test_nodes()
                self.assertNotEqual(core.process.pid, first_pid)
                self.assertEqual(core.status()['selection_mode'], mode)
                self.assertEqual(core.selected, expected)

                # Explicit owned-core stop follows the same restore contract.
                async with core.lock:
                    await core._stop()
                await core.prepare()
                self.assertEqual(core.status()['selection_mode'], mode)
                self.assertEqual(core.selected, expected)
            finally:
                await core.close()

    async def test_manual_survives_load_test_idle_wake_and_stop(self):
        await self.lifecycle(dict(mode='manual', name='Hong Kong'), 'fixed', 'Hong Kong')

    async def test_fastest_survives_load_test_idle_wake_and_stop(self):
        await self.lifecycle(dict(mode='latency'), 'fastest', 'Tokyo')
