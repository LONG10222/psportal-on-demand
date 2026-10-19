#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Isolated aapt2 dump parser/contract tests; no SDK, APK or VPN required."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
from apk_manifest import EXPECTED_PERMISSIONS, audit_manifest, parse_xmltree


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
