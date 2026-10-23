"""Accelerator sources remain explicit and isolated from subscription modes."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from portalproxy import __main__ as backend, config, product_modes


def lan_config(**changes):
    result = dict(product_mode='accelerator', listen_host='192.168.50.2',
                  allowed_clients=['192.168.50.3'], engine_mode='external')
    result.update(changes)
    return result


class AcceleratorListenerPolicyTests(unittest.TestCase):
    def test_mode_is_distinct_and_does_not_replace_legacy_choices(self):
        self.assertEqual(product_modes.MODES, ('game', 'mixed', 'clash', 'accelerator'))
        self.assertEqual(product_modes.LABELS['accelerator'], 'Accelerator mode')
        self.assertEqual(product_modes.infer_mode({}), 'game')
        self.assertEqual(product_modes.infer_mode(dict(product_mode='accelerator')), 'accelerator')
        self.assertEqual(product_modes.infer_mode(dict(listen_host='127.0.0.1', allowed_clients=['127.0.0.1'])), 'clash')

    def test_accelerator_accepts_only_other_explicit_lan_devices(self):
        host = '192.168.50.2'
        clients = ['192.168.50.3', host, '192.168.50.3', '192.168.50.4']
        self.assertEqual(product_modes.listener_policy('accelerator', host, clients),
                         (host, ['192.168.50.3', '192.168.50.4']))
        self.assertEqual(clients, ['192.168.50.3', host, '192.168.50.3', '192.168.50.4'])
        for bind, allowed in [('0.0.0.0', ['192.168.50.3']), ('127.0.0.1', ['127.0.0.1']),
                              (host, [host]), (host, []), (host, ['0.0.0.0/0']),
                              (host, ['8.8.8.8']), (host, ['::1'])]:
            with self.subTest(bind=bind, allowed=allowed), self.assertRaises(ValueError):
                product_modes.listener_policy('accelerator', bind, allowed)

    def test_effective_config_keeps_separate_editable_lan_preferences(self):
        raw = lan_config(host_relay='steam', allowed_clients=['192.168.50.3', '192.168.50.2'])
        before = copy.deepcopy(raw)
        effective = product_modes.effective_config(raw)
        self.assertEqual(raw, before)
        self.assertEqual(effective['allowed_clients'], ['192.168.50.3'])
        self.assertEqual(effective['product_lan_preferences']['allowed_clients'], before['allowed_clients'])
        product_modes.validate_effective(effective)
        with self.assertRaises(ValueError):
            product_modes.validate_effective(dict(effective, allowed_clients=before['allowed_clients']))


class AcceleratorSourceConfigTests(unittest.TestCase):
    def test_host_and_xianniu_are_accepted_without_core_or_subscription(self):
        for source in (dict(host_relay='steam'),
                       dict(existing_proxy_provider='xianniu', existing_proxy_port=56777)):
            raw = lan_config(**source)
            original = copy.deepcopy(raw)
            with self.subTest(source=source), patch('portalproxy.windows_accelerator.detect_xianniu') as detector:
                checked = config.validate(raw, '/unused/config.json')
            self.assertEqual(checked['product_mode'], 'accelerator')
            self.assertNotIn('core_path', checked)
            self.assertEqual(raw, original)
            detector.assert_not_called()

    def test_no_source_or_unmarked_system_proxy_never_defaults_to_a_host_or_mihomo(self):
        for source in ({}, dict(existing_proxy_port=7897),
                       dict(existing_proxy_provider='system', existing_proxy_port=7897),
                       dict(existing_proxy_provider='xianniu'), dict(host_relay=None),
                       dict(subscription_url='https://example.com/sub', core_path=sys.executable)):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'explicit Steam host relay'):
                config.validate(lan_config(**source), '/unused/config.json')

    def test_accelerator_rejects_subscription_profile_embedded_and_host_proxy_conflicts(self):
        sources = [dict(host_relay='steam'), dict(existing_proxy_port=56777, existing_proxy_provider='xianniu')]
        for source in sources:
            for field, value in [('subscription_url', 'https://example.com/sub'),
                                 ('subscription_file', '/unused.yaml'), ('profile_file', '/unused.yaml'),
                                 ('engine_mode', 'embedded')]:
                raw = lan_config(**source)
                raw[field] = value
                with self.subTest(source=source, field=field), self.assertRaises(ValueError):
                    config.validate(raw, '/unused/config.json')
        with self.assertRaises(ValueError):
            config.validate(lan_config(host_relay='steam', existing_proxy_port=56777,
                                      existing_proxy_provider='xianniu'), '/unused/config.json')

    def test_explicit_old_game_steam_config_migrates_on_copy_with_identical_acl(self):
        raw = lan_config(product_mode='game', host_relay='steam',
                         extra={'keep': ['preference']})
        before = copy.deepcopy(raw)
        checked = config.validate(raw, '/unused/config.json')
        self.assertEqual(checked['product_mode'], 'accelerator')
        self.assertEqual(checked['listen_host'], raw['listen_host'])
        self.assertEqual(checked['allowed_clients'], raw['allowed_clients'])
        self.assertEqual(checked['extra'], raw['extra'])
        self.assertEqual(raw, before)

    def test_pre_mode_steam_cli_loopback_stays_legacy_and_does_not_gain_lan_access(self):
        raw = dict(host_relay='steam', listen_host='127.0.0.1', allowed_clients=['127.0.0.1'])
        checked = config.validate(raw, '/unused/config.json')
        self.assertNotIn('product_mode', checked)
        self.assertEqual(checked['allowed_clients'], ['127.0.0.1'])
        self.assertEqual(checked['listen_host'], '127.0.0.1')

    def test_xianniu_old_game_and_pre_mode_configs_remain_compatible(self):
        for mode in ('game', None):
            raw = lan_config(existing_proxy_port=56777, existing_proxy_provider='xianniu')
            if mode is None:
                raw.pop('product_mode')
            else:
                raw['product_mode'] = mode
            checked = config.validate(raw, '/unused/config.json')
            self.assertEqual(checked.get('product_mode'), mode)
        for mode in ('mixed', 'clash'):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'legacy game mode only'):
                config.validate(lan_config(product_mode=mode, existing_proxy_port=56777,
                                          existing_proxy_provider='xianniu'), '/unused/config.json')

    def test_host_source_never_implicitly_converts_mixed_clash_or_null_modes(self):
        for mode in ('mixed', 'clash', None):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'accelerator mode'):
                config.validate(lan_config(product_mode=mode, host_relay='steam'), '/unused/config.json')

    def test_system_proxy_stays_game_only(self):
        raw = lan_config(product_mode='game', existing_proxy_port=7897)
        self.assertEqual(config.validate(raw, '/unused/config.json')['product_mode'], 'game')
        for mode in ('mixed', 'clash', 'accelerator'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                config.validate(dict(raw, product_mode=mode), '/unused/config.json')

    def test_subscription_modes_keep_their_existing_source_and_listener_behavior(self):
        raw = dict(subscription_url='https://example.com/sub', core_path=sys.executable,
                   listen_host='192.168.50.2', allowed_clients=['192.168.50.3', '192.168.50.2'])
        expected = {'game': ('192.168.50.2', ['192.168.50.3']),
                    'mixed': ('192.168.50.2', ['192.168.50.3', '192.168.50.2']),
                    'clash': ('127.0.0.1', ['127.0.0.1'])}
        for mode, pair in expected.items():
            with self.subTest(mode=mode):
                checked = config.validate(product_modes.effective_config(dict(raw, product_mode=mode)), '/unused/config.json')
                self.assertEqual((checked['listen_host'], checked['allowed_clients']), pair)
                self.assertEqual(checked['subscription_url'], raw['subscription_url'])
                self.assertNotIn('host_relay', checked)
        legacy = config.validate(dict(raw, allowed_clients=['192.168.50.2']), '/unused/config.json')
        self.assertNotIn('product_mode', legacy)
        self.assertEqual(legacy['allowed_clients'], ['192.168.50.2'])

    def test_accelerator_check_is_offline_and_cross_platform(self):
        raw = lan_config(host_relay='steam')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps(raw), encoding='utf-8')
            with patch('portalproxy.config.sys.platform', 'linux'), patch('portalproxy.windows_accelerator.detect_xianniu') as detector, patch.object(backend, 'serve') as serve, patch.object(backend.sys, 'stdout', io.StringIO()):
                self.assertEqual(backend.main(['--config', str(path), '--check']), 0)
            serve.assert_not_called()
            detector.assert_not_called()


if __name__ == '__main__':
    unittest.main()
