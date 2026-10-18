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


class CPythonNoticeTests(unittest.TestCase):
    def test_reviewed_notice_set_has_complete_exact_hashes(self):
        self.assertEqual(len(notices.verified_supplement_files(SOURCE)), 25)

    def test_mac_retention_keeps_component_coverage_explicitly_unverified(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'notices'
            report = notices.retain_supplement(SOURCE, target, SOURCE / 'CPython-LICENSE',
                target_platform='darwin', runtime=dict(RUNTIME, openssl=[3, 5, 7]))
            self.assertFalse(report['distribution_approved'])
            self.assertFalse(report['platform_dependency_coverage_verified'])
            self.assertEqual(report['components']['openssl'], [3, 5, 7])
            for source in notices.verified_supplement_files(SOURCE):
                self.assertEqual((target / source.name).read_bytes(), source.read_bytes())

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
            for change in ('path', 'hash', 'missing', 'duplicate', 'source'):
                manifest = json.loads(json.dumps(original))
                if change == 'path':
                    manifest['files'][0]['file'] = '../escape'
                elif change == 'hash':
                    manifest['files'][0]['sha256'] = '0' * 64
                elif change == 'missing':
                    manifest['files'].pop()
                elif change == 'duplicate':
                    manifest['files'][1] = manifest['files'][0]
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
            license_file = SOURCE / 'CPython-LICENSE'
            with patch.object(notices, 'WINDOWS_INSTALLED_LICENSE_SHA256', notices.sha256(license_file)), \
                 patch.object(notices, 'WINDOWS_VCRUNTIME_SHA256', notices.sha256(runtime_dll)):
                report = notices.retain_supplement(SOURCE, root / 'notices', license_file,
                    target_platform='win32', runtime=RUNTIME,
                    vcruntime_origin=runtime_dll, bundled_vcruntime=runtime_dll)
                self.assertIn('Microsoft Distributable Code', report['microsoft_runtime']['classification'])
                self.assertFalse(report['distribution_approved'])
                runtime_dll.write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    notices.retain_supplement(SOURCE, root / 'changed', license_file,
                        target_platform='win32', runtime=RUNTIME,
                        vcruntime_origin=runtime_dll, bundled_vcruntime=runtime_dll)
                self.assertFalse((root / 'changed').exists())
