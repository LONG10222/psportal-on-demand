"""Offline fail-closed tests for the specifically reviewed Windows release gate."""
import copy
import hashlib
import json
import io
from pathlib import Path
import tempfile
import tarfile
import unittest
from unittest.mock import patch
import zipfile
from yaml_packaging_fixtures import add_yaml_evidence
from scripts.verify_windows_release import verify_archive, verify_inventory, verify_default_core, within_windows


class WindowsReleaseGateTests(unittest.TestCase):
    def fixture(self):
        reviewed = json.loads((Path(__file__).resolve().parents[1] / 'notices/windows-cpython-3.13.16-runtime.json').read_text())
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
        self.assertEqual(len(verify_inventory(report, reviewed, 'C:/Windows')),28)
        report['binaries'][0]['sha256'] = 'c'*64
        with self.assertRaises(ValueError): verify_inventory(report, reviewed, 'C:/Windows')

    def test_new_cpython_extensions_require_exact_hashes_and_selected_installation(self):
        for name in ('_internal/_wmi.pyd', '_internal/VCRUNTIME140_1.dll'):
            for mutation in ('missing', 'hash', 'origin', 'unverified'):
                report, reviewed = self.fixture()
                binary = next(b for b in report['binaries'] if b['path'] == name)
                if mutation == 'missing': report['binaries'].remove(binary)
                elif mutation == 'hash':
                    binary['sha256'] = 'c'*64
                    next(f for f in report['files'] if f['path'] == name)['sha256'] = 'c'*64
                elif mutation == 'origin': binary['origin_candidates'][0]['source'] = 'C:/JDK/runtime.dll'
                else: binary['origin_hash_verified'] = False
                with self.subTest(name=name, mutation=mutation), self.assertRaises(ValueError):
                    verify_inventory(report, reviewed, 'C:/Windows')

    def test_default_core_is_independently_pinned_and_required_for_release(self):
        from scripts.default_mihomo import BINARY_SHA256, VERSION
        report, reviewed = self.fixture()
        with self.assertRaises(ValueError):
            verify_inventory(report, reviewed, 'C:/Windows', require_default_mihomo=True)
        core = dict(path='mihomo.exe', sha256=BINARY_SHA256, origin_hash_verified=True,
                    imports=[], origin_candidates=[dict(type='PINNED_OFFICIAL_MIHOMO',
                    source='https://github.com/MetaCubeX/mihomo/releases/tag/' + VERSION,
                    sha256=BINARY_SHA256)])
        report['binaries'].append(core)
        report['files'].append(dict(path=core['path'], sha256=core['sha256']))
        self.assertEqual(len(verify_inventory(report, reviewed, 'C:/Windows', require_default_mihomo=True)), 29)
        for field, value in (('type', 'BINARY'), ('sha256', 'c'*64), ('source', 'C:/unreviewed/mihomo.exe')):
            changed = copy.deepcopy(report)
            changed['binaries'][-1]['origin_candidates'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_inventory(changed, reviewed, 'C:/Windows')
        core['sha256'] = 'c'*64
        report['files'][-1]['sha256'] = 'c'*64
        with self.assertRaises(ValueError): verify_inventory(report, reviewed, 'C:/Windows')

    def test_default_core_gate_binds_complete_source_and_full_license(self):
        from scripts import default_mihomo
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary)
            notices = app / 'licenses/mihomo-v1.19.32'
            notices.mkdir(parents=True)
            source = notices / 'mihomo-v1.19.32-source.zip'
            binary = app / 'mihomo.exe'
            binary.write_bytes(b'MZfixture')
            (notices / 'LICENSE.txt').write_bytes(b'full license')
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('mihomo-1.19.32/LICENSE', b'full license')
            complete = notices / 'corresponding-source.tar.gz'
            def write_complete(license_text=b'full license'):
                with tarfile.open(complete, 'w:gz') as archive:
                    for name, data in (('LICENSE', license_text), ('vendor/modules.txt', b'# module v1.0'), ('VENDOR-SHA256.json', json.dumps({'vendor/modules.txt': hashlib.sha256(b'# module v1.0').hexdigest()}).encode())):
                        member = tarfile.TarInfo('mihomo-1.19.32/' + name)
                        member.size = len(data)
                        archive.addfile(member, io.BytesIO(data))
            write_complete()
            validation = dict(default_mihomo_bundled=True,
                              default_mihomo_complete_source_sha256=hashlib.sha256(complete.read_bytes()).hexdigest())
            with patch.object(default_mihomo, 'BINARY_SHA256', hashlib.sha256(binary.read_bytes()).hexdigest()), \
                 patch.object(default_mihomo, 'SOURCE_SHA256', hashlib.sha256(source.read_bytes()).hexdigest()):
                verify_default_core(app, validation)
                for key, value in (('default_mihomo_bundled', False),
                                   ('default_mihomo_complete_source_sha256', 'c'*64)):
                    with self.subTest(key=key), self.assertRaises(ValueError):
                        verify_default_core(app, dict(validation, **{key: value}))
                write_complete(b'changed license')
                with self.assertRaises(ValueError): verify_default_core(app, validation)
                complete.unlink()
                with self.assertRaises(FileNotFoundError): verify_default_core(app, validation)

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

