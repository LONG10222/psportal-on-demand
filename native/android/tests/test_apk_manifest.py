#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Isolated aapt2 dump parser/contract tests; no SDK, APK or VPN required."""
import pathlib
import re
import runpy
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
from apk_manifest import EXPECTED_PERMISSIONS, NAMESPACES, audit_manifest, parse_xmltree


def fixture():
    permissions = ''.join('    E: uses-permission (line=2)\n'
                          '      A: android:name(0x01010003)="' + name + '" (Raw: "' + name + '")\n'
                          for name in sorted(EXPECTED_PERMISSIONS))
    return '''N: android=http://schemas.android.com/apk/res/android
  E: manifest (line=1)
    A: package="org.psportal.host" (Raw: "org.psportal.host")
    A: android:versionCode(0x0101021b)=(type 0x10)0x4
    A: android:versionName(0x0101021c)="0.4.0-dev" (Raw: "0.4.0-dev")
''' + permissions + '''    E: application (line=12)
      A: android:allowBackup(0x01010280)=(type 0x12)0x0
      A: android:label(0x01010001)=@0x7f010000
      E: activity (line=14)
        A: android:name(0x01010003)="org.psportal.host.MainActivity"
        A: android:exported(0x01010010)=(type 0x12)0xffffffff
      E: service (line=20)
        A: android:name(0x01010003)=".ProxyService" (Raw: ".ProxyService")
        A: android:exported(0x01010010)=(type 0x12)0x0
        A: android:stopWithTask(0x01010036)=(type 0x12)0x0
        A: android:foregroundServiceType(0x01010599)=(type 0x11)0x410
      E: service (line=25)
        A: android:name(0x01010003)="org.psportal.host.PhoneVpnService"
        A: android:permission(0x01010006)="android.permission.BIND_VPN_SERVICE"
        A: android:exported(0x01010010)=(type 0x12)0x0
        A: android:stopWithTask(0x01010036)=(type 0x12)0x0
        A: android:foregroundServiceType(0x01010599)=(type 0x11)0x400
        E: intent-filter (line=31)
          E: action (line=32)
            A: android:name(0x01010003)="android.net.VpnService"
        E: meta-data (line=34)
          A: android:name(0x01010003)="android.net.VpnService.SUPPORTS_ALWAYS_ON"
          A: android:value(0x01010024)=(type 0x12)0x0
'''


def aapt2_fixture():
    # AOSP aapt2 Debug::XmlPrinter: each namespace increases indentation; child
    # elements are two levels below their parent, attributes one level below.
    lines = ['N: android=' + NAMESPACES['android'] + ' (line=2)',
             '  N: tools=' + NAMESPACES['tools'] + ' (line=3)']
    for line in fixture().splitlines()[1:]:
        indent = len(line) - len(line.lstrip())
        token = line.lstrip()
        if token.startswith('A: '):
            indent = indent * 2 - 2
            token = token.replace('A: android:', 'A: ' + NAMESPACES['android'] + ':')
            token = re.sub(r'\(type 0x10\)(0x[0-9a-f]+)', lambda m: str(int(m[1], 16)), token)
            token = re.sub(r'\(type 0x11\)(0x[0-9a-f]+)', lambda m: f'0x{int(m[1], 16):08x}', token)
            token = token.replace('(type 0x12)0xffffffff', 'true').replace('(type 0x12)0x0', 'false')
        else:
            indent *= 2
        lines.append(' ' * indent + token)
    return '\n'.join(lines) + '\n'


class CompiledManifestTests(unittest.TestCase):
    def reject(self, text):
        with self.assertRaises((AssertionError, ValueError)):
            audit_manifest(text)

    def test_exact_v4_service_contract_accepts_compiled_values(self):
        report = audit_manifest(fixture())
        self.assertEqual(set(report['services']), {'org.psportal.host.ProxyService', 'org.psportal.host.PhoneVpnService'})
        self.assertFalse(report['always_on_vpn'])
        self.assertEqual(report['version_code'], 4)
        self.assertEqual(report['version_name'], '0.4.0-dev')
        self.assertEqual(report['services']['org.psportal.host.PhoneVpnService']['binding_permission'], 'android.permission.BIND_VPN_SERVICE')

    def test_aapt2_namespace_lines_uri_attributes_and_pretty_values(self):
        text = aapt2_fixture()
        self.assertEqual(audit_manifest(text), audit_manifest(fixture()))
        # A tools annotation is not an Android service permission or export flag.
        text = text.replace('            E: service (line=20)\n',
                            '            E: service (line=20)\n'
                            '              A: http://schemas.android.com/tools:ignore="ForegroundServicePermission"\n')
        self.assertEqual(audit_manifest(text), audit_manifest(fixture()))

    def test_element_local_namespace_keeps_siblings_and_scope(self):
        lines = aapt2_fixture().splitlines()
        # Move tools from the root to the first service, as aapt2 prints an
        # element-local declaration. The following service remains its sibling.
        lines = [lines[0]] + [line[2:] for line in lines[2:]]
        start = lines.index('          E: service (line=20)')
        end = lines.index('          E: service (line=25)')
        lines[start:end] = ['          N: tools=' + NAMESPACES['tools'] + ' (line=20)'] + ['  ' + line for line in lines[start:end]]
        text = '\n'.join(lines) + '\n'
        self.assertEqual(audit_manifest(text), audit_manifest(fixture()))
        self.reject(text.replace('          E: service (line=25)\n',
                                 '          E: service (line=25)\n'
                                 '            A: tools:ignore="ForegroundServicePermission"\n'))

    def test_namespace_spoofs_duplicates_and_unknowns_fail(self):
        text = aapt2_fixture()
        for old, new in [('N: tools=', 'N: other='),
                         (NAMESPACES['tools'], 'https://schemas.android.com/tools'),
                         (NAMESPACES['android'], NAMESPACES['android'] + '/spoof'),
                         ('N: tools=' + NAMESPACES['tools'], 'N: tools=' + NAMESPACES['android']),
                         (' (line=3)', ' (line=three)'),
                         (' (line=3)', ' (line=3) trailing')]:
            with self.subTest(old=old, new=new):
                self.reject(text.replace(old, new))
        for alias in NAMESPACES:
            self.reject(text.replace('    E: manifest',
                                     '    N: ' + alias + '=' + NAMESPACES[alias] + '\n      E: manifest'))
        self.reject(text + 'N: unknown=http://example.invalid\n')
        self.reject(text.replace('A: ' + NAMESPACES['android'] + ':', 'A: unknown:'))
        self.reject(text.replace('A: ' + NAMESPACES['android'] + ':', 'A: https://untrusted.invalid:'))
        self.reject(text.replace('      A: package=', '      A: android:versionCode=4\n      A: package='))

    def test_aapt2_values_remain_strict_and_references_opaque(self):
        text = aapt2_fixture()
        for old, new in [('versionCode(0x0101021b)=4', 'versionCode(0x0101021b)="4"'),
                         ('versionCode(0x0101021b)=4', 'versionCode(0x0101021b)=true'),
                         ('exported(0x01010010)=false', 'exported(0x01010010)=0'),
                         ('exported(0x01010010)=false', 'exported(0x01010010)=true (Raw: "false")'),
                         ('foregroundServiceType(0x01010599)=0x00000400', 'foregroundServiceType(0x01010599)=@0x7f010001'),
                         ('foregroundServiceType(0x01010599)=0x00000400', 'foregroundServiceType(0x01010599)="0x00000400"')]:
            with self.subTest(old=old, new=new):
                self.reject(text.replace(old, new))

    def test_compiled_dump_is_saved_before_a_failed_audit(self):
        # Exercise the CLI failure path using a structural APK fixture and
        # mocked SDK output; this is not an Android binary/runtime validation.
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            apk, report = root / 'test.apk', root / 'reports/audit.json'
            elf = bytearray(120)
            elf[:6] = b'\x7fELF\x02\x01'
            struct.pack_into('<H', elf, 18, 183)
            struct.pack_into('<Q', elf, 32, 64)
            struct.pack_into('<HH', elf, 54, 56, 1)
            struct.pack_into('<IIQQQQQQ', elf, 64, 1, 0, 0, 0, 0, 0, 0, 16384)
            with zipfile.ZipFile(apk, 'w') as archive:
                for name in ('assets/licenses/ENGINE-NOTICES.txt', 'assets/licenses/GPL-3.0.txt',
                             'assets/licenses/PROJECT-MIT.txt', 'classes.dex', 'AndroidManifest.xml'):
                    archive.writestr(name, b'fixture')
                archive.writestr('lib/arm64-v8a/libgojni.so', elf)
            badging = "package: name='org.psportal.host'\nminSdkVersion:'26'\ntargetSdkVersion:'36'\nlaunchable-activity: name='org.psportal.host.MainActivity'\n"
            dump = aapt2_fixture().replace('N: android=', 'N: unknown=')
            script = pathlib.Path(__file__).resolve().parents[1] / 'tools/audit-apk.py'
            argv = [str(script), str(apk), '--sdk', str(root / 'sdk'), '--report', str(report), '--abis', 'arm64-v8a']
            with mock.patch.object(sys, 'argv', argv), \
                    mock.patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')), \
                    mock.patch('subprocess.check_output', side_effect=[badging, dump]):
                with self.assertRaisesRegex(AssertionError, 'Unexpected compiled namespace'):
                    runpy.run_path(str(script), run_name='__main__')
            self.assertEqual((report.parent / 'compiled-manifest.txt').read_text(), dump)
            self.assertFalse(report.exists())

    def test_exact_compiled_version_is_required(self):
        for old, new in [('(type 0x10)0x4', '(type 0x10)0x3'),
                         ('(type 0x10)0x4', '"4"'),
                         ('"0.4.0-dev"', '"0.3.0-dev"'),
                         ('"0.4.0-dev"', '@0x7f010001')]:
            self.reject(fixture().replace(old, new))
        self.reject(fixture().replace('    A: android:versionCode(0x0101021b)=(type 0x10)0x4\n', ''))
        self.reject(fixture().replace('    A: android:versionName', '    A: android:versionCodeMajor=(type 0x10)0x1\n    A: android:versionName'))

    def test_required_binding_permission_is_service_specific(self):
        permission = '        A: android:permission(0x01010006)="android.permission.BIND_VPN_SERVICE"\n'
        self.reject(fixture().replace(permission, ''))
        self.reject(fixture().replace(permission, '').replace('        A: android:name(0x01010003)=".ProxyService"', permission + '        A: android:name(0x01010003)=".ProxyService"'))
        self.reject(fixture().replace('"android.permission.BIND_VPN_SERVICE"', '"android.permission.INTERNET"'))
        self.reject(fixture().replace('      A: android:allowBackup', '      A: android:permission="android.permission.BIND_VPN_SERVICE"\n      A: android:allowBackup'))

    def test_service_export_is_never_inferred_from_activity(self):
        self.reject(fixture().replace('        A: android:exported(0x01010010)=(type 0x12)0x0', '        A: android:exported(0x01010010)=(type 0x12)0xffffffff'))
        self.reject(fixture().replace('        A: android:exported(0x01010010)=(type 0x12)0x0\n', ''))

    def test_wrong_foreground_types_and_resource_indirection_fail(self):
        for old, new in [('0x11)0x410', '0x11)0x10'), ('0x11)0x400', '0x11)0x410'),
                         ('(type 0x11)0x400', '@0x7f010001')]:
            self.reject(fixture().replace(old, new))

    def test_no_extra_service_or_receiver_even_without_boot_permission(self):
        self.reject(fixture() + '      E: receiver (line=40)\n        A: android:name=".HiddenReceiver"\n')
        self.reject(fixture() + '      E: service (line=40)\n        A: android:name=".OtherService"\n')

    def test_no_boot_permission_or_bind_permission_as_app_permission(self):
        for permission in ['android.permission.RECEIVE_BOOT_COMPLETED', 'android.permission.BIND_VPN_SERVICE']:
            self.reject(fixture().replace('    E: application', '    E: uses-permission\n      A: android:name="' + permission + '"\n    E: application'))

    def test_always_on_and_extra_vpn_intents_fail(self):
        self.reject(fixture().replace('android:value(0x01010024)=(type 0x12)0x0', 'android:value(0x01010024)=(type 0x12)0xffffffff (Raw: "false")'))
        self.reject(fixture().replace('"android.net.VpnService"', '"other.action"'))
        self.reject(fixture().replace('        E: meta-data', '          E: action\n            A: android:name="other.action"\n        E: meta-data'))

    def test_separate_processes_and_conditional_permissions_fail(self):
        self.reject(fixture().replace('      E: service (line=20)', '      A: android:process=":isolated"\n      E: service (line=20)'))
        self.reject(fixture().replace('    E: uses-permission (line=2)', '    E: uses-permission-sdk-23 (line=2)', 1))

    def test_missing_namespace_duplicate_attributes_and_malformed_dump_fail(self):
        self.reject(fixture().replace('http://schemas.android.com/apk/res/android', 'https://untrusted.invalid'))
        self.reject(fixture().replace('    A: package=', '    A: package="org.psportal.host"\n    A: package='))
        self.reject('Error: failed to read manifest')
        self.reject(fixture().replace('(type 0x12)0x0', '(type 0x12)0x1'))
        with self.assertRaises(AssertionError):
            parse_xmltree('N: android=http://schemas.android.com/apk/res/android\nA: package="org.psportal.host"')


if __name__ == '__main__':
    unittest.main()
