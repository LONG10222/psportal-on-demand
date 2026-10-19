"""Mixed-protocol desktop regressions; no display, network or real measurements."""
import io
import json
import queue
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from portalproxy.desktop import BackendProcess, DesktopApp
from portalproxy.desktop_view import DesktopView, saved_preference_note
from portalproxy.runtime import PREFIX
from test_desktop_runtime import status


def legacy(**changes):
    value = dict(kind='nodes', id=1, group='Old group', groups=['Old group'], current='Old node',
                 rows=[dict(name='Old node', type='HTTP', delay=42, selected=True)],
                 policies={'Old group': dict(mode='manual', name='Old node')}, message='Node switched.')
    value.update(changes)
    return value


class MixedTelemetryTests(unittest.TestCase):
    def test_both_protocols_are_owned_and_never_raw_diagnostics(self):
        backend = BackendProcess()
        records = [json.dumps(status()), PREFIX + json.dumps(dict(kind='statistics', devices=1,
                   active=3, clients=[])), PREFIX + json.dumps(legacy())]
        child = SimpleNamespace(stdout=io.StringIO('\n'.join(records) + '\n'))
        backend.process = child
        backend._read_output(child, values=dict(listen_host='192.168.50.2', listen_port=10081))
        self.assertEqual(backend.snapshot()['active_connections'], 3)
        self.assertEqual([backend.updates.get_nowait()['kind'] for _ in range(2)], ['statistics', 'nodes'])
        self.assertTrue(backend.events.empty())
        backend.process = None

    def test_previous_child_cannot_queue_legacy_updates(self):
        backend = BackendProcess()
        child = SimpleNamespace(stdout=io.StringIO(PREFIX + json.dumps(legacy()) + '\n'))
        backend.process = object()
        backend._read_output(child, values={})
        self.assertTrue(backend.updates.empty())
        self.assertTrue(backend.events.empty())
        backend.process = None

    def test_exited_child_discards_buffered_legacy_records(self):
        backend = BackendProcess()
        backend.process = SimpleNamespace(poll=lambda: 0)
        backend.runtime = status()
        backend.updates.put(legacy())
        self.assertEqual(backend.poll(), 0)
        self.assertIsNone(backend.process)
        self.assertIsNone(backend.snapshot())
        self.assertTrue(backend.updates.empty())


class UnifiedNodePresentationTests(unittest.TestCase):
    def view(self, runtime=None, protocol='runtime', event=None):
        view = object.__new__(DesktopView)
        view.runtime = runtime
        view._direct_subscription = lambda: True
        view.app = SimpleNamespace(node_state=legacy() if event is None else event, _node_protocol=protocol)
        return view

    def test_saved_manual_preference_is_separate_from_effective_group_node(self):
        snapshot = status(selection_group='Fallback group', selected_node='Healthy node',
                          node_policies={'Fallback group': dict(mode='manual', name='Preferred node')})
        note = saved_preference_note(snapshot, 'en')
        self.assertIn('Saved manual preference: Preferred node', note)
        self.assertIn("original group's health rules still apply", note)
        self.assertEqual(snapshot['selected_node'], 'Healthy node')
        translated = saved_preference_note(snapshot, 'zh')
        self.assertIn('已保存的手动偏好：Preferred node', translated)
        self.assertIn('健康检查规则仍然生效', translated)
        snapshot['selected_node'] = 'Preferred node'
        self.assertEqual(saved_preference_note(snapshot, 'en'), '')
        snapshot['node_policies']['Fallback group'] = dict(mode='latency')
        self.assertEqual(saved_preference_note(snapshot, 'en'), '')

    def test_legacy_only_report_normalizes_into_the_same_node_schema(self):
        result = self.view(None, 'legacy')._node_runtime()
        self.assertEqual(result['selection_group'], 'Old group')
        self.assertEqual(result['selected_node'], 'Old node')
        self.assertEqual(result['selection_mode'], 'fixed')
        self.assertEqual(result['nodes'], [dict(name='Old node', type='HTTP', delay_ms=42, healthy=True)])

    def test_prepare_with_empty_scope_is_not_repopulated_by_old_legacy_nodes(self):
        snapshot = status(last_command_id=2, selection_group='', groups=[], nodes=[])
        for protocol in ('runtime', 'legacy'):
            result = self.view(snapshot, protocol)._node_runtime()
            self.assertEqual(result['nodes'], [])
            self.assertEqual(result['groups'], [])
            self.assertEqual(result['selection_group'], '')

    def test_group_change_and_fastest_are_not_reverted_by_old_legacy_selection(self):
        snapshot = status(last_command_id=3, selection_group='New group', selection_mode='fastest',
                          selected_node='New node', groups=[dict(name='New group')],
                          nodes=[dict(name='New node', type='Shadowsocks', delay_ms=12, healthy=True)])
        result = self.view(snapshot, 'runtime')._node_runtime()
        self.assertEqual(result, snapshot)
        self.assertEqual(snapshot['nodes'][0]['name'], 'New node')

    def test_newer_legacy_reply_fills_only_until_matching_status_arrives(self):
        snapshot = status(last_command_id=0, selection_group='', nodes=[])
        view = self.view(snapshot, 'legacy')
        self.assertEqual(view._node_runtime()['selected_node'], 'Old node')
        snapshot.update(last_command_id=1, selection_group='Old group', selected_node='Verified node',
                        nodes=[dict(name='Verified node', healthy=None, delay_ms=None)])
        self.assertEqual(view._node_runtime()['selected_node'], 'Verified node')

    def test_background_legacy_record_cannot_revive_nodes_for_linked_client(self):
        view = self.view(status(node_management=False), 'legacy')
        view._direct_subscription = lambda: False
        self.assertFalse(view._node_runtime()['node_management'])
        self.assertEqual(view._node_runtime()['nodes'], [])


class CommandInterleavingTests(unittest.TestCase):
    def app(self):
        app = object.__new__(DesktopApp)
        app.closing = app.importing = False
        app.raw, app.vars = {}, {}
        app._node_request = app.command_id = 0
        app._pending_node_request = app.pending_command = None
        app._reported_command = None
        app.node_state = legacy()
        app._node_protocol = 'runtime'
        app.backend = SimpleNamespace(process=object(), stopping_since=None, command=Mock(),
            snapshot=lambda: status(), updates=queue.Queue(), secrets=(), log=Mock())
        app.view = SimpleNamespace(_direct_subscription=lambda: True, refresh=Mock(), node_message='',
            node_table=SimpleNamespace(selection=lambda: ('item',), item=lambda *args: ('New node',)))
        app._save_node_policies = Mock()
        return app

    def test_prepare_protocol_remains_structured_after_legacy_background_report(self):
        app = self.app()
        app.backend.updates.put(legacy(message='Old switch message'))
        app._poll_updates()
        self.assertEqual(app.view.node_message, '')
        app.node_command('select')
        app.backend.command.assert_called_once_with('select', request_id=1,
            selection_mode='fixed', preferred_node='New node')
        app.node_command('select')
        self.assertEqual(app.backend.command.call_count, 1)

    def test_matching_legacy_ack_releases_both_pending_fields_and_saves_once(self):
        app = self.app()
        app._node_protocol = 'legacy'
        app.pending_command = 7
        app._pending_node_request = (app.backend.process, 7)
        app.backend.updates.put(legacy(id=6))
        app._poll_updates()
        self.assertEqual(app.pending_command, 7)
        app._save_node_policies.assert_not_called()
        app.backend.updates.put(legacy(id=7))
        app._poll_updates()
        self.assertIsNone(app.pending_command)
        self.assertIsNone(app._pending_node_request)
        app._save_node_policies.assert_called_once_with(legacy()['policies'])
        app.backend.snapshot = lambda: status(last_command_id=7, node_policies=legacy()['policies'])
        app._poll_runtime()
        self.assertEqual(app._save_node_policies.call_count, 1)

    def test_matching_structured_ack_saves_policy_and_releases_both_fields(self):
        app = self.app()
        app.pending_command = 8
        app._pending_node_request = (app.backend.process, 8)
        app.backend.snapshot = lambda: status(last_command_id=8, node_policies=legacy()['policies'])
        app._poll_runtime()
        self.assertIsNone(app.pending_command)
        self.assertIsNone(app._pending_node_request)
        app._save_node_policies.assert_called_once_with(legacy()['policies'])
