"""Offline profile-policy restoration regressions using the real controller logic."""
import copy
import tempfile
import unittest
from urllib.parse import unquote

from portalproxy.config import DEFAULTS
from portalproxy.core import CoreManager


class ProfilePolicyRestoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.config = dict(DEFAULTS, data_dir=self.temporary.name,
                           profile_file='offline-profile.json', node_policies={
                               'Group A': dict(mode='manual', name='Alpha'),
                               'Group B': dict(mode='manual', name='Beta'),
                           })
        self.core = CoreManager(self.config)
        self.addAsyncCleanup(self.core.close)
        self.inventory = {
            'Group A': dict(type='Selector', all=['Alpha', 'Beta'], now='Alpha'),
            'Group B': dict(type='Selector', all=['Alpha', 'Beta'], now='Beta'),
            'Alpha': dict(type='Http', alive=True),
            'Beta': dict(type='Http', alive=True),
        }
        self.writes = []
        self.core._request = self.request

    def request(self, path, method='GET', payload=None, timeout=2):
        if path == '/proxies':
            return {'proxies': copy.deepcopy(self.inventory)}
        if path == '/providers/proxies':
            return {'providers': {}}
        if '/delay?' in path:
            return {'delay': 10}
        name = unquote(path.removeprefix('/proxies/'))
        if method == 'PUT':
            self.inventory[name]['now'] = payload['name']
            self.writes.append((name, payload['name']))
            return {}
        return copy.deepcopy(self.inventory[name])

    async def test_testing_active_group_after_restore_keeps_its_manual_choice(self):
        await self.core._refresh_nodes('Group A')
        await self.core.nodes.restore()
        # Testing the already-active group does not reload its saved policy.
        await self.core._refresh_nodes('Group A')
        await self.core._probe_nodes()
        self.assertEqual(self.inventory['Group A']['now'], 'Alpha')
        self.assertEqual(self.config['preferred_node'], 'Alpha')
        self.assertEqual(self.core.nodes.policies['Group A'], dict(mode='manual', name='Alpha'))
        self.assertNotIn(('Group A', 'Beta'), self.writes)

    async def test_disjoint_group_members_do_not_break_the_next_probe(self):
        self.inventory['Group A']['all'] = ['Alpha']
        self.inventory['Group B']['all'] = ['Beta']
        await self.core._refresh_nodes('Group A')
        await self.core.nodes.restore()
        await self.core._probe_nodes()
        self.assertEqual(self.core.selected, 'Alpha')
        self.assertEqual(self.core.selection_group, 'Group A')

    async def test_restore_keeps_active_group_fastest_state_and_settings(self):
        self.core.nodes.policies['Group A'] = dict(mode='latency')
        await self.core._refresh_nodes('Group A')
        self.config.update(selection_mode='fastest', preferred_node='')
        fastest = self.core.fastest
        fastest.current, fastest.challenger, fastest.rounds = 'Alpha', 'Beta', 1
        fastest.switched_at = 123
        await self.core.nodes.restore()
        self.assertIs(self.core.fastest, fastest)
        self.assertEqual((self.core.selection_group, self.core.profile_mode), ('Group A', 'fastest'))
        self.assertEqual((self.config['selection_mode'], self.config['preferred_node']), ('fastest', ''))
        self.assertEqual((fastest.current, fastest.challenger, fastest.rounds, fastest.switched_at),
                         ('Alpha', 'Beta', 1, 123))

    async def test_failed_later_group_restore_still_restores_active_scope(self):
        self.core.nodes.policies['Group B'] = dict(mode='manual', name='Missing')
        await self.core._refresh_nodes('Group A')
        fastest = self.core.fastest
        with self.assertRaisesRegex(ValueError, 'Saved node is missing'):
            await self.core.nodes.restore()
        self.assertEqual((self.core.selection_group, self.core.profile_mode), ('Group A', 'fixed'))
        self.assertEqual(self.config['preferred_node'], 'Alpha')
        self.assertIs(self.core.fastest, fastest)
        await self.core._probe_nodes()
        self.assertEqual(self.inventory['Group A']['now'], 'Alpha')
