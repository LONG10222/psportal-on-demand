#!/usr/bin/env python3
"""Verify an extracted final macOS archive and launch its app via LaunchServices.

No permissions, Gatekeeper bypasses, security settings, or identity signing are
requested. A failure blocks release. Evidence is written outside the app.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import stat
import subprocess
import sys
import tarfile

try:
    from .macos_bundle_finalize import macho_files, sha256
except ImportError:
    from macos_bundle_finalize import macho_files, sha256


def archive_records(archive):
    records = {}
    with tarfile.open(archive, 'r:gz') as stream:
        for item in stream.getmembers():
            path = PurePosixPath(item.name)
            if (not item.name or str(path) == '.' or path.is_absolute() or '..' in path.parts or
                    '\\' in item.name or str(path) != item.name.rstrip('/') or
                    item.name.rstrip('/') in records):
                raise ValueError('Unsafe or duplicate archive member: ' + item.name)
            if item.mode & 0o6000:
                raise ValueError('Unexpected setuid/setgid archive member')
            name = item.name.rstrip('/')
            if item.isdir():
                record = dict(type='directory', mode=item.mode)
            elif item.isfile():
                with stream.extractfile(item) as source:
                    digest = hashlib.file_digest(source, 'sha256').hexdigest()
                record = dict(type='file', mode=item.mode, size=item.size, sha256=digest)
            elif item.issym():
                if not item.linkname or '\\' in item.linkname or item.linkname.startswith('/'):
                    raise ValueError('Unsafe archive symlink: ' + name)
                target = posixpath.normpath(posixpath.join(str(path.parent), item.linkname))
                if target == '..' or target.startswith('../'):
                    raise ValueError('Archive symlink escapes extraction root: ' + name)
                record = dict(type='symlink', mode=item.mode, target=item.linkname)
            else:
                raise ValueError('Unexpected hardlink or special archive member: ' + name)
            records[name] = record
    for name, record in records.items():
        for parent in PurePosixPath(name).parents:
            if str(parent) == '.':
                continue
            if str(parent) not in records or records[str(parent)]['type'] != 'directory':
                raise ValueError('Archive parent is not an explicit real directory: ' + name)
        if record['type'] == 'symlink':
            target = posixpath.normpath(posixpath.join(str(PurePosixPath(name).parent), record['target']))
            seen = {name}
            while True:
                # Resolve symlink components as well as terminal aliases.
                parts = PurePosixPath(target).parts
                replaced = False
                for index in range(1, len(parts) + 1):
                    prefix = '/'.join(parts[:index])
                    entry = records.get(prefix)
                    if entry and entry['type'] == 'symlink':
                        if prefix in seen:
                            raise ValueError('Archive contains a symlink cycle')
                        seen.add(prefix)
                        target = posixpath.normpath(posixpath.join(
                            str(PurePosixPath(prefix).parent), entry['target'], *parts[index:]))
                        if target == '..' or target.startswith('../') or target.startswith('/'):
                            raise ValueError('Archive alias escapes extraction root')
                        replaced = True
                        break
                if not replaced:
                    break
            if target not in records:
                raise ValueError('Archive contains a dangling alias: ' + name)
    return records


def verify_extracted(root, records):
    root = Path(root).resolve()
    actual = {path.relative_to(root).as_posix(): path for path in root.rglob('*')}
    if set(actual) != set(records):
        raise ValueError('Extracted archive member set changed')
    for name, expected in records.items():
        path = actual[name]
        metadata = path.lstat()
        kind = ('symlink' if stat.S_ISLNK(metadata.st_mode) else
                'file' if stat.S_ISREG(metadata.st_mode) else
                'directory' if stat.S_ISDIR(metadata.st_mode) else 'special')
        if kind != expected['type'] or stat.S_IMODE(metadata.st_mode) != expected['mode']:
            raise ValueError('Extracted archive type/mode changed: ' + name)
        if kind == 'file' and (metadata.st_size != expected['size'] or sha256(path) != expected['sha256']):
            raise ValueError('Extracted archive file bytes changed: ' + name)
        if kind == 'symlink' and (os.readlink(path) != expected['target'] or
                                  not path.resolve(strict=True).is_relative_to(root)):
            raise ValueError('Extracted archive alias changed or escaped: ' + name)
    return hashlib.sha256(json.dumps(records, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def verify_archive(archive, output, evidence, bundle_seal):
    if sys.platform != 'darwin':
        raise RuntimeError('Archive signature and LaunchServices acceptance require macOS')
    archive, output, evidence, bundle_seal = map(lambda value: Path(value).absolute(),
                                               (archive, output, evidence, bundle_seal))
    if output.is_symlink() or (output.exists() and any(output.iterdir())):
        raise ValueError('Archive verification requires a new or empty real extraction directory')
    if evidence.is_relative_to(output):
        raise ValueError('Evidence must remain outside the extracted archive')
    report = dict(schema_version=1, passed=False, source_commit=os.environ.get('PSPORTAL_SOURCE_COMMIT', os.environ.get('GITHUB_SHA', '')),
                  archive=str(archive), archive_sha256=sha256(archive),
                  bundle_seal_sha256=sha256(bundle_seal), commands=[],
                  extracted_deep_strict_verified=False, launchservices_window_verified=False)

    def command(argv, env=None):
        result = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=300,
                                cwd=Path(__file__).resolve().parents[1])
        report['commands'].append(dict(argv=list(map(str, argv)), returncode=result.returncode,
                                       stdout=result.stdout, stderr=result.stderr))
        if result.returncode:
            raise RuntimeError('Extracted archive acceptance failed: ' + ' '.join(map(str, argv)) + '\n' + result.stderr)
        return result

    try:
        seal = json.loads(bundle_seal.read_text(encoding='utf-8'))
        if (seal.get('passed') is not True or seal.get('final_deep_strict_verified') is not True or
                seal.get('nested_strict_verified') is not True or
                seal.get('source_commit') != report['source_commit']):
            raise ValueError('Missing successful matching final bundle seal evidence')
        records = archive_records(archive)
        output.mkdir(parents=True, exist_ok=True)
        command(['/usr/bin/tar', '-xzpf', str(archive), '-C', str(output)])
        report['extracted_tree_sha256'] = verify_extracted(output, records)
        report['member_counts'] = {kind: sum(item['type'] == kind for item in records.values())
                                   for kind in ('file', 'directory', 'symlink')}
        app = output / 'PSPortalProxy.app'
        report['app'] = str(app)
        after = macho_files(app)
        main = 'Contents/MacOS/PSPortalProxy'
        nested = {key: digest for key, digest in after.items() if key != main}
        if (nested != seal.get('nested_macho_before') or nested != seal.get('nested_macho_after') or
                after.get(main) != seal.get('main_sha256_after') or
                sha256(app / 'Contents/_CodeSignature/CodeResources') != seal.get('code_resources_sha256')):
            raise ValueError('Extracted bundle differs from the strictly verified final seal')
        report['nested_macho_sha256'] = nested
        report['main_sha256'] = after[main]
        report['code_resources_sha256'] = seal['code_resources_sha256']
        command(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', str(app)])
        report['extracted_deep_strict_verified'] = True
        environment = dict(os.environ, PSPORTAL_MACOS_APP_TEST='1', PSPORTAL_MACOS_APP=str(app))
        acceptance = command([sys.executable, '-m', 'unittest', 'discover', '-s',
                 str(Path(__file__).resolve().parents[1] / 'tests'), '-p', 'test_macos_launchservices.py', '-v'],
                env=environment)
        marker = 'PSPORTAL_LAUNCHSERVICES_RESULT='
        receipts = [json.loads(line[len(marker):]) for line in acceptance.stdout.splitlines() if line.startswith(marker)]
        expected = dict(app=str(app.resolve()), visible=True, normal_quit=True, no_listener=True, open_exitcode=0)
        if receipts != [expected]:
            raise ValueError('Missing exact executed LaunchServices acceptance receipt')
        report['launchservices_receipt'] = receipts[0]
        report['launchservices_window_verified'] = True
        # Launch/close must not mutate sealed app bytes or companion notices.
        if verify_extracted(output, records) != report['extracted_tree_sha256']:
            raise ValueError('Extracted tree changed after LaunchServices acceptance')
        command(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', str(app)])
        report['passed'] = True
        return report
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--bundle-seal', type=Path)
    args = parser.parse_args()
    verify_archive(args.archive, args.output, args.evidence,
                   args.bundle_seal or args.archive.parent / 'MACOS-BUNDLE-SEAL.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
