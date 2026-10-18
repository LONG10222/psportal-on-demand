"""Display-free strict provenance and tar tests for the macOS release gate."""
import copy
import hashlib
import io
from pathlib import Path, PurePosixPath, PureWindowsPath
import tarfile
import tempfile
import unittest
from scripts.verify_macos_release import (APP_EXECUTABLE, NATIVE_EXECUTABLE, NATIVE_RESOURCE_ALIAS, NATIVE_COMPATIBILITY_LINKS, METHOD,
    companion_candidates, resolve_bundle_path, verify_archive, verify_inventory, verify_final_seal, within_posix)


class MacOSReleaseGateTests(unittest.TestCase):
    def fixture(self):
        runtime_files = {f'Contents/Frameworks/lib{i}.dylib': dict(source_relative=f'lib/lib{i}.dylib',
            source_sha256='a'*64, type='BINARY', resolved_bundle_path=f'Contents/Frameworks/lib{i}.dylib') for i in range(61)}
        reviewed = dict(architecture='arm64', python_version='3.13.15', pyinstaller_version='6.16.0',
            original_python_prefix='/Python', expected_binary_path_count=64, expected_bundle_symlinks=[dict(path=k,target=v) for k,v in NATIVE_COMPATIBILITY_LINKS.items()], runtime_files=runtime_files)
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
        binaries.append(dict(binaries[-1], path=NATIVE_RESOURCE_ALIAS))
        report = dict(inventory_complete=True, issues=[], app='/app', build='/build', binaries=binaries,
            files=[dict(path=b['path'],sha256=b['sha256']) for b in binaries], symlinks=copy.deepcopy(reviewed['expected_bundle_symlinks']),
            runtime=dict(python='3.13.15 (exact)',pyinstaller='6.16.0',base_prefix='/Python'))
        return report,reviewed

    def test_full_byte_proof_accepts_and_changed_regions_fail(self):
        report,reviewed=self.fixture()
        self.assertEqual(len(verify_inventory(report,reviewed)[0]),64)
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

    def test_empty_directories_are_bound_to_the_exact_tested_tree(self):
        data=b'tested';sha=hashlib.sha256(data).hexdigest()
        expected={'PSPortalProxy.app','PSPortalProxy.app/empty'}
        with tempfile.TemporaryDirectory() as temporary:
            archive=Path(temporary)/'app.tar.gz'
            for mutation in ('none','missing','extra','privileged'):
                with tarfile.open(archive,'w:gz') as stream:
                    dirs=expected-{'PSPortalProxy.app/empty'} if mutation=='missing' else set(expected)
                    if mutation=='extra':dirs.add('PSPortalProxy.app/unknown')
                    for path in sorted(dirs):
                        member=tarfile.TarInfo(path);member.type=tarfile.DIRTYPE
                        member.mode=0o4755 if mutation=='privileged' else 0o755;stream.addfile(member)
                    member=tarfile.TarInfo('PSPortalProxy.app/file');member.size=len(data)
                    stream.addfile(member,io.BytesIO(data))
                if mutation=='none':verify_archive(archive,{'file':dict(sha256=sha)}, {}, {}, expected)
                else:
                    with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                        verify_archive(archive,{'file':dict(sha256=sha)}, {}, {}, expected)

    def test_native_alias_and_real_helper_require_identical_bytes_and_exact_layout(self):
        for mutation in ('hash', 'alias', 'directory'):
            report,reviewed=self.fixture()
            if mutation=='hash':
                for item in report['binaries']+report['files']:
                    if item['path']==NATIVE_RESOURCE_ALIAS:item['sha256']='f'*64
            else:
                path=NATIVE_RESOURCE_ALIAS if mutation=='alias' else 'Contents/MacOS/native'
                for item in report['symlinks']:
                    if item['path']==path:item['target']='../Frameworks'
                reviewed['expected_bundle_symlinks']=copy.deepcopy(report['symlinks'])
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):verify_inventory(report,reviewed)

    def seal_fixture(self):
        report,reviewed=self.fixture()
        binaries,files,links=verify_inventory(report,reviewed)
        files['Contents/_CodeSignature/CodeResources']=dict(sha256='9'*64)
        nested={resolve_bundle_path(path,links):item['sha256'] for path,item in binaries.items() if path!=APP_EXECUTABLE}
        success=lambda argv:dict(argv=argv,returncode=0)
        seal=dict(schema_version=1,source_commit='commit',app='/app',passed=True,
            final_deep_strict_verified=True,nested_strict_verified=True,signing_identity='ad-hoc',
            developer_id=False,notarized=False,deep_signing_used=False,nested_macho_before=nested,
            nested_macho_after=copy.deepcopy(nested),main_sha256_before='8'*64,main_sha256_after='d'*64,
            code_resources_sha256='9'*64,native_sha256='e'*64,native_aliases=NATIVE_COMPATIBILITY_LINKS,
            native_resource_envelope_entry='MacOS/psportal-native',commands=[
                success(['/usr/bin/codesign','--force','--sign','-','--timestamp=none','/app']),
                success(['/usr/bin/codesign','--verify','--deep','--strict','--verbose=2','/app'])]+
                [success(['/usr/bin/codesign','--verify','--strict','--verbose=2','/app/'+path])
                 for path in {*nested,APP_EXECUTABLE}])
        extracted='/final-macos-archive/PSPortalProxy.app'
        acceptance=dict(schema_version=1,source_commit='commit',passed=True,
            extracted_deep_strict_verified=True,launchservices_window_verified=True,
            archive='/release/app.tar.gz',archive_sha256='1'*64,bundle_seal_sha256='2'*64,
            app=extracted,extracted_tree_sha256='3'*64,nested_macho_sha256=nested,main_sha256='d'*64,
            code_resources_sha256='9'*64,launchservices_receipt=dict(app=extracted,visible=True,
                normal_quit=True,no_listener=True,open_exitcode=0),commands=[
                success(['/usr/bin/codesign','--verify','--deep','--strict','--verbose=2',extracted])]*2)
        args=[report,binaries,files,links,dict(source_commit='commit',native_binary_sha256='e'*64),
              seal,acceptance,PurePosixPath('/release/app.tar.gz'),'1'*64,'2'*64,'3'*64]
        return args

    def test_final_seal_and_extracted_launch_are_bound_to_exact_artifact(self):
        verify_final_seal(*self.seal_fixture())
        for target,key,value in ((5,'source_commit','other'),(5,'passed',False),
                (5,'nested_macho_before',{}),(5,'main_sha256_after','f'*64),
                (5,'native_sha256','f'*64),(5,'code_resources_sha256','f'*64),
                (5,'deep_signing_used',True),(5,'native_aliases',{}),
                (6,'archive_sha256','f'*64),(6,'bundle_seal_sha256','f'*64),
                (6,'extracted_tree_sha256','f'*64),(6,'nested_macho_sha256',{}),
                (6,'launchservices_receipt',{}),(6,'launchservices_window_verified',False),
                (6,'app','/another/PSPortalProxy.app')):
            args=self.seal_fixture();args[target][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):verify_final_seal(*args)

    def test_final_seal_requires_exact_outer_signing_and_both_postarchive_checks(self):
        for mutation in ('identity','deep-sign','nested-missing','nested-failed','archive-once','archive-failed'):
            args=self.seal_fixture();seal,acceptance=args[5:7]
            if mutation=='identity':seal['commands'][0]['argv'][3]='developer-key'
            elif mutation=='deep-sign':seal['commands'][0]['argv'].insert(1,'--deep')
            elif mutation=='nested-missing':seal['commands'].pop()
            elif mutation=='nested-failed':seal['commands'][-1]['returncode']=1
            elif mutation=='archive-once':acceptance['commands'].pop()
            else:acceptance['commands'][0]['returncode']=1
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):verify_final_seal(*args)

    def test_synthetic_macos_receipt_uses_posix_paths_on_every_host(self):
        args=self.seal_fixture()
        self.assertEqual(str(args[7]), args[6]['archive'])
        verify_final_seal(*args)
        args[7]=PureWindowsPath('/release/app.tar.gz')
        with self.assertRaises(ValueError):verify_final_seal(*args)
