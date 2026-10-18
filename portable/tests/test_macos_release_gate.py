"""Display-free strict provenance and tar tests for the macOS release gate."""
import copy
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from scripts.verify_macos_release import (APP_EXECUTABLE, NATIVE_EXECUTABLE, METHOD,
    companion_candidates, resolve_bundle_path, verify_archive, verify_inventory, within_posix)


class MacOSReleaseGateTests(unittest.TestCase):
    def fixture(self):
        runtime_files = {f'Contents/Frameworks/lib{i}.dylib': dict(source_relative=f'lib/lib{i}.dylib',
            source_sha256='a'*64, type='BINARY', resolved_bundle_path=f'Contents/Frameworks/lib{i}.dylib') for i in range(61)}
        reviewed = dict(architecture='arm64', python_version='3.13.15', pyinstaller_version='6.16.0',
            original_python_prefix='/Python', expected_binary_path_count=63, expected_bundle_symlinks=[], runtime_files=runtime_files)
        binaries = []
        for path, item in runtime_files.items():
            source='/Python/' + item['source_relative']
            binaries.append(dict(path=path, format='Mach-O', sha256='b'*64, origin_hash_verified=False,
                origin_transformation_verified=True, origin_candidates=[dict(source=source, sha256='a'*64, type='BINARY')],
                origin_transformation_proofs=[dict(verified=True, method=METHOD, architecture='arm64',
                    pyinstaller='6.16.0', source=source, source_sha256='a'*64, packaged='/app/' + path,
                    packaged_sha256='b'*64, normalized_source_sha256='c'*64, normalized_packaged_sha256='c'*64)],
                imports=[dict(name='/usr/lib/libSystem.B.dylib', resolved='/usr/lib/libSystem.B.dylib')]))
        binaries.append(dict(path=APP_EXECUTABLE,format='Mach-O',sha256='d'*64,origin_hash_verified=True,
            origin_candidates=[dict(source='/build/PSPortalProxy',sha256='d'*64,type='EXECUTABLE')],imports=[]))
        binaries.append(dict(path=NATIVE_EXECUTABLE,format='Mach-O',sha256='e'*64,origin_hash_verified=True,
            origin_candidates=[dict(source='/native/dist/psportal',sha256='e'*64,type='REVIEWED_NATIVE')],imports=[]))
        report = dict(inventory_complete=True, issues=[], app='/app', build='/build', binaries=binaries,
            files=[dict(path=b['path'],sha256=b['sha256']) for b in binaries], symlinks=[],
            runtime=dict(python='3.13.15 (exact)',pyinstaller='6.16.0',base_prefix='/Python'))
        return report,reviewed

    def test_full_byte_proof_accepts_and_changed_regions_fail(self):
        report,reviewed=self.fixture()
        self.assertEqual(len(verify_inventory(report,reviewed)[0]),63)
        report['binaries'][0]['origin_transformation_proofs'][0]['normalized_packaged_sha256']='f'*64
        with self.assertRaises(ValueError):verify_inventory(report,reviewed)

    def test_proofs_bind_pinned_source_packaged_hash_architecture_and_path(self):
        for key,value in (('source_sha256','f'*64),('packaged_sha256','f'*64),('architecture','x86_64'),
                          ('source','/other/lib0.dylib'),('packaged','/other/lib0.dylib'),
                          ('normalized_source_sha256',''),('method','trust-load-commands'),('pyinstaller','7.0.0')):
            report,reviewed=self.fixture()
            report['binaries'][0]['origin_transformation_proofs'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):verify_inventory(report,reviewed)

    def test_unknown_origins_file_hash_mismatch_and_duplicate_evidence_fail(self):
        for mutation in ('extra','filehash','duplicate','candidate','issue','version'):
            report,reviewed=self.fixture()
            if mutation=='extra':report['binaries'].append(copy.deepcopy(report['binaries'][0]))
            elif mutation=='filehash':report['files'][0]['sha256']='f'*64
            elif mutation=='duplicate':report['files'].append(copy.deepcopy(report['files'][0]))
            elif mutation=='candidate':report['binaries'][0]['origin_candidates'][0]['source']='/untrusted/lib0.dylib'
            elif mutation=='issue':report['issues']=['unverified']
            else:report['runtime']['python']='3.13.16 (different)'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):verify_inventory(report,reviewed)

    def test_dependencies_are_exact_bundle_or_system_scope(self):
        for path in ('/opt/unreviewed/lib.dylib','/usr/lib/../unreviewed.dylib','/usr/library/lib.dylib',None):
            report,reviewed=self.fixture();report['binaries'][0]['imports'][0]['resolved']=path
            with self.subTest(path=path),self.assertRaises(ValueError):verify_inventory(report,reviewed)
        self.assertTrue(within_posix('/System/Library/a','/System/Library'))
        self.assertFalse(within_posix('/System/LibraryExtra/a','/System/Library'))

    def test_symlink_chains_resolve_but_escapes_and_cycles_fail(self):
        links={'Contents/Resources/Python':'Python.framework/Python',
               'Contents/Resources/Python.framework':'../Frameworks/Python.framework',
               'Contents/Frameworks/Python.framework/Python':'Versions/Current/Python',
               'Contents/Frameworks/Python.framework/Versions/Current':'3.13'}
        self.assertEqual(resolve_bundle_path('Contents/Resources/Python',links),
                         'Contents/Frameworks/Python.framework/Versions/3.13/Python')
        for bad in ({'a':'../outside'},{'a':'/outside'},{'a':'b','b':'a'}):
            with self.assertRaises(ValueError):resolve_bundle_path('a',bad)
        report,reviewed=self.fixture();report['symlinks']=[dict(path='a',target='b')]
        with self.assertRaises(ValueError):verify_inventory(report,reviewed)

    def test_tar_binds_every_file_notice_and_exact_symlink(self):
        payload=b'known executable'; notice=b'full notice'; sha=lambda data:hashlib.sha256(data).hexdigest()
        files={'Contents/MacOS/app':dict(sha256=sha(payload)), 'Contents/Resources/app':dict(sha256=sha(payload))}
        links={'Contents/Resources/app':'../MacOS/app'};companion={'licenses/COPYING':sha(notice)}
        with tempfile.TemporaryDirectory() as temporary:
            archive=Path(temporary)/'app.tar.gz'
            for mutation in ('none','changed','extra','link','hardlink','duplicate','escape','missing'):
                with tarfile.open(archive,'w:gz') as stream:
                    def add(name,data):
                        member=tarfile.TarInfo(name);member.size=len(data);stream.addfile(member,io.BytesIO(data))
                    add('PSPortalProxy.app/Contents/MacOS/app',b'changed' if mutation=='changed' else payload)
                    link=tarfile.TarInfo('PSPortalProxy.app/Contents/Resources/app')
                    link.type=tarfile.LNKTYPE if mutation=='hardlink' else tarfile.SYMTYPE
                    link.linkname='/outside' if mutation=='link' else links['Contents/Resources/app'];stream.addfile(link)
                    if mutation!='missing':add('licenses/COPYING',notice)
                    if mutation=='extra':add('unreviewed.dylib',b'extra')
                    if mutation=='duplicate':add('licenses/COPYING',notice)
                    if mutation=='escape':add('../outside',b'extra')
                if mutation=='none':verify_archive(archive,files,links,companion)
                else:
                    with self.subTest(mutation=mutation),self.assertRaises(ValueError):verify_archive(archive,files,links,companion)

    def test_symlink_alias_file_hash_is_bound_to_actual_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive=Path(temporary)/'unused.tar.gz'
            files={'real':dict(sha256='a'*64),'alias':dict(sha256='b'*64)}
            with self.assertRaises(ValueError):verify_archive(archive,files,{'alias':'real'},{})

    def test_archive_rejects_privileged_modes_and_lost_owner_execute(self):
        data=b'tested';sha=hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            archive=Path(temporary)/'app.tar.gz'
            for mode in (0o755,0o644,0o4755,0o2755,0o011):
                with tarfile.open(archive,'w:gz') as stream:
                    member=tarfile.TarInfo('PSPortalProxy.app/'+APP_EXECUTABLE)
                    member.size=len(data);member.mode=mode;stream.addfile(member,io.BytesIO(data))
                if mode==0o755:verify_archive(archive,{APP_EXECUTABLE:dict(sha256=sha)}, {}, {})
                else:
                    with self.subTest(mode=mode),self.assertRaises(ValueError):
                        verify_archive(archive,{APP_EXECUTABLE:dict(sha256=sha)}, {}, {})

    def test_companion_notice_duplicates_fail_closed(self):
        item=dict(source='/app/licenses/COPYING',sha256='a'*64,locations=['already-packaged-companion'])
        self.assertEqual(companion_candidates(dict(license_candidates=[item])), {item['source']:item['sha256']})
        with self.assertRaises(ValueError):companion_candidates(dict(license_candidates=[item,copy.deepcopy(item)]))
