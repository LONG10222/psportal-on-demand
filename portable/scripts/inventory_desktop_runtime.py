#!/usr/bin/env python3
"""Collect exact frozen-runtime evidence without changing or approving a bundle.

Run with the same Python/PyInstaller installation used to build the app. The
report retains original TOCs and full installed license candidates separately
from the app. Unknown/mismatched binary origins and missing Python/Tcl/Tk license
candidates cause a nonzero exit AFTER evidence is written. In particular, macOS
install-name/signature changes are reported as unverified, never assumed safe.
This is a diagnostic inventory, not a license-compatibility/distribution audit.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
from functools import lru_cache
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import sysconfig


ROOT = Path(__file__).resolve().parents[1]
TYPECODES = {'BINARY', 'EXTENSION', 'EXECUTABLE', 'DATA', 'SYMLINK',
             'PYMODULE', 'PYMODULE-1', 'PYMODULE-2', 'PYSOURCE', 'PYZ', 'PKG'}
BINARY_TYPES = {'BINARY', 'EXTENSION', 'EXECUTABLE'}
LICENSE_NAME = re.compile(r'(^|[._-])(licen[cs]e|copying|copyright|notice)s?($|[._-])', re.I)
API_SET_NAME = re.compile(r'api-ms-win-[a-z0-9-]+\.dll', re.I)
MACHO = {b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
         b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
         b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def binary_format(path):
    with path.open('rb') as stream:
        magic = stream.read(4)
    if magic == b'\x7fELF':
        return 'ELF'
    if magic[:2] == b'MZ':
        return 'PE'
    if magic in MACHO:
        return 'Mach-O'
    return None


def toc_entries(value):
    """Read data-only PyInstaller TOCs, never execute their representation."""
    if (isinstance(value, (list, tuple)) and len(value) == 3
            and all(isinstance(item, str) for item in value)
            and value[2] in TYPECODES):
        yield tuple(value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from toc_entries(item)


def destination_keys(relative):
    relative = relative.replace('\\', '/')
    keys = {relative}
    for prefix in ('_internal/', 'Contents/Frameworks/', 'Contents/Resources/', 'Contents/MacOS/'):
        if relative.startswith(prefix):
            keys.add(relative[len(prefix):])
    # PyInstaller 6.16 macOS BUNDLE replaces dots in code-containing directory
    # names for codesign, while the original TOC retains their source spelling.
    for key in list(keys):
        parts = key.split('/')
        keys.add('/'.join([part.replace('__dot__', '.') for part in parts[:-1]] + parts[-1:]))
    return keys


def component(path):
    text = str(path).replace('\\', '/').lower()
    if re.search(r'(^|/)(tcl[^/]*|_tcl_data)(/|$)', text):
        return 'Tcl'
    if re.search(r'(^|/)(tk\d[^/]*|tk\.framework|_tk_data)(/|$)', text):
        return 'Tk'
    return 'other-runtime'


def is_packaged_notice(relative):
    parts = str(relative).replace('\\', '/').split('/')
    return any(part.lower() in ('license', 'licenses') for part in parts[:-1]) or bool(LICENSE_NAME.search(parts[-1]))


def companion_notice_directory(app, target_platform):
    # build.py archives this known companion directory beside the macOS .app.
    return app.with_suffix('') / 'licenses' if target_platform == 'darwin' and app.suffix == '.app' else None


def pe_version_metadata(pe):
    """Keep unedited version-resource strings as provenance hints, not licenses."""
    result = {'string_tables': []}
    for fixed in getattr(pe, 'VS_FIXEDFILEINFO', ()):
        for label, high, low in (('file_version', fixed.FileVersionMS, fixed.FileVersionLS),
                                 ('product_version', fixed.ProductVersionMS, fixed.ProductVersionLS)):
            result[label] = '.'.join(str(number) for number in (high >> 16, high & 65535, low >> 16, low & 65535))
    def decode(value):
        return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else str(value)
    for group in getattr(pe, 'FileInfo', ()):
        for info in group:
            for table in getattr(info, 'StringTable', ()):
                result['string_tables'].append(dict(language=decode(table.LangID),
                    entries={decode(key): decode(value) for key, value in table.entries.items()}))
    return result


@lru_cache(maxsize=256)
def windows_api_set_resolution(name):
    """Prove an unresolved API-set contract maps to a real System32 module.

API-set names are virtual contracts, not necessarily files. A successful
system-only loader resolution is evidence; a matching filename alone is not.
No arbitrary library name/path is loaded and every acquired handle is freed.
"""
    if sys.platform != 'win32' or not API_SET_NAME.fullmatch(name):
        return None
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.GetSystemDirectoryW.argtypes = (wintypes.LPWSTR, wintypes.UINT)
    kernel32.GetSystemDirectoryW.restype = wintypes.UINT
    kernel32.LoadLibraryExW.argtypes = (wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD)
    kernel32.LoadLibraryExW.restype = wintypes.HMODULE
    kernel32.GetModuleFileNameW.argtypes = (wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD)
    kernel32.GetModuleFileNameW.restype = wintypes.DWORD
    kernel32.FreeLibrary.argtypes = (wintypes.HMODULE,)
    kernel32.FreeLibrary.restype = wintypes.BOOL
    buffer = ctypes.create_unicode_buffer(32768)
    count = kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < count < len(buffer):
        raise OSError('Cannot determine Windows system directory')
    system = Path(buffer.value).resolve(strict=True)
    handle = kernel32.LoadLibraryExW(name, None, 0x00000800)  # LOAD_LIBRARY_SEARCH_SYSTEM32
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        count = kernel32.GetModuleFileNameW(handle, buffer, len(buffer))
        if not 0 < count < len(buffer):
            raise OSError('Cannot identify API-set host module')
        host = Path(buffer.value).resolve(strict=True)
        if host.parent != system:
            raise OSError('API-set host was not resolved within System32')
        return dict(resolved=str(host), resolution_method='windows-api-set-system-loader',
                    system_sha256=digest(host))
    finally:
        kernel32.FreeLibrary(handle)


def annotate_import(name, resolved):
    item = dict(name=name, resolved=resolved)
    if sys.platform == 'win32' and API_SET_NAME.fullmatch(name):
        item.update(static_resolved=resolved, resolved=None)
        try:
            proof = windows_api_set_resolution(name)
            if proof:
                item.update(proof)
        except (OSError, ValueError) as error:
            item['api_set_resolution_error'] = str(error)
    return item


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    default_app = ROOT / 'dist' / ('PSPortalProxy.app' if sys.platform == 'darwin' else 'PSPortalProxy')
    parser.add_argument('--app', type=Path, default=default_app)
    parser.add_argument('--build', type=Path, default=ROOT / 'build' / 'portalproxy')
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime-inventory')
    parser.add_argument('--native-origin', type=Path,
                        help='Original reviewed native binary before copying it into the app')
    args = parser.parse_args(argv)
    app, build, output = (path.resolve() for path in (args.app, args.build, args.output))
    if not app.is_dir() or not build.is_dir():
        parser.error('The frozen app and its matching PyInstaller build directory must exist')
    if output.is_relative_to(app) or output.is_relative_to(build):
        parser.error('Evidence output must be outside the app and its build directory')
    # Refuse to mix two builds or silently replace an earlier diagnostic.
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error('Choose an empty evidence output directory')
    output.mkdir(parents=True, exist_ok=True)
    issues, entries, tocs, build_python = [], {}, [], None
    for path in sorted(build.glob('*.toc')):
        if path.stat().st_size > 64 * 1024 * 1024:
            issues.append('Oversized TOC: ' + str(path))
            continue
        target = output / 'build-tocs' / path.name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(path, target)
        tocs.append(dict(path=str(path), sha256=digest(path), retained=target.relative_to(output).as_posix()))
        try:
            parsed = ast.literal_eval(path.read_text(encoding='utf-8'))
        except (ValueError, SyntaxError) as error:
            issues.append(f'Cannot parse TOC {path.name}: {error}')
            continue
        if path.name == 'Analysis-00.toc' and isinstance(parsed, tuple) and len(parsed) > 12:
            if isinstance(parsed[12], str):
                build_python = parsed[12]
        for destination, origin, kind in toc_entries(parsed):
            key = destination.replace('\\', '/')
            entries.setdefault((key, origin, kind), set()).add(path.name)
    if not entries:
        issues.append('No PyInstaller dependency records found')
    if build_python != sys.version:
        issues.append('The Analysis TOC Python version does not match this inventory interpreter')

    runtime = dict(python=sys.version, executable=sys.executable, base_prefix=sys.base_prefix,
                   prefix=sys.prefix, stdlib=sysconfig.get_path('stdlib'), platform=platform.platform(),
                   build_python=build_python)
    runtime['stdlib_components'] = {}
    for module_name, version_attribute in (
            ('ssl', 'OPENSSL_VERSION'), ('zlib', 'ZLIB_RUNTIME_VERSION'),
            ('pyexpat', 'EXPAT_VERSION'), ('_decimal', '__libmpdec_version__'),
            ('unicodedata', 'unidata_version'), ('_bz2', None), ('_lzma', None)):
        try:
            module = importlib.import_module(module_name)
            metadata = dict(version=getattr(module, version_attribute, None) if version_attribute else None)
            source = getattr(module, '__file__', None)
            if source and Path(source).is_file():
                metadata.update(source=source, sha256=digest(Path(source)))
            if module_name == '_lzma' and sys.platform == 'darwin':
                try:
                    if __package__:
                        from .retain_cpython_notices import installed_liblzma_version
                    else:
                        from retain_cpython_notices import installed_liblzma_version
                    metadata['version'] = installed_liblzma_version()
                    metadata['version_evidence'] = 'lzma_version_string exported by installed stdlib extension'
                except (AttributeError, OSError, ValueError) as error:
                    metadata['version_unverified'] = str(error)
            runtime['stdlib_components'][module_name] = metadata
        except ImportError as error:
            runtime['stdlib_components'][module_name] = dict(unavailable=str(error))
    # Each search directory is inspected for nearby notices, without scanning
    # home directories or treating repository-supplied terms as installed ones.
    notice_dirs = {}
    def add_notice_dir(path, label, location='build-origin'):
        if path is not None:
            metadata = notice_dirs.setdefault(Path(path).resolve(), dict(components=set(), locations=set()))
            metadata['components'].add(label)
            metadata['locations'].add(location)
    add_notice_dir(Path(sys.base_prefix), 'Python', 'installed')
    add_notice_dir(Path(sysconfig.get_path('stdlib')), 'Python', 'installed')
    try:
        from PyInstaller.utils.hooks.tcl_tk import tcltk_info
        runtime['pyinstaller'] = importlib.metadata.version('pyinstaller')
        runtime['tcl_tk'] = {key: getattr(tcltk_info, key, None) for key in (
            'available', 'tcl_version', 'tk_version', 'tcl_data_dir', 'tk_data_dir',
            'tcl_shared_library', 'tk_shared_library', 'tkinter_extension_file',
            'is_macos_system_framework')}
        for label, key in (('Tcl', 'tcl_data_dir'), ('Tk', 'tk_data_dir')):
            directory = runtime['tcl_tk'][key]
            if directory:
                add_notice_dir(directory, label, 'installed')
                add_notice_dir(Path(directory).parent, label, 'installed')
        import tkinter
        runtime['tcl_patchlevel'] = tkinter.Tcl().eval('info patchlevel')
        tk_dir = runtime['tcl_tk']['tk_data_dir']
        if tk_dir and (Path(tk_dir) / 'tk.tcl').is_file():
            script = Path(tk_dir) / 'tk.tcl'
            match = re.search(r'package\s+require\s+-exact\s+Tk\s+([0-9.]+)', script.read_text(encoding='utf-8'))
            runtime['tk_script_patchlevel'] = match.group(1) if match else None
            runtime['tk_init_script'] = dict(path=str(script), sha256=digest(script))
    except Exception as error:
        issues.append('Installed Tcl/Tk metadata unavailable: ' + str(error))

    origins, by_destination = [], {}
    for (destination, origin, kind), names in sorted(entries.items()):
        source = Path(origin)
        record = dict(destination=destination, source=origin, type=kind, tocs=sorted(names))
        if source.is_file():
            record.update(sha256=digest(source), size=source.stat().st_size)
            label = component(source)
            add_notice_dir(source.parent, label)
            add_notice_dir(source.parent.parent, label)
        else:
            record['source_exists'] = False
        origins.append(record)
        if kind in BINARY_TYPES:
            by_destination.setdefault(destination, []).append(record)
    native_origins = ([args.native_origin.resolve()] if args.native_origin else
                      sorted((ROOT.parent / 'native' / 'dist').glob('psportal-*/psportal*')))
    native_origins = [path for path in native_origins if path.is_file() and binary_format(path)]

    all_files, binaries, symlinks, macho_proofs = [], [], [], {}
    for path in sorted(app.rglob('*')):
        relative = path.relative_to(app).as_posix()
        if path.is_symlink():
            symlinks.append(dict(path=relative, target=os.readlink(path)))
            if not path.resolve().is_relative_to(app):
                issues.append('Bundle symlink escapes app: ' + relative)
                continue
        if not path.is_file():
            continue
        record = dict(path=relative, size=path.stat().st_size, sha256=digest(path))
        all_files.append(record)
        fmt = binary_format(path)
        if not fmt:
            continue
        record = dict(record, format=fmt)
        if fmt == 'PE' and sys.platform == 'win32':
            try:
                import pefile  # Installed by PyInstaller on Windows.
                with pefile.PE(str(path), fast_load=True) as pe:
                    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
                    record['pe_version_resource'] = pe_version_metadata(pe)
            except Exception as error:
                record['pe_version_error'] = str(error)
                issues.append('Cannot inspect PE version resource: ' + relative)
        keys = destination_keys(relative)
        if path.resolve().is_relative_to(app):
            keys.update(destination_keys(path.resolve().relative_to(app).as_posix()))
        candidates = [candidate for key in sorted(keys)
                      for candidate in by_destination.get(key, ())]
        if path.name in ('psportal-native', 'psportal-native.exe'):
            candidates += [dict(source=str(source), sha256=digest(source), type='REVIEWED_NATIVE')
                           for source in native_origins]
        # Relocated framework links may have a different destination name.
        if not candidates:
            candidates = [item for item in origins if item['type'] in BINARY_TYPES
                          and item.get('sha256') == record['sha256']]
        record['origin_candidates'] = candidates
        record['origin_hash_verified'] = any(item.get('sha256') == record['sha256'] for item in candidates)
        if not record['origin_hash_verified'] and fmt == 'Mach-O' and sys.platform == 'darwin':
            from macho_origin_proof import prove_macho_origin
            record['origin_transformation_proofs'] = []
            resolved_relative = path.resolve().relative_to(app).as_posix()
            destination = resolved_relative.removeprefix('Contents/Frameworks/').removeprefix('Contents/MacOS/')
            for candidate in candidates:
                key = (candidate['source'], str(path.resolve()), destination, candidate['type'])
                if key not in macho_proofs:
                    macho_proofs[key] = prove_macho_origin(candidate['source'], path.resolve(), destination, candidate['type'])
                record['origin_transformation_proofs'].append(macho_proofs[key])
            record['origin_transformation_verified'] = any(proof['verified'] for proof in record['origin_transformation_proofs'])
        if not record['origin_hash_verified'] and not record.get('origin_transformation_verified'):
            issues.append('Unverified binary origin/hash: ' + relative)
        binaries.append(record)
    if not binaries:
        issues.append('No frozen native binaries found')

    try:
        from PyInstaller.depend.bindepend import get_imports
        search_paths = sorted({str((app / item['path']).parent) for item in binaries})
        for record in binaries:
            try:
                record['imports'] = [annotate_import(name, resolved) for name, resolved in
                    sorted(get_imports(str(app / record['path']), search_paths=search_paths),
                           key=lambda item: (item[0], item[1] or ''))]
                for item in record['imports']:
                    if item['resolved'] is None:
                        issues.append('Unresolved imported library: ' + record['path'] + ' -> ' + item['name'])
            except Exception as error:
                record['imports_error'] = str(error)
                issues.append('Cannot inventory imports: ' + record['path'])
    except ImportError as error:
        issues.append('PyInstaller dependency inspector unavailable: ' + str(error))

    candidates = {}
    def add_candidate(path, labels, locations, force=False):
        if path.is_file() and (force or LICENSE_NAME.search(path.name)):
            value = candidates.setdefault(path.resolve(), dict(components=set(), locations=set()))
            value['components'].update(labels)
            value['locations'].update(locations)
    for directory, metadata in sorted(notice_dirs.items()):
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            add_candidate(path, metadata['components'], metadata['locations'])
            if path.is_dir() and path.name.lower() in ('license', 'licenses', 'legal', 'resources'):
                for child in path.rglob('*'):
                    add_candidate(child, metadata['components'], metadata['locations'])
    try:
        distribution = importlib.metadata.distribution('pyinstaller')
        for item in distribution.files or ():
            add_candidate(Path(distribution.locate_file(item)), {'PyInstaller'}, {'installed'})
    except importlib.metadata.PackageNotFoundError:
        issues.append('Installed PyInstaller package metadata unavailable')
    for path in app.rglob('*'):
        if not path.is_symlink() or path.resolve().is_relative_to(app):
            add_candidate(path, {component(path)}, {'already-packaged'},
                          force=is_packaged_notice(path.relative_to(app)))
    companion = companion_notice_directory(app, sys.platform)
    if companion and companion.is_dir():
        if not companion.resolve().is_relative_to(app.parent):
            issues.append('Companion notices escape the build output directory')
        else:
            for path in companion.rglob('*'):
                if path.is_symlink() and not path.resolve().is_relative_to(companion.resolve()):
                    issues.append('Companion notice link escapes its directory: ' + str(path))
                    continue
                add_candidate(path, {component(path)}, {'already-packaged-companion'}, force=True)
    notices = []
    for path, metadata in sorted(candidates.items()):
        sha = digest(path)
        target = output / 'license-candidates' / sha / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        notices.append(dict(source=str(path), size=path.stat().st_size, sha256=sha,
            components=sorted(metadata['components']), locations=sorted(metadata['locations']),
            retained=target.relative_to(output).as_posix()))
    for label in ('Python', 'Tcl', 'Tk'):
        if not any(label in item['components'] and 'installed' in item['locations'] for item in notices):
            issues.append('No installed ' + label + ' license candidate found')

    report = dict(schema_version=1, diagnostic_only=True, inventory_complete=not issues,
        license_coverage_verified=False, distribution_approved=False,
        source_commit=os.environ.get('GITHUB_SHA', ''), app=str(app), build=str(build), runtime=runtime,
        companion_notice_directory=str(companion) if companion else None,
        limitations=[
            'License candidates are retained verbatim, but proximity does not establish license applicability.',
            'Mach-O transformations require scratch-only pinned normalization and exact normalized byte equality.',
            'System dependency resolutions are diagnostic; this does not claim those libraries were bundled.',
            'A complete platform-specific license and corresponding-source review is still required.'],
        summary=dict(files=len(all_files), binaries=len(binaries),
            verified_binary_origins=sum(item['origin_hash_verified'] or item.get('origin_transformation_verified', False) for item in binaries),
            byte_identical_binary_origins=sum(item['origin_hash_verified'] for item in binaries),
            normalized_binary_origins=sum(item.get('origin_transformation_verified', False) for item in binaries),
            license_candidates=len(notices), issues=len(issues)),
        issues=issues, tocs=tocs, binaries=binaries, files=all_files, symlinks=symlinks,
        collected_dependencies=origins, license_candidates=notices)
    (output / 'runtime-inventory.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    (output / 'README.txt').write_text(
        'DIAGNOSTIC ONLY. This directory does not approve distribution.\n'
        'runtime-inventory.json identifies exact files, binary origins, imports, and unresolved questions.\n'
        'license-candidates/ retains full unedited candidate notices from the build installation.\n'
        'Candidate proximity is not a claim that a notice covers a dependency.\n'
        'build-tocs/ retains the exact PyInstaller dependency records for review.\n', encoding='utf-8')
    print(json.dumps(report['summary'], indent=2))
    for issue in issues:
        print('UNVERIFIED: ' + issue)
    print('Diagnostic evidence: ' + str(output))
    return 1 if issues else 0


if __name__ == '__main__':
    raise SystemExit(main())
