"""Read-only Windows/Linux discovery fixtures; no host network changes needed."""
import copy
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

from portalproxy import setup, existing_proxy


def windows_data():
    return {
        'adapters': [{'index': 8, 'name': '无线网络连接', 'up': True,
                      'hardware': True, 'virtual': False, 'type': 71}],
        'addresses': [{'index': 8, 'address': '192.168.5.12', 'prefix': 28,
                       'preferred': True, 'skip': False}],
        'routes': [{'index': 8, 'destination': '0.0.0.0/0', 'gateway': '192.168.5.1',
                    'metric': 10, 'interface_metric': 25}],
    }


def linux_data():
    return ([{'ifindex': 3, 'ifname': 'enp3s0', 'flags': ['BROADCAST', 'MULTICAST', 'UP', 'LOWER_UP'],
              'operstate': 'UP', 'link_type': 'ether',
              'addr_info': [{'family': 'inet', 'local': '192.168.5.12', 'prefixlen': 28,
                             'scope': 'global', 'preferred_life_time': 7200, 'valid_life_time': 7200}]}],
            [{'dst': 'default', 'gateway': '192.168.5.1', 'dev': 'enp3s0', 'metric': 10, 'flags': []}])


class WindowsLANTests(unittest.TestCase):
    def parse(self, data):
        return setup.parse_windows_interfaces(json.dumps(data))

    def test_localized_name_real_prefix_exact_allowlist(self):
        result = self.parse(windows_data())
        self.assertEqual(result['interface'], '无线网络连接')
        self.assertEqual(result['subnet'], '192.168.5.0/28')
        self.assertEqual(len(result['clients']), 13)
        self.assertNotIn(result['host'], result['clients'])
        self.assertTrue(all(ipaddress.ip_address(host) in ipaddress.ip_network(result['subnet']) for host in result['clients']))

    def test_unique_default_route_uses_route_plus_interface_metric(self):
        data = windows_data()
        data['adapters'].append(dict(data['adapters'][0], index=9, name='Ethernet', type=6))
        data['addresses'].append(dict(data['addresses'][0], index=9, address='10.0.0.2'))
        data['routes'].append(dict(data['routes'][0], index=9, gateway='10.0.0.1', metric=20, interface_metric=10))
        self.assertEqual(self.parse(data)['host'], '10.0.0.2')
        data['routes'][1]['interface_metric'] = 15
        with self.assertRaisesRegex(ValueError, 'safely identify'):
            self.parse(data)

    def test_non_physical_down_unknown_and_virtual_fail_closed(self):
        for change in ({'up': False}, {'hardware': False}, {'virtual': True}, {'type': 131},
                       {'up': 'Up'}, {'type': True}, {'name': 'Ethernet\n'}):
            data = windows_data(); data['adapters'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.parse(data)
        data = windows_data(); data['routes'][0]['index'] = 99
        with self.assertRaises(ValueError): self.parse(data)

    def test_invalid_address_prefix_and_gateway_fail_closed(self):
        for address in ('::1', 'fe80::1%8', '192.168.5.999', '192.168.05.12',
                        '127.0.0.1', '169.254.1.2', '100.64.0.2', '8.8.8.8',
                        '192.168.5.0', '192.168.5.15', '192.168.5.12;whoami', 3232236812):
            data = windows_data(); data['addresses'][0]['address'] = address
            with self.subTest(address=address), self.assertRaises(ValueError): self.parse(data)
        for prefix in (23, 16, 31, 32, -1, 33, '24', True, None):
            data = windows_data(); data['addresses'][0]['prefix'] = prefix
            with self.subTest(prefix=prefix), self.assertRaises(ValueError): self.parse(data)
        for gateway in ('0.0.0.0', '192.168.9.1', '192.168.5.12', '192.168.5.15', '::1', None, 3232236801):
            data = windows_data(); data['routes'][0]['gateway'] = gateway
            with self.subTest(gateway=gateway), self.assertRaises(ValueError): self.parse(data)

    def test_preferred_non_skipped_address_and_known_route_required(self):
        for change in ({'preferred': False}, {'skip': True}, {'preferred': 'Preferred'}, {'index': True}):
            data = windows_data(); data['addresses'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): self.parse(data)
        data = windows_data(); data['addresses'].append(dict(data['addresses'][0], address='192.168.5.13'))
        with self.assertRaises(ValueError): self.parse(data)
        for change in ({'metric': -1}, {'metric': None}, {'interface_metric': '20'}, {'index': True}):
            data = windows_data(); data['routes'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): self.parse(data)
        data = windows_data(); data['routes'] = []
        with self.assertRaises(ValueError): self.parse(data)

    def test_split_vpn_default_is_not_treated_as_physical_default(self):
        data = windows_data(); data['routes'].append({'destination': '0.0.0.0/1', 'index': 99})
        with self.assertRaises(ValueError): self.parse(data)

    def test_static_read_only_powershell_command(self):
        data = windows_data(); data['adapters'][0]['name'] = 'Ethernet;$(Remove-Item x)'
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps(data))
        with patch.object(setup.sys, 'platform', 'win32'), patch.object(setup.subprocess, 'run', return_value=result) as run:
            self.assertEqual(setup.discover_lan()['host'], '192.168.5.12')
        args = run.call_args.args[0]
        self.assertEqual(args[:4], ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command'])
        self.assertIn('Get-NetAdapter -Physical', args[4])
        self.assertIn('Get-NetIPAddress', args[4]); self.assertIn('Get-NetRoute', args[4])
        self.assertNotIn('Remove-Item', args[4]); self.assertNotIn('Set-Net', args[4])
        self.assertFalse(run.call_args.kwargs['shell'])


@unittest.skipIf(os.name == "nt", "POSIX sysfs symlink fixtures; Windows adapter parser tested separately")
class LinuxLANTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.sys = Path(self.temp.name) / 'sys'; self.root = self.sys / 'class/net'
        self.root.mkdir(parents=True)
        self.hardware('enp3s0')

    def hardware(self, name, state='up', virtual=False):
        device = self.sys / 'devices' / ('virtual' if virtual else 'pci0000:00') / name
        entry = device / 'net' / name
        entry.mkdir(parents=True)
        (entry / 'device').symlink_to(device, target_is_directory=True)
        (entry / 'type').write_text('1\n'); (entry / 'operstate').write_text(state + '\n')
        (self.root / name).symlink_to(entry, target_is_directory=True)
        return entry

    def parse(self, addresses, routes):
        return setup.parse_linux_interfaces(json.dumps(addresses), json.dumps(routes), self.root)

    def test_sysfs_verified_interface_actual_small_subnet(self):
        addresses, routes = linux_data()
        self.assertEqual(self.parse(addresses, routes)['subnet'], '192.168.5.0/28')
        addresses[0]['addr_info'].append({'family': 'inet6', 'local': 'fe80::3', 'prefixlen': 64, 'scope': 'link'})
        self.assertEqual(self.parse(addresses, routes)['host'], '192.168.5.12')
        addresses[0]['addr_info'][0].update(local='192.168.5.2', prefixlen=30)
        self.assertEqual(self.parse(addresses, routes)['clients'], ['192.168.5.1'])

    def test_canonical_and_symlinked_sysfs_roots_identify_the_same_hardware(self):
        alias = Path(self.temp.name) / 'sys-alias'
        alias.symlink_to(self.sys, target_is_directory=True)
        addresses, routes = linux_data()
        result = setup.parse_linux_interfaces(json.dumps(addresses), json.dumps(routes), alias / 'class/net')
        self.assertEqual(result, self.parse(addresses, routes))

    def test_down_loopback_bridge_unknown_and_virtual_rejected(self):
        for change in ({'operstate': 'DOWN'}, {'operstate': 'UNKNOWN'}, {'master': 'br0'},
                       {'link_type': 'loopback'}, {'flags': ['UP', 'LOWER_UP', 'POINTOPOINT']},
                       {'flags': ['UP', {}]}, {'flags': None}, {'linkinfo': {'info_kind': 'veth'}}):
            addresses, routes = linux_data(); addresses[0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): self.parse(addresses, routes)
        for name, virtual in (('tun0', True), ('docker0', True), ('unknown0', False)):
            if virtual: self.hardware(name, virtual=True)
            addresses, routes = linux_data(); addresses[0]['ifname'] = name; routes[0]['dev'] = name
            with self.subTest(name=name), self.assertRaises(ValueError): self.parse(addresses, routes)
        (self.root / 'enp3s0' / 'operstate').write_text('down\n')
        with self.assertRaises(ValueError): self.parse(*linux_data())

    def test_default_route_selection_and_ambiguity(self):
        self.hardware('wlan0')
        addresses, routes = linux_data()
        second = copy.deepcopy(addresses[0]); second['ifname'] = 'wlan0'
        second['addr_info'][0]['local'] = '10.0.0.2'; addresses.append(second)
        routes.append(dict(routes[0], dev='wlan0', gateway='10.0.0.1', metric=20))
        self.assertEqual(self.parse(addresses, routes)['interface'], 'enp3s0')
        routes[1]['metric'] = 10
        with self.assertRaises(ValueError): self.parse(addresses, routes)
        routes[1].update(dev='tun0', metric=1)
        with self.assertRaises(ValueError): self.parse(addresses, routes)

    def test_no_route_multipath_split_vpn_and_bad_route_fail_closed(self):
        addresses, routes = linux_data()
        with self.assertRaises(ValueError): self.parse(addresses, [])
        for change in ({'nexthops': [{'dev': 'enp3s0'}]}, {'flags': ['linkdown']}, {'metric': '10'},
                       {'type': 'blackhole'}, {'gateway': '1.1.1.1'}, {'gateway': None},
                       {'dev': '../enp3s0'}, {'dev': 'enp3s0;touch /tmp/bad'}):
            with self.subTest(change=change), self.assertRaises(ValueError): self.parse(addresses, [dict(routes[0], **change)])
        with self.assertRaises(ValueError): self.parse(addresses, routes + [{'dst': '128.0.0.0/1', 'dev': 'tun0'}])

    def test_multiple_addresses_need_verified_preferred_source(self):
        addresses, routes = linux_data()
        addresses[0]['addr_info'].append(dict(addresses[0]['addr_info'][0], local='192.168.5.13'))
        with self.assertRaises(ValueError): self.parse(addresses, routes)
        routes[0]['prefsrc'] = '192.168.5.13'
        self.assertEqual(self.parse(addresses, routes)['host'], '192.168.5.13')
        routes[0]['prefsrc'] = '127.0.0.1'
        with self.assertRaises(ValueError): self.parse(addresses, routes)

    def test_malformed_ipv4_prefix_and_lifetime(self):
        for change in ({'local': 'fe80::1'}, {'local': '192.168.5.999'}, {'prefixlen': None},
                       {'prefixlen': '24'}, {'prefixlen': 16}, {'local': '100.64.1.2'},
                       {'tentative': True}, {'deprecated': True}, {'preferred_life_time': 0}):
            addresses, routes = linux_data(); addresses[0]['addr_info'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): self.parse(addresses, routes)

    def test_discovery_only_uses_fixed_ip_json_commands(self):
        addresses, routes = linux_data()
        rules = [{'priority': 0, 'src': 'all', 'table': 'local'},
                 {'priority': 32766, 'src': 'all', 'table': 'main'},
                 {'priority': 32767, 'src': 'all', 'table': 'default'}]
        outputs = [subprocess.CompletedProcess([], 0, stdout=json.dumps(value)) for value in (addresses, routes, rules)]
        parser = setup.parse_linux_interfaces
        with patch.object(setup.sys, 'platform', 'linux'), patch.object(setup.subprocess, 'run', side_effect=outputs) as run, \
             patch.object(setup, 'parse_linux_interfaces', side_effect=lambda a, b, **kw: parser(a, b, self.root, **kw)):
            self.assertEqual(setup.discover_lan()['host'], '192.168.5.12')
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [['ip', '-j', '-4', 'address', 'show'], ['ip', '-j', '-4', 'route', 'show', 'table', 'main'],
                          ['ip', '-j', '-4', 'rule', 'show']])
        self.assertTrue(all(call.kwargs['shell'] is False for call in run.call_args_list))

    def test_policy_routed_vpn_and_unknown_rules_fail_closed(self):
        rules = [{'priority': 0, 'src': 'all', 'table': 'local'},
                 {'priority': 32766, 'src': 'all', 'table': 'main'},
                 {'priority': 32767, 'src': 'all', 'table': 'default'}]
        setup._linux_main_routing(json.dumps(rules))
        for extra in ({'priority': 1000, 'src': 'all', 'table': 51820},
                      {'priority': 32766, 'src': 'all', 'table': 'main'},
                      {'priority': True, 'src': 'all', 'table': 'main'}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                setup._linux_main_routing(json.dumps(rules + [extra]))
        for change in ({'table': 51820}, {'suppress_prefixlength': 0}, {'src': '192.168.5.0/24'}, {'fwmark': '0xca6c'}):
            modified = copy.deepcopy(rules); modified[1].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): setup._linux_main_routing(json.dumps(modified))
        with self.assertRaises(ValueError): setup._linux_main_routing('[]')


class BoundedDiscoveryTests(unittest.TestCase):
    def test_bad_json_is_bounded_and_generic(self):
        for value in ('', 'x' * 262145, '{"adapters":[],"adapters":[]}', '[[[' * 1000,
                      '{"a":NaN}', '[1]', '{"routes": "not an array"}', json.dumps({'x': 'x'*4097}),
                      json.dumps({'x': [[[[[[[[[[[[[0]]]]]]]]]]]]]})):
            with self.subTest(value=value[:60]), self.assertRaises(ValueError): setup.parse_windows_interfaces(value)

    def test_missing_command_failed_command_and_bad_encoding_are_actionable(self):
        for platform in ('linux', 'win32'):
            for error in (FileNotFoundError(), subprocess.TimeoutExpired('read', 5),
                          subprocess.CalledProcessError(1, 'read'), UnicodeError()):
                with patch.object(setup.sys, 'platform', platform), patch.object(setup.subprocess, 'run', side_effect=error), \
                     self.subTest(platform=platform, error=type(error)), self.assertRaisesRegex(ValueError, 'Could not read local network'):
                    setup.discover_lan()

    def test_macos_command_path_is_preserved(self):
        results = [subprocess.CompletedProcess([], 0, stdout='interface: en0'),
                   subprocess.CompletedProcess([], 0, stdout='en0: flags=8863<UP,BROADCAST,RUNNING> mtu 1500\n'
                       '    inet 192.168.5.12 netmask 0xfffffff0\n    status: active\n')]
        with patch.object(setup.sys, 'platform', 'darwin'), patch.object(setup.subprocess, 'run', side_effect=results) as run:
            self.assertEqual(setup.discover_lan()['host'], '192.168.5.12')
        self.assertEqual([call.args[0] for call in run.call_args_list], [['/sbin/route', '-n', 'get', 'default'], ['/sbin/ifconfig', '-a']])


class ProxyDiscoveryTests(unittest.TestCase):
    def test_http_literal_loopback_only_without_credentials_or_shell_syntax(self):
        for value in ('127.0.0.1:7897', 'localhost:1024', 'http://localhost:65535/', 'HTTP://LOCALHOST:7897'):
            with self.subTest(value=value): self.assertEqual(existing_proxy._local_http_proxy(value)['host'], '127.0.0.1')
        for value in ('http://user:pass@localhost:7897', 'http://localhost:7897@remote.test', 'https://localhost:7897',
                      'socks5://localhost:7897', '127.1:7897', '[::1]:7897', 'localhost.evil:7897', '127.0.0.2:7897',
                      '127.0.0.1:80', 'localhost:65536', 'localhost:+7897', 'localhost:７８９７',
                      'localhost:7897;whoami', '$(whoami):7897', 'localhost:7897\n', 'localhost:7897/path',
                      'localhost:7897?url=secret', None):
            with self.subTest(value=value): self.assertIsNone(existing_proxy._local_http_proxy(value))

    def test_windows_registry_only_manual_hkcu_and_read_access(self):
        opened = []
        class Key:
            def __enter__(self): return self
            def __exit__(self, *args): pass
        values = {'ProxyEnable': (1, 4), 'ProxyServer': ('http=localhost:7897;https=remote.example:443;socks=localhost:7898', 1)}
        def query(key, name):
            if name not in values: raise FileNotFoundError()
            return values[name]
        fake = types.SimpleNamespace(HKEY_CURRENT_USER='HKCU', KEY_READ=0x20019, REG_DWORD=4, REG_SZ=1,
                                     OpenKey=lambda *args: (opened.append(args) or Key()), QueryValueEx=query)
        with patch.dict('sys.modules', {'winreg': fake}), patch.object(existing_proxy.sys, 'platform', 'win32'):
            self.assertEqual(existing_proxy.detect_system_proxy(), {'host': '127.0.0.1', 'port': 7897})
            self.assertEqual(opened[-1][0], 'HKCU'); self.assertEqual(opened[-1][-1], fake.KEY_READ)
            for server in ('http=user:password@localhost:7897', 'socks=localhost:7897', 'http=localhost:7897;http=localhost:7898',
                           'localhost:7897;Start-Process evil', 'http=localhost:7897;bad=command'):
                values['ProxyServer'] = (server, 1)
                with self.subTest(server=server): self.assertIsNone(existing_proxy.detect_system_proxy())
            values['ProxyServer'] = ('localhost:7897', 1); values['AutoConfigURL'] = ('https://example.test/secret.pac', 1)
            self.assertIsNone(existing_proxy.detect_system_proxy())
            del values['AutoConfigURL']; values['ProxyEnable'] = (0, 4)
            self.assertIsNone(existing_proxy.detect_system_proxy())

    def test_environment_is_explicit_and_conflicts_credentials_cgi_reject(self):
        cases = [({'http_proxy': 'http://localhost:7897'}, 7897),
                 ({'HTTP_PROXY': '127.0.0.1:7898'}, 7898),
                 ({'http_proxy': 'localhost:7897', 'HTTP_PROXY': '127.0.0.1:7897'}, 7897),
                 ({'http_proxy': 'localhost:7897', 'HTTP_PROXY': 'localhost:7898'}, None),
                 ({'http_proxy': 'http://name:password@localhost:7897'}, None),
                 ({'HTTP_PROXY': 'localhost:7897', 'REQUEST_METHOD': 'GET'}, None)]
        for env, expected in cases:
            # A Linux environment is case-sensitive even when this fixture runs
            # on Windows, whose real os.environ folds these two keys together.
            with patch.object(existing_proxy.os, 'environ', dict(env)), patch.object(existing_proxy.sys, 'platform', 'linux'), \
                 patch.object(existing_proxy.subprocess, 'run') as run, self.subTest(env=env):
                info = existing_proxy.detect_system_proxy()
                self.assertEqual(info['port'] if info else None, expected); run.assert_not_called()

    def test_gnome_only_manual_uncredentialed_http_fixed_queries(self):
        for values, expected in [(["'manual'", 'false', "'localhost'", '7897'], 7897),
                                 (["'auto'"], None), (["'none'"], None), (["'manual'", 'true'], None),
                                 (["'manual'", 'false', "'remote.test'"], None),
                                 (["'manual'", 'false', "'localhost'", '7897;whoami'], None),
                                 (["'manual'", 'false', "'localhost'", '8'*513], None)]:
            results = [subprocess.CompletedProcess([], 0, stdout=value + '\n') for value in values]
            with patch.dict(os.environ, {}, clear=True), patch.object(existing_proxy.sys, 'platform', 'linux'), \
                 patch.object(existing_proxy.subprocess, 'run', side_effect=results) as run, self.subTest(values=values):
                info = existing_proxy.detect_system_proxy()
                self.assertEqual(info['port'] if info else None, expected)
                self.assertTrue(all(call.args[0][:2] == ['gsettings', 'get'] and call.kwargs['shell'] is False for call in run.call_args_list))

    def test_missing_proxy_command_returns_none(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(existing_proxy.sys, 'platform', 'linux'), \
             patch.object(existing_proxy.subprocess, 'run', side_effect=FileNotFoundError()):
            self.assertIsNone(existing_proxy.detect_system_proxy())


class AccountingPathTests(unittest.TestCase):
    def test_standard_paths_only(self):
        name = 'io.github.clash-verge-rev.clash-verge-rev/profiles.yaml'
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / 'home'
            roaming = Path(folder) / 'Roaming'
            data = Path(folder) / 'data'
            with patch.object(Path, 'home', return_value=home):
                for platform, env, expected in [
                    ('darwin', {}, home / 'Library/Application Support' / name),
                    ('win32', {'APPDATA': str(roaming), 'LOCALAPPDATA': str(home / 'wrong')}, roaming / name),
                    ('win32', {}, None), ('win32', {'APPDATA': 'relative/path'}, None),
                    ('linux', {}, home / '.local/share' / name),
                    ('linux', {'XDG_DATA_HOME': str(data)}, data / name),
                    ('linux', {'XDG_DATA_HOME': 'relative'}, home / '.local/share' / name),
                    ('freebsd', {}, None)]:
                    with patch.dict(os.environ, env, clear=True), patch.object(existing_proxy.sys, 'platform', platform), self.subTest(platform=platform, env=env):
                        self.assertEqual(existing_proxy.clash_accounting_path(), expected)

    def test_active_accounting_only_no_controller_or_cache_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'io.github.clash-verge-rev.clash-verge-rev/profiles.yaml'
            path.parent.mkdir()
            raw = json.dumps({'current': 'active', 'items': [
                {'uid': 'other', 'url': 'https://secret/other', 'extra': {'total': 9999}},
                {'uid': 'active', 'name': 'Fixture', 'url': 'https://secret/token', 'password': 'password',
                 'extra': {'upload': 10, 'download': 20, 'total': 100, 'expire': 1900000000, 'token': 'secret'}}]})
            path.write_text(raw)
            for platform, env in [('win32', {'APPDATA': folder}), ('linux', {'XDG_DATA_HOME': folder})]:
                with patch.dict(os.environ, env, clear=True), patch.object(existing_proxy.sys, 'platform', platform), \
                     patch.object(existing_proxy.subprocess, 'run') as run:
                    info = existing_proxy.read_clash_accounting()
                    self.assertEqual(info['total'], 100); self.assertNotIn('secret', str(info)); self.assertNotIn('password', str(info))
                    self.assertEqual(path.read_text(), raw); run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
