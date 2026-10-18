"""Fail-closed gate for the individually reviewed macOS arm64 development app.

Bind exact installed runtime origins, full-byte transformation proofs, complete
notices and successful runtime/window checks to every shipped tar member.
No Developer ID signing, notarization or physical Portal acceptance is claimed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
APP_EXECUTABLE = 'Contents/MacOS/PSPortalProxy'
NATIVE_EXECUTABLE = 'Contents/MacOS/psportal-native'
NATIVE_RESOURCE_ALIAS = 'Contents/Resources/native/psportal-native'
NATIVE_COMPATIBILITY_LINKS = {
    'Contents/MacOS/native': '../Resources/native',
    NATIVE_RESOURCE_ALIAS: '../../MacOS/psportal-native',
}
METHOD = 'pinned-pyinstaller-transform-and-signature-removal'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_relative(value):
    return bool(isinstance(value, str) and value and '\\' not in value and
                not PurePosixPath(value).is_absolute() and '..' not in PurePosixPath(value).parts and
                str(PurePosixPath(value)) == value and value != '.')


def within_posix(value, root):
    return bool(isinstance(value, str) and isinstance(root, str) and
                '..' not in PurePosixPath(value).parts and '..' not in PurePosixPath(root).parts and
                PurePosixPath(value).is_absolute() and PurePosixPath(root).is_absolute() and
                PurePosixPath(value).is_relative_to(PurePosixPath(root)))


def unique_records(records, label):
    result = {}
    for record in records:
        path = record.get('path')
        require(safe_relative(path) and path not in result, 'Unsafe or duplicate ' + label + ' path')
        result[path] = record
    return result


def resolve_bundle_path(value, links):
    require(safe_relative(value), 'Unsafe bundle path')
    for _ in range(32):
        parts = value.split('/')
        for index in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:index])
            if prefix in links:
                target = links[prefix]
                require(isinstance(target, str) and target and '\\' not in target and
                        not PurePosixPath(target).is_absolute(), 'Unsafe absolute bundle symlink')
                value = posixpath.normpath(posixpath.join(posixpath.dirname(prefix), target, *parts[index:]))
                require(safe_relative(value), 'Bundle symlink escapes app')
                break
        else:
            return value
    raise ValueError('Bundle symlink cycle or excessive chain')


def verified_origin(binary, source, source_sha, packaged, kind):
    candidates = binary.get('origin_candidates', [])
    if not any(item.get('source') == source and item.get('sha256') == source_sha and
               item.get('type') == kind for item in candidates):
        return False
    if binary.get('origin_hash_verified') is True and binary['sha256'] == source_sha:
        return True
    for proof in binary.get('origin_transformation_proofs', []):
        normalized = proof.get('normalized_source_sha256', '')
        if (binary.get('origin_transformation_verified') is True and proof.get('verified') is True and
            proof.get('method') == METHOD and proof.get('architecture') == 'arm64' and
            proof.get('pyinstaller') == '6.16.0' and proof.get('source') == source and
            proof.get('source_sha256') == source_sha and proof.get('packaged') == packaged and
            proof.get('packaged_sha256') == binary['sha256'] and
            re.fullmatch('[0-9a-f]{64}', normalized) and
            proof.get('normalized_packaged_sha256') == normalized):
            return True
    return False


def verify_inventory(report, reviewed):
    require(report.get('inventory_complete') is True and not report.get('issues'), 'Runtime inventory has unresolved issues')
    require(reviewed.get('architecture') == 'arm64' and reviewed.get('python_version') == '3.13.15' and
            reviewed.get('pyinstaller_version') == '6.16.0', 'Unreviewed runtime manifest')
    runtime = report['runtime']
    require(runtime['pyinstaller'] == reviewed['pyinstaller_version'] and
            runtime['base_prefix'] == reviewed['original_python_prefix'] and
            runtime['python'].startswith(reviewed['python_version'] + ' '), 'Selected runtime differs from review')
    files = unique_records(report.get('files', []), 'file')
    binaries = unique_records(report.get('binaries', []), 'binary')
    links = {key: value['target'] for key, value in unique_records(report.get('symlinks', []), 'symlink').items()}
    expected_links = {key: value['target'] for key, value in unique_records(reviewed['expected_bundle_symlinks'], 'reviewed symlink').items()}
    require(links == expected_links and all(links.get(path) == target for path, target in NATIVE_COMPATIBILITY_LINKS.items()),
            'Bundle symlink topology differs from review')
    for path in links:
        resolve_bundle_path(path, links)
    require(len(binaries) == reviewed['expected_binary_path_count'] == 64 and
            set(binaries) == set(reviewed['runtime_files']) | {APP_EXECUTABLE, NATIVE_EXECUTABLE, NATIVE_RESOURCE_ALIAS}, 'Unexpected frozen binaries')
    require(binaries[NATIVE_EXECUTABLE]['sha256'] == binaries[NATIVE_RESOURCE_ALIAS]['sha256'] and
            resolve_bundle_path(NATIVE_RESOURCE_ALIAS, links) == NATIVE_EXECUTABLE,
            'Native resource alias differs from the actual code helper')
    app, build = report['app'], report['build']
    require(within_posix(app, '/') and within_posix(build, '/'), 'Invalid build evidence paths')
    for path, binary in binaries.items():
        require(binary.get('format') == 'Mach-O' and path in files and
                binary['sha256'] == files[path]['sha256'] and re.fullmatch('[0-9a-f]{64}', binary['sha256']),
                'Binary and archive file evidence disagree')
        resolved_relative = resolve_bundle_path(path, links)
        packaged = str(PurePosixPath(app) / resolved_relative)
        if path in reviewed['runtime_files']:
            expected = reviewed['runtime_files'][path]
            require(safe_relative(expected['source_relative']) and
                    resolved_relative == expected['resolved_bundle_path'], 'Runtime destination differs from review')
            source = str(PurePosixPath(runtime['base_prefix']) / expected['source_relative'])
            require(verified_origin(binary, source, expected['source_sha256'], packaged, expected['type']),
                    'Runtime full-byte origin proof failed: ' + path)
        elif path == APP_EXECUTABLE:
            source = str(PurePosixPath(build) / 'PSPortalProxy')
            require(any(verified_origin(binary, source, candidate.get('sha256'), packaged, 'EXECUTABLE')
                        for candidate in binary.get('origin_candidates', []) if candidate.get('source') == source),
                    'Frozen executable does not match the current build')
        else:
            require(binary.get('origin_hash_verified') is True and any(
                item.get('type') == 'REVIEWED_NATIVE' and item.get('sha256') == binary['sha256']
                for item in binary.get('origin_candidates', [])), 'Native engine has no exact build origin')
        for item in binary.get('imports', []):
            require(any(within_posix(item.get('resolved'), root) for root in (app, '/usr/lib', '/System/Library')),
                    'Dependency is outside bundle and macOS system libraries: ' + str(item.get('name')))
    return binaries, files, links


def verify_archive(archive, files, links, companion, directories=None):
    regular = {'PSPortalProxy.app/' + path: item['sha256'] for path, item in files.items() if path not in links}
    for path, item in files.items():
        if path in links:
            target = resolve_bundle_path(path, links)
            require(target in files and target not in links and files[target]['sha256'] == item['sha256'],
                    'Symlink file hash disagrees with its final target')
    require(not set(regular) & set(companion), 'Companion archive path collides with app')
    regular.update(companion)
    expected_links = {'PSPortalProxy.app/' + path: target for path, target in links.items()}
    if directories is not None:
        require(all(safe_relative(name) for name in directories), 'Unsafe expected archive directory')
    seen, actual_regular, actual_links, actual_directories = set(), {}, {}, set()
    with tarfile.open(archive, 'r:gz') as stream:
        for member in stream:
            name = member.name.rstrip('/')
            require(safe_relative(name) and name not in seen, 'Unsafe or duplicate tar member')
            seen.add(name)
            require(member.mode & 0o6000 == 0, 'Privileged archive member mode is not accepted')
            if member.isdir():
                require(name in directories if directories is not None else
                        any(path.startswith(name + '/') for path in (*regular, *expected_links)),
                        'Unexpected archive directory: ' + name)
                actual_directories.add(name)
            elif member.issym():
                actual_links[name] = member.linkname
            elif member.isfile():
                require(name in regular, 'Uninventoried archive file: ' + name)
                if name in ('PSPortalProxy.app/' + APP_EXECUTABLE, 'PSPortalProxy.app/' + NATIVE_EXECUTABLE):
                    require(member.mode & 0o100, 'Archive executable lost owner execute permission')
                app_relative = name.removeprefix('PSPortalProxy.app/')
                if app_relative in files and 'mode' in files[app_relative]:
                    require(member.mode & 0o777 == files[app_relative]['mode'], 'Archive file permissions changed')
                actual_regular[name] = digest(stream.extractfile(member).read())
            else:
                raise ValueError('Hardlinks and special archive members are not accepted')
    require(actual_regular == regular and actual_links == expected_links, 'Archive differs from exact tested files, notices or symlink targets')
    if directories is not None:
        require(actual_directories == directories, 'Archive differs from tested directory set')


def verify_final_seal(report, binaries, files, links, validation, seal, acceptance,
                      archive_path, archive_sha256, seal_sha256, archive_tree_sha256):
    """Cross-bind actual seal/extracted launch receipts to this inventoried artifact."""
    app = report['app']
    commit = validation['source_commit']
    require(seal.get('source_commit') == acceptance.get('source_commit') == commit and
            seal.get('schema_version') == acceptance.get('schema_version') == 1,
            'Final seal/acceptance evidence is from another source revision')
    require(seal.get('app') == app and all(seal.get(key) is True for key in (
            'passed', 'final_deep_strict_verified', 'nested_strict_verified')) and
            seal.get('signing_identity') == 'ad-hoc' and seal.get('deep_signing_used') is False and
            seal.get('developer_id') is False and seal.get('notarized') is False,
            'Final outer-only ad-hoc seal or strict nested verification is missing')
    nested = {resolve_bundle_path(path, links): item['sha256'] for path, item in binaries.items()
              if path != APP_EXECUTABLE}
    require(seal.get('nested_macho_before') == seal.get('nested_macho_after') == nested,
            'Final signing changed or omitted nested Mach-O code')
    main_sha = binaries[APP_EXECUTABLE]['sha256']
    envelope_sha = files['Contents/_CodeSignature/CodeResources']['sha256']
    require(seal.get('main_sha256_after') == main_sha and
            seal.get('code_resources_sha256') == envelope_sha and
            re.fullmatch('[0-9a-f]{64}', seal.get('main_sha256_before', '')) and
            seal.get('native_sha256') == binaries[NATIVE_EXECUTABLE]['sha256'] == validation['native_binary_sha256'] and
            seal.get('native_aliases') == NATIVE_COMPATIBILITY_LINKS and
            seal.get('native_resource_envelope_entry') == 'MacOS/psportal-native',
            'Final seal is not bound to the exact inventoried app and native helper')
    def succeeded(evidence, argv, minimum=1):
        return sum(item.get('argv') == argv and item.get('returncode') == 0
                   for item in evidence.get('commands', [])) >= minimum
    signing = [item for item in seal.get('commands', []) if '--sign' in item.get('argv', [])]
    require(len(signing) == 1 and signing[0].get('returncode') == 0 and
            signing[0]['argv'] == ['/usr/bin/codesign', '--force', '--sign', '-', '--timestamp=none', app],
            'Unexpected signing command or identity')
    require(succeeded(seal, ['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', app]) and
            all(succeeded(seal, ['/usr/bin/codesign', '--verify', '--strict', '--verbose=2',
                 str(PurePosixPath(app) / path)]) for path in {*nested, APP_EXECUTABLE}),
            'Successful exact-app/nested codesign command evidence is missing')
    extracted_app = str(PurePosixPath(report['build']).parent / 'final-macos-archive/PSPortalProxy.app')
    require(all(acceptance.get(key) is True for key in (
            'passed', 'extracted_deep_strict_verified', 'launchservices_window_verified')) and
            acceptance.get('archive') == str(archive_path) and acceptance.get('archive_sha256') == archive_sha256 and
            acceptance.get('bundle_seal_sha256') == seal_sha256 and acceptance.get('app') == extracted_app and
            acceptance.get('extracted_tree_sha256') == archive_tree_sha256,
            'Extracted archive acceptance is missing or bound to another archive')
    require(acceptance.get('nested_macho_sha256') == nested and acceptance.get('main_sha256') == main_sha and
            acceptance.get('code_resources_sha256') == envelope_sha and
            acceptance.get('launchservices_receipt') == dict(app=extracted_app, visible=True, normal_quit=True,
                                                            no_listener=True, open_exitcode=0),
            'Extracted app or actual LaunchServices receipt differs from this sealed build')
    require(succeeded(acceptance, ['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2',
                                  extracted_app], minimum=2),
            'Extracted app was not strictly verified before and after launch')


def companion_candidates(report):
    result = {}
    for item in report['license_candidates']:
        if 'already-packaged-companion' in item['locations']:
            require(item['source'] not in result, 'Duplicate companion notice evidence')
            result[item['source']] = item['sha256']
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=ROOT / 'runtime-inventory/runtime-inventory.json')
    args = parser.parse_args(argv)
    require(sys.platform == 'darwin', 'The macOS release gate must run on the actual host')
    report = json.loads(args.inventory.read_text(encoding='utf-8'))
    reviewed = json.loads((ROOT / 'notices/macos-cpython-3.13.15-runtime.json').read_text(encoding='utf-8'))
    binaries, files, links = verify_inventory(report, reviewed)
    app = Path(report['app'])
    require(app.resolve() == (ROOT / 'dist/PSPortalProxy.app').resolve() and
            Path(report['build']).resolve() == (ROOT / 'build/portalproxy').resolve(), 'Unexpected app/build inventory path')
    for path, item in files.items():
        require((app / path).resolve().is_relative_to(app.resolve()) and
                digest((app / path).read_bytes()) == item['sha256'], 'Inventoried app file changed')
        item['mode'] = (app / path).stat().st_mode & 0o777
    require(all(files[path]['mode'] & 0o100 for path in (APP_EXECUTABLE, NATIVE_EXECUTABLE)), 'Packaged executables have lost execute permission')
    validation = json.loads((ROOT / 'release/VALIDATION.json').read_text(encoding='utf-8'))
    require(report['source_commit'] == validation['source_commit'] == os.environ['GITHUB_SHA'], 'Evidence came from another commit')
    require(validation['system'] == 'darwin' and validation['architecture'] == 'arm64', 'Unreviewed platform')
    require(validation['tests_run'] >= 149 and all(validation.get(key) is True for key in (
        'exact_cpython_runtime_notices', 'actual_external_core_tested', 'native_platform_frozen_window_smoke_tested',
        'source_tk_gui_both_modes_tested', 'matching_bundled_native_discovery_tested',
        'final_macos_archive_acceptance_tested')), 'Required runtime/window acceptance is missing')
    from retain_cpython_notices import verified_supplement_files, MACOS_INSTALLED_LICENSE_SHA256, MACOS_INSTALLED_NOTICES, MACOS_COMPONENTS
    notices = ROOT / 'dist/PSPortalProxy/licenses'
    require(Path(report['companion_notice_directory']).resolve() == notices.resolve(), 'Unexpected companion notices')
    retained = notices / 'cpython-3.13.15-macos'
    source = ROOT / 'notices/cpython-3.13.15-macos'
    for path in verified_supplement_files(source, 'darwin'):
        require((retained / path.name).read_bytes() == path.read_bytes(), 'Full reviewed notice not retained: ' + path.name)
    scope = json.loads((retained / 'runtime-scope.json').read_text(encoding='utf-8'))
    require(scope['python'] == '3.13.15' and scope['platform'] == 'darwin' and
            all(scope['components'].get(key) == value for key, value in MACOS_COMPONENTS.items()), 'Wrong exact notice/component scope')
    require(scope['installed_python_license_sha256'] == MACOS_INSTALLED_LICENSE_SHA256 and
            digest((notices / 'Python-LICENSE.txt').read_bytes()) == MACOS_INSTALLED_LICENSE_SHA256, 'Installed Python license changed')
    require(report['runtime']['stdlib_components']['_lzma'].get('version') == '5.2.3', 'Actual linked liblzma version is unproven')
    for component, expected in MACOS_INSTALLED_NOTICES.items():
        require(scope['installed_component_notices'][component]['sha256'] == expected and
                digest((retained / ('installed-' + component + '-license.txt')).read_bytes()) == expected,
                'Exact installed component notice missing: ' + component)
    native = app / 'Contents/Resources/native'
    require(digest((native / 'psportal-native').read_bytes()) == validation['native_binary_sha256'] and
            digest((native / 'corresponding-source.tar.gz').read_bytes()) == validation['corresponding_source_sha256'], 'Native source/executable mismatch')
    for path in (notices / 'PyInstaller-COPYING.txt', notices / 'PSPortal-OnDemand-LICENSE.txt',
                 native / 'LICENSE', native / 'THIRD_PARTY_NOTICES.md', native / 'SOURCE.md', native / 'licenses/ENGINE-NOTICES.txt'):
        require(path.stat().st_size > 100, 'Required full notice missing: ' + str(path))
    companion = {}
    candidate_hashes = companion_candidates(report)
    for path in notices.rglob('*'):
        require(not path.is_symlink(), 'Companion notices must not contain symlinks')
        if path.is_file():
            sha = digest(path.read_bytes())
            require(candidate_hashes.get(str(path.resolve())) == sha, 'Companion notice differs from inventory')
            companion['licenses/' + path.relative_to(notices).as_posix()] = sha
    for name in ('desktop.md', 'native-acceptance.md', 'validation.md'):
        companion[name] = digest((ROOT / 'docs' / name).read_bytes())
    archives = list((ROOT / 'release').glob('PSPortalProxy-darwin-*.tar.gz'))
    require(len(archives) == 1, 'Expected one exact macOS archive')
    directories = {'PSPortalProxy.app', 'licenses'}
    for root, prefix in ((app, 'PSPortalProxy.app'), (notices, 'licenses')):
        directories.update(prefix + '/' + path.relative_to(root).as_posix() for path in root.rglob('*')
                           if path.is_dir() and not path.is_symlink())
    verify_archive(archives[0], files, links, companion, directories)
    from verify_macos_archive import archive_records
    archive_tree = archive_records(archives[0])
    archive_tree_sha256 = digest(json.dumps(archive_tree, sort_keys=True, separators=(',', ':')).encode())
    seal_path = ROOT / 'release/MACOS-BUNDLE-SEAL.json'
    acceptance_path = ROOT / 'release/MACOS-ARCHIVE-ACCEPTANCE.json'
    seal = json.loads(seal_path.read_text(encoding='utf-8'))
    acceptance = json.loads(acceptance_path.read_text(encoding='utf-8'))
    verify_final_seal(report, binaries, files, links, validation, seal, acceptance,
                      archives[0], digest(archives[0].read_bytes()), digest(seal_path.read_bytes()), archive_tree_sha256)
    result = dict(source_commit=validation['source_commit'], developer_id_signed=False, notarized=False,
        scope='Reviewed macOS arm64 CPython3.13.15/PyInstaller6.16.0 development GUI archive only',
        runtime_binaries_verified=len(binaries), archive_directories_verified=len(directories),
        runtime_review_source=reviewed['evidence_run'],
        complete_versioned_notices_retained=True, matching_native_source_retained=True,
        real_window_and_runtime_checks_passed=True, final_adhoc_seal_deep_strict_verified=True,
        nested_native_and_runtime_bytes_preserved=True, extracted_archive_launchservices_verified=True,
        bundle_seal_sha256=digest(seal_path.read_bytes()), archive_acceptance_sha256=digest(acceptance_path.read_bytes()),
        runtime_inventory_sha256=digest(args.inventory.read_bytes()),
        archive_sha256=digest(archives[0].read_bytes()), physical_portal_or_live_subscription_tested=False)
    release = ROOT / 'release'
    (release / 'MACOS-RUNTIME-REVIEW.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    outputs = sorted(path for path in release.iterdir() if path.is_file() and path.name != 'SHA256SUMS')
    require(sum(path.stat().st_size for path in outputs) < 150 * 1024 * 1024, 'macOS release exceeds size budget')
    (release / 'SHA256SUMS').write_text(''.join(digest(path.read_bytes()) + '  ' + path.name + '\n' for path in outputs), encoding='ascii')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
