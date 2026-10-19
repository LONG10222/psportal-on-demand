import asyncio
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from portalproxy import config, profiles
from portalproxy.core import CoreManager
from portalproxy.proxy import ProxyServer
from test_core import port


class ProfileImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.source = self.folder / 'full.yaml'
        self.runtime = self.folder / 'runtime'
        self.runtime.mkdir()
        self.data = {'proxies': [{'name': 'Custom Tokyo', 'type': 'http', 'server': 'node.example', 'port': 443,
                                 'password': 'fixture-secret', 'tls': True}],
                     'proxy-groups': [{'name': 'Custom', 'type': 'select', 'proxies': ['Custom Tokyo', 'DIRECT']}],
                     'rules': ['DOMAIN-SUFFIX,example.org,Custom', 'MATCH,DIRECT'],
                     'dns': {'enable': False, 'nameserver': ['https://dns.example/dns-query']},
                     'profile': {'store-selected': True}, 'port': 7890}
        self.source.write_text(json.dumps(self.data))
        self.cfg = {'profile_file': str(self.source), 'backend_port': 10182, 'api_port': 10190}

    def test_complete_profile_preserves_groups_rules_node_options_and_source(self):
        before = self.source.read_bytes()
        out = profiles.render_profile(self.cfg, 'runtime-secret', self.runtime)
        for key in ('proxies', 'proxy-groups', 'rules', 'dns', 'profile'):
            self.assertEqual(out[key], self.data[key])
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(out['port'], 10182)
        self.assertEqual(out['external-controller'], '127.0.0.1:10190')
        self.assertEqual(out['bind-address'], '127.0.0.1')
        self.assertEqual(out['secret'], 'runtime-secret')
        self.assertFalse(out['allow-lan'])
        self.assertEqual(profiles.inspect_profile(self.source)['kind'], 'profile')

    def test_yaml_anchors_and_merge_are_supported_without_dropping_values(self):
        self.source.write_text('defaults: &d {type: http, port: 443}\nproxies:\n - <<: *d\n   name: node\n   server: node.example\nrules: [MATCH,DIRECT]\n')
        data = profiles.read_profile(self.source)
        self.assertEqual(data['proxies'][0]['port'], 443)
        self.assertEqual(data['proxies'][0]['name'], 'node')

    def test_json_surrogate_pairs_roundtrip_without_changing_the_source(self):
        self.data['proxies'][0]['name'] = '🇯🇵 Tokyo'
        raw = json.dumps(self.data)
        self.assertIn('\\ud83c', raw)
        self.source.write_text(raw)
        self.assertEqual(profiles.read_profile(self.source)['proxies'][0]['name'], '🇯🇵 Tokyo')
        self.assertEqual(self.source.read_text(), raw)

    def test_malformed_duplicate_recursive_and_unsafe_tags_are_rejected_without_secret_echo(self):
        for raw in ('proxies: []\nproxies: []', 'x: &x [*x]', '!!python/object/apply:os.system [echo secret-marker]',
                    'password: [secret-marker', 'proxies: {}', 'rules: {}', 'date: 2026-10-18'):
            with self.subTest(raw=raw):
                self.source.write_text(raw)
                with self.assertRaises(profiles.ProfileError) as caught:
                    profiles.read_profile(self.source)
                self.assertNotIn('secret-marker', str(caught.exception))

    def test_system_features_are_rejected_instead_of_silently_removed(self):
        for changes in ({'tun': {'enable': True}}, {'dns': {'enable': True, 'listen': ':53'}}, {'iptables': {'enable': True}},
                        {'listeners': [{'type': 'mixed', 'port': 9000}]}):
            self.source.write_text(json.dumps(dict(self.data, **changes)))
            with self.assertRaises(profiles.ProfileError):
                profiles.render_profile(self.cfg, 'secret', self.runtime)

    def test_host_overlay_accepts_common_profile_without_changing_source_or_resolver(self):
        self.data.update(tun={'enable': True}, dns={'enable': True, 'listen': ':53', 'nameserver': ['1.1.1.1']},
                         listeners=[{'type': 'mixed', 'port': 7890}], authentication=['fixture:secret'])
        self.source.write_text(json.dumps(self.data))
        out = profiles.render_profile(dict(self.cfg, host_profile_overlay=True), 'secret', self.runtime)
        self.assertFalse(out['tun']['enable'])
        self.assertTrue(out['dns']['enable'])
        self.assertEqual(out['dns']['nameserver'], ['1.1.1.1'])
        self.assertEqual(out['dns']['listen'], '')
        self.assertNotIn('listeners', out)
        self.assertNotIn('authentication', out)
        self.assertEqual(out['rules'], self.data['rules'])
        self.assertEqual(json.loads(self.source.read_text()), self.data)

    def test_provider_file_is_snapshotted_and_relative_path_keeps_semantics(self):
        provider = self.folder / 'nodes.yaml'
        provider.write_text('proxies: []\n')
        self.data['proxy-providers'] = {'nodes': {'type': 'file', 'path': 'nodes.yaml'}}
        self.source.write_text(json.dumps(self.data))
        out = profiles.render_profile(self.cfg, 'secret', self.runtime)
        relative = out['proxy-providers']['nodes']['path']
        self.assertEqual((self.runtime / relative).read_bytes(), provider.read_bytes())
        self.assertEqual(self.source.read_text(), json.dumps(self.data))

    def test_provider_cannot_traverse_outside_selected_profile_directory(self):
        self.data['proxy-providers'] = {'nodes': {'type': 'file', 'path': '../outside.yaml'}}
        self.source.write_text(json.dumps(self.data))
        with self.assertRaisesRegex(profiles.ProfileError, 'inside'):
            profiles.render_profile(self.cfg, 'secret', self.runtime)

    def test_host_config_accepts_full_profile_without_subscription_and_rejects_embedded(self):
        core = self.folder / 'core'; core.write_text('not executed')
        cfg = dict(config.DEFAULTS, core_path=str(core), profile_file=str(self.source),
                   listen_host='127.0.0.1', allowed_clients=['127.0.0.1'])
        self.assertEqual(config.validate(cfg, self.folder / 'host.json')['profile_file'], str(self.source))
        with self.assertRaisesRegex(ValueError, 'external Mihomo'):
            config.validate(dict(cfg, engine_mode='embedded'), self.folder / 'host.json')

    def test_complete_profile_ignores_stale_provider_fields(self):
        core = self.folder / 'core'; core.write_text('not executed')
        cfg = dict(core_path=str(core), profile_file=str(self.source), selection_mode='fixed',
                   preferred_node='', subscription_file='/missing/old-provider.yaml',
                   listen_host='127.0.0.1', allowed_clients=['127.0.0.1'])
        result = config.validate(cfg, self.folder / 'host.json')
        self.assertEqual(result['selection_mode'], 'auto')
        self.assertNotIn('subscription_file', result)
        self.source.write_text('proxy-providers: {nodes: {type: http, url: https://example.org/nodes}}')
        self.assertEqual(profiles.inspect_profile(self.source)['kind'], 'profile')

    def test_connection_exports_contain_no_subscription_or_node_credentials(self):
        values = dict(listen_host='192.168.1.2', listen_port=10081, allowed_clients=['192.168.1.30'],
                      subscription_url='https://secret.example/token', password='do-not-export')
        for data in (profiles.connection_details(values), profiles.client_config(values)):
            serialized = json.dumps(data)
            self.assertNotIn('secret.example', serialized)
            self.assertNotIn('do-not-export', serialized)
        self.assertEqual(profiles.client_config(values)['proxies'][0]['server'], '192.168.1.2')
        with self.assertRaises(ValueError):
            profiles.connection_details(dict(values, listen_host='0.0.0.0'))


@unittest.skipUnless(os.environ.get('MIHOMO_BINARY'), 'Set MIHOMO_BINARY for complete-profile transport')
class CompleteProfileTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_complete_profile_uses_its_own_group_and_rule_then_releases_core(self):
        calls = []
        async def upstream(reader, writer):
            try:
                header = await reader.readuntil(b'\r\n\r\n')
                calls.append(header)
                if header.startswith(b'CONNECT '):
                    writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                    await writer.drain()
                    if b':80 ' in header:
                        calls.append(await reader.readuntil(b'\r\n\r\n'))
                        writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 12\r\nConnection: close\r\n\r\nprofile-core')
                        await writer.drain()
                    else:
                        while chunk := await reader.read(65536):
                            writer.write(chunk); await writer.drain()
                else:
                    writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 12\r\nConnection: close\r\n\r\nprofile-core')
                    await writer.drain()
            finally:
                writer.close(); await writer.wait_closed()
        server = await asyncio.start_server(upstream, '127.0.0.1', 0)
        node_port = server.sockets[0].getsockname()[1]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                source = folder / 'profile.yaml'
                original = {'proxies': [{'name': 'CUSTOM-HTTP', 'type': 'http', 'server': '127.0.0.1', 'port': node_port}],
                            'proxy-groups': [{'name': 'ORIGINAL-GROUP', 'type': 'select', 'proxies': ['CUSTOM-HTTP']}],
                            'rules': ['MATCH,ORIGINAL-GROUP'], 'tun': {'enable': True},
                            'dns': {'enable': True, 'listen': ':53', 'nameserver': ['1.1.1.1']}}
                source.write_text(json.dumps(original))
                cfg = dict(config.DEFAULTS, profile_file=str(source), host_profile_overlay=True, core_path=os.environ['MIHOMO_BINARY'],
                           listen_host='127.0.0.1', listen_port=0, allowed_clients=['127.0.0.1'],
                           backend_port=port(), api_port=port(), data_dir=str(folder / 'runtime'), idle_seconds=1)
                core = CoreManager(cfg); proxy = ProxyServer(cfg, core)
                try:
                    await proxy.start(); core.start_monitor()
                    self.assertIsNone(core.process)
                    reader, writer = await asyncio.open_connection(*proxy.bound_addresses[0][:2])
                    writer.write(b'GET http://1.1.1.1/profile HTTP/1.1\r\nHost: 1.1.1.1\r\n\r\n'); await writer.drain()
                    self.assertIn(b'profile-core', await asyncio.wait_for(reader.read(), 15))
                    writer.close(); await writer.wait_closed()
                    generated = json.loads((core.runtime / 'config.json').read_text())
                    self.assertEqual(generated['proxy-groups'], original['proxy-groups'])
                    self.assertEqual(generated['rules'], original['rules'])
                    self.assertFalse(generated['tun']['enable'])
                    self.assertEqual(generated['dns']['listen'], '')
                    self.assertEqual(json.loads(source.read_text()), original)
                    self.assertTrue(calls)
                    for _ in range(40):
                        if core.process is None:
                            break
                        await asyncio.sleep(.1)
                    self.assertIsNone(core.process)
                finally:
                    await proxy.close(); await core.close()
        finally:
            server.close(); await server.wait_closed()
