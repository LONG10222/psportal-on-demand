#!/usr/bin/env python3
"""Finalize the native layout, then ad-hoc seal only the outer macOS bundle.

No signing identity, keychain access, entitlement, omission rule or deep signing
is used. Every nested Mach-O must retain its exact original bytes. This is an
integrity check, not Developer ID signing, notarization or Gatekeeper approval.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

MACHO_MAGICS = {bytes.fromhex(value) for value in (
    'feedface', 'cefaedfe', 'feedfacf', 'cffaedfe', 'cafebabe', 'bebafeca',
    'cafebabf', 'bfbafeca')}


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def macho_files(app):
    result = {}
    for path in sorted(Path(app).rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('rb') as stream:
            magic = stream.read(4)
        if magic in MACHO_MAGICS:
            result[path.relative_to(app).as_posix()] = sha256(path)
    return result


def arrange_native(app, expected_sha256):
    """Move code without changing it; keep discovery and source pairing aliases."""
    app = Path(app)
    resources = app / 'Contents/Resources/native'
    staged = resources / 'psportal-native'
    target = app / 'Contents/MacOS/psportal-native'
    compatibility = app / 'Contents/MacOS/native'
    if expected_sha256 is None:
        if resources.exists() or target.exists() or compatibility.exists():
            raise ValueError('Unexpected native content in a build without native evidence')
        return None
    if not staged.is_file() or staged.is_symlink() or sha256(staged) != expected_sha256:
        raise ValueError('Staged native helper does not match the original native release')
    if target.exists() or target.is_symlink() or compatibility.exists() or compatibility.is_symlink():
        raise ValueError('Native destination/compatibility path already exists')
    if not (resources / 'corresponding-source.tar.gz').is_file():
        raise ValueError('Native corresponding source is missing')
    staged.rename(target)
    staged.symlink_to('../../MacOS/psportal-native')
    compatibility.symlink_to('../Resources/native', target_is_directory=True)
    if staged.resolve() != target.resolve() or compatibility.resolve() != resources.resolve():
        raise ValueError('Native compatibility aliases do not resolve to their intended targets')
    if sha256(target) != expected_sha256:
        raise ValueError('Native helper bytes changed during layout finalization')
    return target


def finalize_bundle(app, evidence, expected_native_sha256=None):
    if sys.platform != 'darwin':
        raise RuntimeError('Actual macOS codesign verification is required')
    app, evidence = Path(app).absolute(), Path(evidence).absolute()
    if app.is_symlink() or not (app / 'Contents/MacOS/PSPortalProxy').is_file():
        raise ValueError('Expected the actual assembled PSPortalProxy.app bundle')
    if evidence.is_relative_to(app):
        raise ValueError('Seal evidence must remain outside the sealed app')
    report = dict(schema_version=1, source_commit=os.environ.get('PSPORTAL_SOURCE_COMMIT', os.environ.get('GITHUB_SHA', '')),
                  app=str(app), passed=False, final_deep_strict_verified=False,
                  nested_strict_verified=False,
                  signing_identity='ad-hoc', developer_id=False, notarized=False,
                  deep_signing_used=False, commands=[])

    def command(arguments, required=True):
        completed = subprocess.run(arguments, capture_output=True, text=True, timeout=180)
        report['commands'].append(dict(argv=list(map(str, arguments)),
            returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr))
        if required and completed.returncode:
            raise RuntimeError('macOS bundle verification/signing failed: ' +
                               ' '.join(map(str, arguments)) + '\n' + completed.stderr)
        return completed

    try:
        # A failed preseal verification is evidence of the original assembly
        # gap, never permission to weaken the mandatory final verification.
        report['preseal_verified'] = command(
            ['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', str(app)],
            required=False).returncode == 0
        native = arrange_native(app, expected_native_sha256)
        before = macho_files(app)
        main = 'Contents/MacOS/PSPortalProxy'
        if main not in before:
            raise ValueError('The outer executable is not Mach-O')
        if native:
            command(['/usr/bin/codesign', '--verify', '--strict', '--verbose=2', str(native)])
        # Outer-only signing updates the app resource envelope and main code
        # signature. In particular, never use --deep or re-sign nested code.
        command(['/usr/bin/codesign', '--force', '--sign', '-', '--timestamp=none', str(app)])
        after = macho_files(app)
        if set(before) != set(after):
            raise ValueError('The Mach-O file set changed while sealing the app')
        for relative, digest in before.items():
            if relative != main and after[relative] != digest:
                raise ValueError('Outer signing changed nested code: ' + relative)
        report['nested_macho_before'] = {key: before[key] for key in sorted(before) if key != main}
        report['nested_macho_after'] = {key: after[key] for key in sorted(after) if key != main}
        report['main_sha256_before'] = before[main]
        report['main_sha256_after'] = after[main]
        command(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', str(app)])
        report['final_deep_strict_verified'] = True
        for relative in sorted(after):
            command(['/usr/bin/codesign', '--verify', '--strict', '--verbose=2', str(app / relative)])
        report['nested_strict_verified'] = True
        envelope = app / 'Contents/_CodeSignature/CodeResources'
        report['code_resources_sha256'] = sha256(envelope)
        if native:
            seal = plistlib.loads(envelope.read_bytes()).get('files2', {})
            if 'MacOS/psportal-native' not in seal:
                raise ValueError('The final resource envelope does not seal the native helper')
            report['native_sha256'] = sha256(native)
            report['native_resource_envelope_entry'] = 'MacOS/psportal-native'
            report['native_aliases'] = {
                'Contents/MacOS/native': os.readlink(app / 'Contents/MacOS/native'),
                'Contents/Resources/native/psportal-native': os.readlink(app / 'Contents/Resources/native/psportal-native')}
            if report['native_sha256'] != expected_native_sha256:
                raise ValueError('The sealed native helper differs from the original release')
        report['passed'] = True
        return report
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
