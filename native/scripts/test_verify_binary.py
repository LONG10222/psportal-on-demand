# SPDX-License-Identifier: GPL-3.0-only
"""Keep executable smoke checks aligned with listener and outbound-core states."""
import copy
import unittest

import verify_binary


def cold_listener_status():
    return {
        'event': 'status', 'running': True, 'state': 'listening',
        'core_state': 'stopped', 'nodes': [], 'active': 0,
        'selected_node': '', 'error': '',
        'stats': {
            'running': True, 'external_requests': 0, 'waking': 0,
            'forwarding': 0,
        },
    }


class ColdListenerStatusTests(unittest.TestCase):
    def test_active_listener_with_sleeping_core_is_accepted(self):
        verify_binary.assert_cold_listener_statuses([cold_listener_status(), cold_listener_status()])

    def test_empty_output_is_rejected(self):
        with self.assertRaises(AssertionError):
            verify_binary.assert_cold_listener_statuses([])

    def test_incorrect_or_missing_runtime_fields_are_rejected(self):
        for key, value in (
            ('event', 'ready'), ('running', False), ('running', 1),
            ('state', 'stopped'), ('state', 'waking'), ('state', 'forwarding'),
            ('core_state', 'starting'), ('core_state', 'running'),
            ('nodes', [{'name': 'unexpected'}]), ('active', 1),
            ('selected_node', 'unexpected'), ('error', 'unexpected failure'),
        ):
            with self.subTest(key=key, value=value):
                changed = cold_listener_status()
                changed[key] = value
                with self.assertRaises(AssertionError):
                    verify_binary.assert_cold_listener_statuses([changed])
        for key in cold_listener_status():
            with self.subTest(missing=key):
                changed = cold_listener_status()
                del changed[key]
                with self.assertRaises(AssertionError):
                    verify_binary.assert_cold_listener_statuses([changed])

    def test_listener_stats_prove_no_outbound_activity(self):
        for key in cold_listener_status()['stats']:
            for missing in (False, True):
                with self.subTest(key=key, missing=missing):
                    changed = cold_listener_status()
                    if missing:
                        del changed['stats'][key]
                    else:
                        changed['stats'][key] = False if key == 'running' else 1
                    with self.assertRaises(AssertionError):
                        verify_binary.assert_cold_listener_statuses([changed])

    def test_every_snapshot_must_remain_cold(self):
        first = cold_listener_status()
        later = copy.deepcopy(first)
        later['core_state'] = 'running'
        with self.assertRaises(AssertionError):
            verify_binary.assert_cold_listener_statuses([first, later, first])


if __name__ == '__main__':
    unittest.main()
