"""Retain the reviewed CPython supplement without approving a platform bundle.

Only the exact reviewed platform-specific CPython releases are accepted.
Component versions and full installed notices are checked before any copy.
The separate frozen-binary origin and redistribution gate remains required.
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
MACOS_VERSION = '3.13.15'
MACOS_INSTALLED_LICENSE_SHA256 = '78b12c3a81360b357002334f0e70ea0e92eebf7a9b358805c03c48484945f3bb'
MACOS_INSTALLED_NOTICES = {
    'Tcl': 'c0a69a2bfd757361ec7e6143973b103c90409316b49e9c88db26ad6388e79f16',
    'Tk': '2cde822b93ca16ae535c954b7dfe658b4ad10df2a193628d1b358f1765e8b198',
    'CPython-components': '952ac05720d7f1dcb63589b35eb0931b1442eb250230a4ad31198eddf0ad6abc',
}
MACOS_COMPONENTS = {'openssl': [3, 0, 21], 'zlib': '1.2.12', 'libmpdec': '4.0.1',
                    'expat': 'expat_2.8.2', 'tcl': '8.6.18', 'tk_script': '8.6.18',
                    'unicode': '15.1.0', 'liblzma': '5.2.3'}
WINDOWS_INSTALLED_LICENSE_SHA256 = '62bec384df47b0328307db41455ff6ea2559e5546b394ac69148561b21703120'
WINDOWS_VCRUNTIME_SHA256 = 'd1f4225df2cd877dbf130d5668a021dce3f94118455ff5ec952061c30afc9ce7'
WINDOWS_VCRUNTIME_1_SHA256 = 'a7146c08f89fe5b04541ab507cdb59ff7b44534d4ba3c668a426c6450a03434e'
WINDOWS_COMPONENTS = {'openssl': [3, 5, 9], 'zlib': '1.3.1', 'libmpdec': '4.0.0',
                      'expat': 'expat_2.8.5', 'tcl': '8.6.15', 'tk_script': '8.6.15', 'unicode': '15.1.0'}


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def supplement_name(target_platform):
    if target_platform == 'win32':
        return 'cpython-' + VERSION
    if target_platform == 'darwin':
        return 'cpython-' + MACOS_VERSION + '-macos'
    raise ValueError('No reviewed CPython supplement for this platform')


def installed_liblzma_version():
    """Query the already-imported stdlib extension's linked version, read-only."""
    import _lzma
    import ctypes
    library = ctypes.CDLL(_lzma.__file__)
    query = library.lzma_version_string
    query.argtypes = ()
    query.restype = ctypes.c_char_p
    value = query()
    if not value or not re.fullmatch(rb'[0-9]+\.[0-9]+\.[0-9]+', value):
        raise ValueError('The installed liblzma did not expose an exact release version')
    return value.decode('ascii')


def installed_macos_notices():
    from PyInstaller.utils.hooks.tcl_tk import tcltk_info
    root = Path(sys.base_prefix).resolve()
    paths = {
        'Tcl': Path(tcltk_info.tcl_data_dir).parent / 'license.terms',
        'Tk': Path(tcltk_info.tk_data_dir).parent / 'license.terms',
        'CPython-components': root / 'Resources/English.lproj/Documentation/_sources/license.rst.txt',
    }
    if any(not path.resolve().is_relative_to(root) for path in paths.values()):
        raise ValueError('Installed macOS notices are outside the selected Python distribution')
    return paths


def openssl_release(description):
    # CPython's legacy OPENSSL_VERSION_INFO puts OpenSSL3's patch in index3,
    # not index2. Bind to the actual linked library's exact version string.
    match = re.fullmatch(r'OpenSSL ([0-9]+)\.([0-9]+)\.([0-9]+) [0-9]{1,2} '
                         r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [0-9]{4}', description)
    if not match:
        raise ValueError('Unreviewed OpenSSL version description')
    return [int(number) for number in match.groups()]


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
    result = dict(python=platform.python_version(), implementation=platform.python_implementation(),
        openssl=openssl_release(ssl.OPENSSL_VERSION), openssl_description=ssl.OPENSSL_VERSION,
        zlib=zlib.ZLIB_RUNTIME_VERSION, libmpdec=_decimal.__libmpdec_version__,
        expat=pyexpat.EXPAT_VERSION, tcl=tkinter.Tcl().eval('info patchlevel'),
        tk_script=match.group(1) if match else None, unicode=unicodedata.unidata_version)
    if sys.platform == 'darwin':
        result['liblzma'] = installed_liblzma_version()
    return result


def verified_supplement_files(source, target_platform='win32'):
    source = Path(source).resolve()
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    supplement_name(target_platform)  # Reject unaudited platforms.
    version = VERSION if target_platform == 'win32' else MACOS_VERSION
    count = 23 if target_platform == 'win32' else 21
    if manifest.get('python_version') != version or manifest.get('upstream_tag') != 'v' + version:
        raise ValueError('Notice manifest is not for the reviewed CPython release')
    records = manifest.get('files', [])
    if len(records) != count:
        raise ValueError(f'The reviewed supplement requires all {count} notice files')
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
        source_url = record.get('source_url', '')
        prefixes = ['https://raw.githubusercontent.com/python/cpython/v' + version + '/']
        exact = {'https://raw.githubusercontent.com/spdx/license-list-data/v3.27.0/text/CC0-1.0.txt'}
        if target_platform == 'win32':
            prefixes += ['https://raw.githubusercontent.com/python/cpython-source-deps/' + tag + '/'
                for tag in ('bzip2-1.0.8', 'libffi-3.4.4', 'mpdecimal-4.0.0',
                            'openssl-3.5.9', 'xz-5.2.5', 'zlib-1.3.1')]
        else:
            prefixes += ['https://raw.githubusercontent.com/openssl/openssl/openssl-3.0.21/',
                         'https://raw.githubusercontent.com/tukaani-project/xz/v5.2.3/']
            exact.add('https://www.bytereef.org/software/mpdecimal/releases/mpdecimal-4.0.1.tar.gz')
        if source_url not in exact and not source_url.startswith(tuple(prefixes)):
            raise ValueError('Unreviewed notice source: ' + name)
        if '?' in source_url or '#' in source_url or '/..' in source_url:
            raise ValueError('Invalid notice source URL: ' + name)
        files.append(path)
    expected = names | {'manifest.json', 'README.txt'}
    if {path.name for path in source.iterdir()} != expected:
        raise ValueError('The supplement contains unmanifested or missing files')
    if any((source / name).is_symlink() or not (source / name).is_file() for name in ('manifest.json', 'README.txt')):
        raise ValueError('Supplement metadata must be ordinary files')
    return files + [source / 'manifest.json', source / 'README.txt']


def retain_supplement(source, destination, installed_license, *, target_platform=None,
                      runtime=None, vcruntime_origin=None, bundled_vcruntime=None, installed_notices=None):
    target_platform = sys.platform if target_platform is None else target_platform
    runtime = installed_components() if runtime is None else runtime
    if target_platform not in ('win32', 'darwin'):
        raise ValueError('This supplement gate is for Windows/macOS; Linux uses its installed-runtime audit')
    version = VERSION if target_platform == 'win32' else MACOS_VERSION
    if runtime.get('python') != version or runtime.get('implementation') != 'CPython':
        raise ValueError('Notice review currently requires exact CPython ' + version + ' on ' + target_platform)
    files = verified_supplement_files(source, target_platform)
    installed_license = Path(installed_license)
    if not installed_license.is_file():
        raise ValueError('The complete installed Python license is required')
    additional = {}
    report = dict(python=version, platform=target_platform, components=runtime,
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
        extra_origin = Path(vcruntime_origin).with_name('VCRUNTIME140_1.dll')
        extra_bundled = Path(bundled_vcruntime).with_name('VCRUNTIME140_1.dll')
        if any(not path.is_file() or sha256(path) != WINDOWS_VCRUNTIME_1_SHA256
               for path in (extra_origin, extra_bundled)):
            raise ValueError('Microsoft VCRUNTIME140_1.dll does not match the audited Python distribution')
        report['microsoft_runtime_additional'] = dict(
            component='VCRUNTIME140_1.dll',
            classification='Microsoft Distributable Code, not PSF-licensed',
            origin=str(extra_origin), sha256=WINDOWS_VCRUNTIME_1_SHA256,
            notice='Full Additional Conditions for this Windows binary build in ../Python-LICENSE.txt',
            scope='Unmodified runtime supplied with the audited Windows Python distribution only')
    else:
        for name, expected in MACOS_COMPONENTS.items():
            if runtime.get(name) != expected:
                raise ValueError('Installed macOS component needs a new notice review: ' + name)
        if report['installed_python_license_sha256'] != MACOS_INSTALLED_LICENSE_SHA256:
            raise ValueError('Installed macOS Python license differs from the audited distribution')
        installed_notices = installed_macos_notices() if installed_notices is None else installed_notices
        if set(installed_notices) != set(MACOS_INSTALLED_NOTICES):
            raise ValueError('Exact installed macOS Python/Tcl/Tk component notices are required')
        report['installed_component_notices'] = {}
        for component, expected in MACOS_INSTALLED_NOTICES.items():
            path = Path(installed_notices[component])
            if not path.is_file() or sha256(path) != expected:
                raise ValueError('Installed macOS notice differs from reviewed bytes: ' + component)
            name = 'installed-' + component + '-license.txt'
            additional[name] = path
            report['installed_component_notices'][component] = dict(origin=str(path), sha256=expected, retained=name)
        report['system_library_scope'] = 'zlib, bzip2 and libffi are linked macOS system libraries; binary inventory must prove they are not redistributed'
        report['external_library_notice_review'] = 'Exact observed versions checked; frozen binary origins/transformation proof remains required'
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Refusing to overwrite previously retained supplemental evidence')
    destination.mkdir(parents=True)
    for path in files:
        shutil.copy2(path, destination / path.name)
    for name, path in additional.items():
        shutil.copy2(path, destination / name)
    (destination / 'runtime-scope.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report
