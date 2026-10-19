"""Offline macOS discovery regressions; no host routes or proxy settings change."""
import subprocess
import unittest
from unittest.mock import patch

from portalproxy import existing_proxy, setup


def interface(name='en0', address='192.168.5.12', *, status='active', flags='8863', extra=''):
    return (f'{name}: flags={flags}<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n'
            f'\tinet {address} netmask 0xffffff00 broadcast 192.168.5.255\n'
            f'{extra}\tstatus: {status}\n')


def proxy_output(global_fields='', scoped_fields=''):
    return ('<dictionary> {\n' + global_fields + '\n'
            '  __SCOPED__ : <dictionary> {\n'
            '    en1 : <dictionary> {\n' + scoped_fields + '\n'
            '    }\n  }\n}\n')


def proxy_fields(port=7897, host='127.0.0.1', enabled=1):
    return f'  HTTPEnable : {enabled}\n  HTTPProxy : {host}\n  HTTPPort : {port}'


class MacOSLANDiscoveryTests(unittest.TestCase):
    def test_active_default_interface_keeps_exact_private_subnet(self):
        data = interface() + interface('en1', '10.0.0.2', status='inactive')
        result = setup.parse_interfaces(data, 'en0')
        self.assertEqual(result['host'], '192.168.5.12')
        self.assertEqual(result['subnet'], '192.168.5.0/24')
        self.assertEqual(len(result['clients']), 253)
        self.assertNotIn(result['host'], result['clients'])

    def test_inactive_or_down_default_never_falls_back_to_other_interface(self):
        for change in ({'status': 'inactive'}, {'flags': '8862'}, {'flags': '8823'},
                       {'flags': '8873'}, {'flags': '886b'}):
            data = interface(**change) + interface('en1', '10.0.0.2')
            with self.subTest(change=change), self.assertRaises(ValueError):
                setup.parse_interfaces(data, 'en0')

    def test_missing_unknown_or_vpn_default_is_not_guessed(self):
        data = interface() + interface('en1', '10.0.0.2')
        for preferred in ('', 'en9', 'utun3', 'bridge0'):
            with self.subTest(preferred=preferred), self.assertRaises(ValueError):
                setup.parse_interfaces(data, preferred)

    def test_multiple_addresses_or_duplicate_default_blocks_are_ambiguous(self):
        for data in (interface(extra='\tinet 192.168.5.13 netmask 0xffffff00\n'),
                     interface() + interface()):
            with self.subTest(data=data), self.assertRaises(ValueError):
                setup.parse_interfaces(data, 'en0')

    def test_network_broadcast_and_unconfirmed_link_are_rejected(self):
        for data in (interface(address='192.168.5.0'), interface(address='192.168.5.255'),
                     interface().replace('\tstatus: active\n', ''),
                     interface().replace('0xffffff00', '0xffffffffff'),
                     'x' * 262145):
            with self.subTest(data=data[:100]), self.assertRaises(ValueError):
                setup.parse_interfaces(data, 'en0')

    def test_fixed_read_only_commands_require_successful_route_lookup(self):
        results = [subprocess.CompletedProcess([], 0, stdout='interface: en0\n'),
                   subprocess.CompletedProcess([], 0, stdout=interface())]
        with patch.object(setup.sys, 'platform', 'darwin'), \
             patch.object(setup.subprocess, 'run', side_effect=results) as run:
            self.assertEqual(setup.discover_lan()['host'], '192.168.5.12')
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [['/sbin/route', '-n', 'get', 'default'], ['/sbin/ifconfig', '-a']])
        self.assertTrue(all(call.kwargs.get('check') is True for call in run.call_args_list))
        self.assertTrue(all(call.kwargs.get('shell') is False for call in run.call_args_list))

    def test_unreadable_route_and_invalid_command_encoding_fail_closed(self):
        for error in (subprocess.CalledProcessError(1, '/sbin/route'), UnicodeError(),
                      subprocess.TimeoutExpired('/sbin/route', 2)):
            with patch.object(setup.sys, 'platform', 'darwin'), \
                 patch.object(setup.subprocess, 'run', side_effect=error), \
                 self.subTest(error=type(error)), self.assertRaisesRegex(ValueError, 'Could not read local network'):
                setup.discover_lan()


class MacOSProxyDiscoveryTests(unittest.TestCase):
    def discover(self, output):
        result = subprocess.CompletedProcess([], 0, stdout=output)
        with patch.object(existing_proxy.sys, 'platform', 'darwin'), \
             patch.object(existing_proxy.subprocess, 'run', return_value=result) as run:
            value = existing_proxy.detect_system_proxy()
        self.assertEqual(run.call_args.args[0], ['/usr/sbin/scutil', '--proxy'])
        self.assertTrue(run.call_args.kwargs.get('check'))
        self.assertIs(run.call_args.kwargs.get('shell'), False)
        return value

    def test_scoped_proxy_never_overrides_global_proxy(self):
        output = proxy_output(proxy_fields(), proxy_fields(7898))
        self.assertEqual(self.discover(output), {'host': '127.0.0.1', 'port': 7897})

    def test_scoped_proxy_does_not_enable_globally_disabled_or_missing_proxy(self):
        for fields in ('', proxy_fields(enabled=0), proxy_fields(host='proxy.example')):
            with self.subTest(fields=fields):
                self.assertIsNone(self.discover(proxy_output(fields, proxy_fields(7898))))

    def test_nested_arrays_do_not_hide_valid_global_fields(self):
        output = ('<dictionary> {\n  ExceptionsList : <array> {\n'
                  '    0 : *.local\n    1 : 169.254/16\n  }\n' + proxy_fields() + '\n}\n')
        self.assertEqual(self.discover(output), {'host': '127.0.0.1', 'port': 7897})

    def test_enabled_global_pac_or_auto_discovery_is_ambiguous(self):
        for key in ('ProxyAutoConfigEnable', 'ProxyAutoDiscoveryEnable'):
            for enabled in ('1', 'unknown'):
                with self.subTest(key=key, enabled=enabled):
                    self.assertIsNone(self.discover(proxy_output(proxy_fields() + f'\n  {key} : {enabled}')))
            self.assertEqual(self.discover(proxy_output(proxy_fields() + f'\n  {key} : 0')),
                             {'host': '127.0.0.1', 'port': 7897})

    def test_nested_pac_does_not_change_global_manual_proxy(self):
        scoped = proxy_fields(7898) + '\n  ProxyAutoConfigEnable : 1\n  ProxyAutoDiscoveryEnable : 1'
        self.assertEqual(self.discover(proxy_output(proxy_fields(), scoped)),
                         {'host': '127.0.0.1', 'port': 7897})

    def test_duplicate_malformed_and_oversized_output_is_not_guessed(self):
        valid = proxy_output(proxy_fields())
        for output in (proxy_output(proxy_fields() + '\n  HTTPPort : 7898'),
                       valid[:-2], valid + 'HTTPPort : 7898\n', 'x' * 262145,
                       proxy_output(proxy_fields(port='+7897'))):
            with self.subTest(output=output[:100]):
                self.assertIsNone(self.discover(output))

    def test_failed_or_unreadable_command_does_not_report_a_proxy(self):
        for error in (subprocess.CalledProcessError(1, '/usr/sbin/scutil'), UnicodeError(),
                      subprocess.TimeoutExpired('/usr/sbin/scutil', 2)):
            with patch.object(existing_proxy.sys, 'platform', 'darwin'), \
                 patch.object(existing_proxy.subprocess, 'run', side_effect=error), \
                 self.subTest(error=type(error)):
                self.assertIsNone(existing_proxy.detect_system_proxy())


if __name__ == '__main__':
    unittest.main()
