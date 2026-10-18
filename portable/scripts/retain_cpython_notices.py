"""Retain the reviewed CPython supplement without approving a platform bundle.

Only the exact reviewed CPython release is accepted. Windows has additional
component-version and original-installer checks. macOS external libraries still
require their own binary inventory and notice review; copying extra candidate
notices is not evidence that those versions were linked into the interpreter.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import sys


VERSION = '3.13.16'
WINDOWS_INSTALLED_LICENSE_SHA256 = '62bec384df47b0328307db41455ff6ea2559e5546b394ac69148561b21703120'
WINDOWS_VCRUNTIME_SHA256 = 'd1f4225df2cd877dbf130d5668a021dce3f94118455ff5ec952061c30afc9ce7'
WINDOWS_COMPONENTS = {'openssl': [3, 5, 9], 'zlib': '1.3.1', 'libmpdec': '4.0.0',
                      'expat': 'expat_2.8.5', 'tcl': '8.6.15', 'tk_script': '8.6.15', 'unicode': '15.1.0'}


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def installed_components():
    import _decimal
    import pyexpat
    import ssl
    import tkinter
    import zlib
    import unicodedata
    from PyInstaller.utils.hooks.tcl_tk import tcltk_info
    tk_script = Path(tcltk_info.tk_data_dir) / 'tk.tcl'
    match = re.search(r'package\s+require\s+-exact\s+Tk\s+([0-9.]+)', tk_script.read_text(encoding='utf-8'))
    return dict(python=platform.python_version(), implementation=platform.python_implementation(),
        openssl=list(ssl.OPENSSL_VERSION_INFO[:3]), openssl_description=ssl.OPENSSL_VERSION,
        zlib=zlib.ZLIB_RUNTIME_VERSION, libmpdec=_decimal.__libmpdec_version__,
        expat=pyexpat.EXPAT_VERSION, tcl=tkinter.Tcl().eval('info patchlevel'),
        tk_script=match.group(1) if match else None, unicode=unicodedata.unidata_version)


def verified_supplement_files(source):
    source = Path(source).resolve()
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('python_version') != VERSION or manifest.get('upstream_tag') != 'v' + VERSION:
        raise ValueError('Notice manifest is not for the reviewed CPython release')
    records = manifest.get('files', [])
    if len(records) != 23:
        raise ValueError('The reviewed supplement requires all 23 notice files')
    files, names = [], set()
    for record in records:
        name = record.get('file', '')
        if not name or name in ('.', '..') or '/' in name or '\\' in name or name in names:
            raise ValueError('Invalid or duplicate notice filename')
        names.add(name)
        path = source / name
        if path.is_symlink() or not path.is_file() or path.resolve().parent != source:
            raise ValueError('Notice is missing or escapes its reviewed directory: ' + name)
        if not re.fullmatch('[0-9a-f]{64}', record.get('sha256', '')) or sha256(path) != record['sha256']:
            raise ValueError('Notice content hash mismatch: ' + name)
        if not re.fullmatch('[0-9a-f]{64}', record.get('source_sha256', '')):
            raise ValueError('Missing upstream source hash: ' + name)
        if not record.get('source_url', '').startswith((
                'https://raw.githubusercontent.com/python/cpython/v3.13.16/',
                'https://raw.githubusercontent.com/python/cpython-source-deps/bzip2-1.0.8/',
                'https://raw.githubusercontent.com/python/cpython-source-deps/libffi-3.4.4/',
                'https://raw.githubusercontent.com/python/cpython-source-deps/mpdecimal-4.0.0/',
                'https://raw.githubusercontent.com/python/cpython-source-deps/openssl-3.5.9/',
                'https://raw.githubusercontent.com/python/cpython-source-deps/xz-5.2.5/',
                'https://raw.githubusercontent.com/python/cpython-source-deps/zlib-1.3.1/',
                'https://raw.githubusercontent.com/spdx/license-list-data/v3.27.0/text/CC0-1.0.txt')):
            raise ValueError('Unreviewed notice source: ' + name)
        files.append(path)
    expected = names | {'manifest.json', 'README.txt'}
    if {path.name for path in source.iterdir()} != expected:
        raise ValueError('The supplement contains unmanifested or missing files')
    if any((source / name).is_symlink() or not (source / name).is_file() for name in ('manifest.json', 'README.txt')):
        raise ValueError('Supplement metadata must be ordinary files')
    return files + [source / 'manifest.json', source / 'README.txt']


def retain_supplement(source, destination, installed_license, *, target_platform=None,
                      runtime=None, vcruntime_origin=None, bundled_vcruntime=None):
    target_platform = sys.platform if target_platform is None else target_platform
    runtime = installed_components() if runtime is None else runtime
    if target_platform not in ('win32', 'darwin'):
        raise ValueError('This supplement gate is for Windows/macOS; Linux uses its installed-runtime audit')
    if runtime.get('python') != VERSION or runtime.get('implementation') != 'CPython':
        raise ValueError('Windows/macOS notice review currently requires exact CPython ' + VERSION)
    files = verified_supplement_files(source)
    installed_license = Path(installed_license)
    if not installed_license.is_file():
        raise ValueError('The complete installed Python license is required')
    report = dict(python=VERSION, platform=target_platform, components=runtime,
        installed_python_license_sha256=sha256(installed_license),
        supplemental_manifest_sha256=sha256(Path(source) / 'manifest.json'),
        platform_dependency_coverage_verified=False, distribution_approved=False)
    if target_platform == 'win32':
        for name, expected in WINDOWS_COMPONENTS.items():
            if runtime.get(name) != expected:
                raise ValueError('Installed Windows component needs a new notice review: ' + name)
        if report['installed_python_license_sha256'] != WINDOWS_INSTALLED_LICENSE_SHA256:
            raise ValueError('Installed Windows Python license differs from the audited distribution')
        if not vcruntime_origin or not bundled_vcruntime:
            raise ValueError('Original and bundled Microsoft runtime files must be identified')
        if any(sha256(path) != WINDOWS_VCRUNTIME_SHA256 for path in (vcruntime_origin, bundled_vcruntime)):
            raise ValueError('Microsoft runtime does not match the audited unmodified Python distribution')
        report['microsoft_runtime'] = dict(component='VCRUNTIME140.dll',
            classification='Microsoft Distributable Code, not PSF-licensed',
            origin=str(vcruntime_origin), sha256=WINDOWS_VCRUNTIME_SHA256,
            notice='Full Additional Conditions for this Windows binary build in ../Python-LICENSE.txt',
            scope='Unmodified runtime supplied with the audited Windows Python distribution only')
    else:
        report['external_library_notice_review'] = 'Required separately for actual macOS-linked versions and origins'
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Refusing to overwrite previously retained supplemental evidence')
    destination.mkdir(parents=True)
    for path in files:
        shutil.copy2(path, destination / path.name)
    (destination / 'runtime-scope.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report
