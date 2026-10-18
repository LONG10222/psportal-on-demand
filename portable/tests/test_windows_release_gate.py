"""Offline fail-closed tests for the specifically reviewed Windows release gate."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile
from yaml_packaging_fixtures import add_yaml_evidence
from scripts.verify_windows_release import verify_archive, verify_inventory, within_windows


class WindowsReleaseGateTests(unittest.TestCase):
    def fixture(self):
        reviewed = dict(pyinstaller_version='6.16.0', runtime_files={f'_internal/{i}.dll': 'a'*64 for i in range(23)})
        binaries = [dict(path=name, sha256=sha, origin_hash_verified=True,
            origin_candidates=[dict(source='C:/Python/' + name.rsplit('/',1)[1], sha256=sha)],
            imports=[dict(name='kernel32.dll', resolved='C:/Windows/System32/kernel32.dll')]) for name, sha in reviewed['runtime_files'].items()]
        binaries += [dict(path=name, sha256='b'*64, origin_hash_verified=True, imports=[]) for name in ('PSPortalProxy.exe','native/psportal-native.exe')]
        report = dict(inventory_complete=True, issues=[], binaries=binaries,
            files=[dict(path=b['path'],sha256=b['sha256']) for b in binaries], app='D:/app',
            runtime=dict(base_prefix='C:/Python', pyinstaller='6.16.0'))
        add_yaml_evidence(report, 'win32')
        return report, reviewed

    def test_exact_reviewed_runtime_accepts_and_changed_content_fails(self):
        report, reviewed = self.fixture()
        self.assertEqual(len(verify_inventory(report, reviewed, 'C:/Windows')),26)
        report['binaries'][0]['sha256'] = 'c'*64
        with self.assertRaises(ValueError): verify_inventory(report, reviewed, 'C:/Windows')

    def test_unknown_origin_and_unresolved_inventory_fail_closed(self):
        for mutation in ('origin', 'extra', 'issue', 'version'):
            report, reviewed = self.fixture()
            if mutation == 'origin': report['binaries'][0]['origin_candidates'][0]['source'] = 'C:/JDK/0.dll'
            elif mutation == 'extra': report['binaries'].append(copy.deepcopy(report['binaries'][0]))
            elif mutation == 'issue': report['issues'] = ['unverified']
            else: report['runtime']['pyinstaller'] = 'unreviewed'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): verify_inventory(report, reviewed, 'C:/Windows')

    def test_api_set_requires_actual_system_proof_and_no_jdk_imports(self):
        report, reviewed = self.fixture()
        item = report['binaries'][0]['imports'][0]
        item.update(name='api-ms-win-core-path-l1-1-0.dll')
        with self.assertRaises(ValueError): verify_inventory(report, reviewed, 'C:/Windows')
        item.update(resolution_method='windows-api-set-system-loader',system_sha256='d'*64)
        verify_inventory(report, reviewed, 'C:/Windows')
        item['system_sha256']='not-a-hash'
        with self.assertRaises(ValueError): verify_inventory(report, reviewed, 'C:/Windows')
        item['system_sha256']='d'*64
        item['resolved']='D:/app/KernelBase.dll'
        with self.assertRaises(ValueError): verify_inventory(report, reviewed, 'C:/Windows')
        item['resolved']='C:/JDK/api-ms-win-core-path-l1-1-0.dll'
        with self.assertRaises(ValueError): verify_inventory(report, reviewed, 'C:/Windows')

    def test_binary_inventory_must_match_unique_archived_file_hashes(self):
        for change in ('hash','duplicate','missing'):
            report,reviewed=self.fixture()
            if change=='hash':report['files'][0]['sha256']='c'*64
            elif change=='duplicate':report['files'].append(copy.deepcopy(report['files'][0]))
            else:report['files'].pop(0)
            with self.subTest(change=change),self.assertRaises(ValueError):verify_inventory(report,reviewed,'C:/Windows')

    def test_archive_matches_every_tested_file_and_rejects_changes_or_extras(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive=Path(tmp)/'package.zip'; data=b'tested bytes'
            files=[dict(path='PSPortalProxy.exe',sha256=hashlib.sha256(data).hexdigest())]
            for content, extra in ((data,False),(b'changed',False),(data,True)):
                with zipfile.ZipFile(archive,'w') as z:
                    z.writestr('PSPortalProxy/PSPortalProxy.exe',content)
                    if extra:z.writestr('unexpected.exe',b'extra')
                if content==data and not extra:verify_archive(archive,files)
                else:
                    with self.assertRaises(ValueError):verify_archive(archive,files)

    def test_windows_path_scope_is_case_insensitive_but_bounded(self):
        self.assertTrue(within_windows('c:/WINDOWS/system32/kernel32.dll','C:/Windows/System32'))
        self.assertFalse(within_windows('C:/Windows/System32extra/kernel32.dll','C:/Windows/System32'))
        self.assertFalse(within_windows('relative.dll','C:/Windows/System32'))
        self.assertFalse(within_windows(None,'C:/Windows/System32'))
        self.assertFalse(within_windows('C:/Windows/System32/../untrusted.dll','C:/Windows/System32'))
        self.assertFalse(within_windows('C:/Windows/System32/kernel32.dll','C:/Windows/System32/../System32'))

