"""Offline integrity/scope checks for the reviewed CPython notice supplement."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import retain_cpython_notices as notices


SOURCE = Path(__file__).resolve().parents[1] / 'notices' / 'cpython-3.13.16'
RUNTIME = dict(python='3.13.16', implementation='CPython', **notices.WINDOWS_COMPONENTS)
MAC_SOURCE = SOURCE.with_name('cpython-3.13.15-macos')
MAC_RUNTIME = dict(python='3.13.15', implementation='CPython', **notices.MACOS_COMPONENTS)


class CPythonNoticeTests(unittest.TestCase):
    def test_openssl3_version_uses_linked_release_string_not_legacy_tuple_fix(self):
        self.assertEqual(notices.openssl_release('OpenSSL 3.5.9 16 Sep 2026'), [3, 5, 9])
        self.assertEqual(notices.openssl_release('OpenSSL 3.0.21 9 Jun 2026'), [3, 0, 21])
        for value in ('LibreSSL 3.5.9', 'OpenSSL 3.5.9-dev 16 Sep 2026',
                      'OpenSSL 3.5.9 16 Sep 2026 extra', 'OpenSSL 3.5'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                notices.openssl_release(value)

    def test_reviewed_notice_set_has_complete_exact_hashes(self):
        self.assertEqual(len(notices.verified_supplement_files(SOURCE)), 25)

    def test_mac_notice_set_has_complete_exact_hashes_and_platform_binding(self):
        self.assertEqual(len(notices.verified_supplement_files(MAC_SOURCE, 'darwin')), 23)
        with self.assertRaises(ValueError):
            notices.verified_supplement_files(MAC_SOURCE, 'win32')
        with self.assertRaises(ValueError):
            notices.verified_supplement_files(SOURCE, 'darwin')
        self.assertEqual(notices.supplement_name('darwin'), 'cpython-3.13.15-macos')
        self.assertEqual(notices.supplement_name('win32'), 'cpython-3.13.16')

    def mac_fixture(self, root):
        paths = {}
        for name in notices.MACOS_INSTALLED_NOTICES:
            paths[name] = root / (name + '.txt')
            paths[name].write_text('Owned exact installed notice fixture: ' + name)
        return paths, {name: notices.sha256(path) for name, path in paths.items()}

    def test_mac_retention_checks_versions_and_preserves_installed_notices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths, hashes = self.mac_fixture(root)
            target = root / 'notices'
            with patch.dict(notices.MACOS_INSTALLED_NOTICES, hashes):
                report = notices.retain_supplement(MAC_SOURCE, target, MAC_SOURCE / 'CPython-LICENSE',
                    target_platform='darwin', runtime=MAC_RUNTIME, installed_notices=paths)
            self.assertFalse(report['distribution_approved'])
            self.assertFalse(report['platform_dependency_coverage_verified'])
            for source in notices.verified_supplement_files(MAC_SOURCE, 'darwin'):
                self.assertEqual((target / source.name).read_bytes(), source.read_bytes())
            for name, source in paths.items():
                record = report['installed_component_notices'][name]
                self.assertEqual((target / record['retained']).read_bytes(), source.read_bytes())
                self.assertEqual(record['sha256'], hashes[name])

    def test_mac_rejects_unreviewed_versions_missing_or_changed_installed_notices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths, hashes = self.mac_fixture(root)
            target = root / 'notices'
            with patch.dict(notices.MACOS_INSTALLED_NOTICES, hashes):
                for name in notices.MACOS_COMPONENTS:
                    with self.subTest(component=name), self.assertRaises(ValueError):
                        notices.retain_supplement(MAC_SOURCE, target, MAC_SOURCE / 'CPython-LICENSE',
                            target_platform='darwin', runtime=dict(MAC_RUNTIME, **{name: 'unreviewed'}),
                            installed_notices=paths)
                    self.assertFalse(target.exists())
                for changed_paths in ({'Tcl': paths['Tcl']}, dict(paths, Tk=paths['Tcl'])):
                    with self.assertRaises(ValueError):
                        notices.retain_supplement(MAC_SOURCE, target, MAC_SOURCE / 'CPython-LICENSE',
                            target_platform='darwin', runtime=MAC_RUNTIME, installed_notices=changed_paths)
                    self.assertFalse(target.exists())

    def test_linked_liblzma_version_query_is_read_only_and_fail_closed(self):
        with patch('_lzma.__file__', '/installed/stdlib/_lzma.so', create=True), patch('ctypes.CDLL') as load:
            load.return_value.lzma_version_string.return_value = b'5.2.3'
            self.assertEqual(notices.installed_liblzma_version(), '5.2.3')
            self.assertEqual(load.return_value.lzma_version_string.argtypes, ())
            for value in (None, b'5.2.3-modified', b'unreviewed'):
                load.return_value.lzma_version_string.return_value = value
                with self.assertRaises(ValueError): notices.installed_liblzma_version()

    def test_wrong_python_or_platform_never_creates_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'notices'
            for platform, runtime in (('linux', RUNTIME), ('darwin', dict(RUNTIME, python='3.13.17')),
                                       ('win32', dict(RUNTIME, implementation='OtherPython'))):
                with self.subTest(platform=platform, runtime=runtime), self.assertRaises(ValueError):
                    notices.retain_supplement(SOURCE, target, SOURCE / 'CPython-LICENSE',
                        target_platform=platform, runtime=runtime)
                self.assertFalse(target.exists())

    def test_manifest_corruption_and_missing_notices_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / 'source'
            shutil.copytree(SOURCE, copy)
            manifest_path = copy / 'manifest.json'
            original = json.loads(manifest_path.read_text())
            for change in ('path', 'hash', 'missing', 'duplicate', 'source', 'tag', 'source_path'):
                manifest = json.loads(json.dumps(original))
                if change == 'path':
                    manifest['files'][0]['file'] = '../escape'
                elif change == 'hash':
                    manifest['files'][0]['sha256'] = '0' * 64
                elif change == 'missing':
                    manifest['files'].pop()
                elif change == 'duplicate':
                    manifest['files'][1] = manifest['files'][0]
                elif change == 'tag':
                    manifest['files'][0]['source_url'] = manifest['files'][0]['source_url'].replace('v3.13.16', 'v3.13.15')
                elif change == 'source_path':
                    manifest['files'][0]['source_url'] += '/../LICENSE'
                else:
                    manifest['files'][0]['source_url'] = 'https://unreviewed.invalid/LICENSE'
                manifest_path.write_text(json.dumps(manifest))
                with self.subTest(change=change), self.assertRaises(ValueError):
                    notices.verified_supplement_files(copy)

    def test_windows_requires_matching_components_and_installed_license(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'notices'
            for runtime in (dict(RUNTIME, expat='expat_unreviewed'), RUNTIME):
                with self.subTest(runtime=runtime), self.assertRaises(ValueError):
                    notices.retain_supplement(SOURCE, target, SOURCE / 'CPython-LICENSE',
                        target_platform='win32', runtime=runtime)
                self.assertFalse(target.exists())

    def test_windows_runtime_hash_is_bound_to_installer_and_classified_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime_dll = root / 'VCRUNTIME140.dll'
            runtime_dll.write_bytes(b'owned test fixture')
            extra_dll = root / 'VCRUNTIME140_1.dll'
            extra_dll.write_bytes(b'additional owned test fixture')
            license_file = SOURCE / 'CPython-LICENSE'
            with patch.object(notices, 'WINDOWS_INSTALLED_LICENSE_SHA256', notices.sha256(license_file)), \
                 patch.object(notices, 'WINDOWS_VCRUNTIME_SHA256', notices.sha256(runtime_dll)), \
                 patch.object(notices, 'WINDOWS_VCRUNTIME_1_SHA256', notices.sha256(extra_dll)):
                report = notices.retain_supplement(SOURCE, root / 'notices', license_file,
                    target_platform='win32', runtime=RUNTIME,
                    vcruntime_origin=runtime_dll, bundled_vcruntime=runtime_dll)
                self.assertIn('Microsoft Distributable Code', report['microsoft_runtime']['classification'])
                self.assertIn('Microsoft Distributable Code', report['microsoft_runtime_additional']['classification'])
                self.assertFalse(report['distribution_approved'])
                extra_dll.unlink()
                with self.assertRaises(ValueError):
                    notices.retain_supplement(SOURCE, root / 'missing-extra', license_file,
                        target_platform='win32', runtime=RUNTIME,
                        vcruntime_origin=runtime_dll, bundled_vcruntime=runtime_dll)
                self.assertFalse((root / 'missing-extra').exists())
                extra_dll.write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    notices.retain_supplement(SOURCE, root / 'changed-extra', license_file,
                        target_platform='win32', runtime=RUNTIME,
                        vcruntime_origin=runtime_dll, bundled_vcruntime=runtime_dll)
                self.assertFalse((root / 'changed-extra').exists())
                runtime_dll.write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    notices.retain_supplement(SOURCE, root / 'changed', license_file,
                        target_platform='win32', runtime=RUNTIME,
                        vcruntime_origin=runtime_dll, bundled_vcruntime=runtime_dll)
                self.assertFalse((root / 'changed').exists())
