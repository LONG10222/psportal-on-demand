"""Fail-closed release gate for the individually reviewed Windows x64 runtime.

The diagnostic inventory alone never approves distribution. This separate gate
binds its exact files to reviewed runtime hashes, complete versioned notices,
matching native source and the successful real-window/runtime test evidence.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PureWindowsPath
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def within_windows(path, root):
    return bool(path and root and '..' not in PureWindowsPath(path).parts and
                '..' not in PureWindowsPath(root).parts and PureWindowsPath(path).is_absolute() and
                PureWindowsPath(path).is_relative_to(PureWindowsPath(root)))


def verify_inventory(report, reviewed, system_root, *, require_default_mihomo=False):
    require(report.get('inventory_complete') is True and not report.get('issues'), 'Runtime inventory has unresolved issues')
    try:
        from .pyyaml_runtime import verify_python_inventory
    except ImportError:
        from pyyaml_runtime import verify_python_inventory
    yaml_review, yaml_extension = verify_python_inventory(report, 'win32')
    yaml_path = '_internal/' + yaml_review['extension_path']
    binaries = report.get('binaries', [])
    expected = set(reviewed['runtime_files']) | {yaml_path, 'PSPortalProxy.exe', 'native/psportal-native.exe'}
    has_mihomo = any(b['path'] == 'mihomo.exe' for b in binaries)
    require(has_mihomo or not require_default_mihomo, 'Required pinned default Mihomo is missing')
    if has_mihomo:
        expected.add('mihomo.exe')
    require(len(binaries) == len(expected) and {b['path'] for b in binaries} == expected and
            all(b.get('origin_hash_verified') is True for b in binaries),
            'Expected exact reviewed Windows runtime, PyYAML, application/native and pinned optional core origins; '
            'missing=' + str(sorted(expected - {b['path'] for b in binaries})) +
            ', unexpected=' + str(sorted({b['path'] for b in binaries} - expected)))
    files = {item['path']: item['sha256'] for item in report.get('files', [])}
    require(len(files) == len(report.get('files', [])), 'Duplicate inventoried file path')
    require(all(files.get(binary['path']) == binary['sha256'] for binary in binaries), 'Binary hashes disagree with archive file inventory')
    internal = {b['path']: b['sha256'] for b in binaries if b['path'].startswith('_internal/') and b['path'] != yaml_path}
    require(internal == reviewed['runtime_files'], 'Windows runtime differs from the individually reviewed files')
    require(report['runtime']['pyinstaller'] == reviewed['pyinstaller_version'], 'PyInstaller version requires new review')
    prefix = report['runtime']['base_prefix']
    system = str(PureWindowsPath(system_root) / 'System32')
    for binary in binaries:
        if binary['path'] == 'mihomo.exe':
            try:
                from .default_mihomo import BINARY_SHA256, VERSION
            except ImportError:
                from default_mihomo import BINARY_SHA256, VERSION
            require(binary['sha256'] == BINARY_SHA256 and any(
                c.get('type') == 'PINNED_OFFICIAL_MIHOMO' and c.get('sha256') == BINARY_SHA256 and
                c.get('source') == 'https://github.com/MetaCubeX/mihomo/releases/tag/' + VERSION
                for c in binary.get('origin_candidates', [])), 'Default Mihomo differs from pinned official release')
        if binary['path'] == yaml_path:
            require(binary['sha256'] == yaml_review['extension_sha256'] and
                    any(c.get('source') == yaml_extension['source'] and c.get('sha256') == binary['sha256'] and
                        c.get('type') == 'EXTENSION' and within_windows(c.get('source'), report['runtime']['prefix'])
                        for c in binary.get('origin_candidates', [])), 'YAML extension differs from exact installed wheel origin')
        if binary['path'] in internal:
            require(any(c.get('sha256') == binary['sha256'] and within_windows(c.get('source'), prefix)
                        for c in binary.get('origin_candidates', [])), 'Runtime origin is outside selected Python')
        for item in binary.get('imports', []):
            resolved = item.get('resolved')
            require(any(within_windows(resolved, base) for base in (report['app'], system)), 'Dependency is not supplied by package or Windows System32: ' + str(item.get('name')))
            if item['name'].lower().startswith('api-ms-win-'):
                require(within_windows(resolved, system) and item.get('resolution_method') == 'windows-api-set-system-loader' and
                        re.fullmatch('[0-9a-f]{64}', item.get('system_sha256', '')), 'Missing actual system-loader proof for API-set contract')
    return binaries


def verify_archive(archive, files):
    expected = {'PSPortalProxy/' + item['path']: item['sha256'] for item in files}
    require(len(expected) == len(files), 'Duplicate inventory path')
    with zipfile.ZipFile(archive) as stream:
        members = [item for item in stream.infolist() if not item.is_dir()]
        require(len(members) == len(expected) and {item.filename for item in members} == set(expected), 'Archive and tested/inventoried package have different files')
        for item in members:
            require(digest(stream.read(item)) == expected[item.filename], 'Archive content changed: ' + item.filename)


def verify_default_core(app, validation):
    try:
        from .default_mihomo import verify, verify_complete_source, VERSION
    except ImportError:
        from default_mihomo import verify, verify_complete_source, VERSION
    notices = app / 'licenses' / ('mihomo-' + VERSION)
    source = notices / ('mihomo-' + VERSION + '-source.zip')
    license_text = verify(app / 'mihomo.exe', source)
    require((notices / 'LICENSE.txt').read_bytes() == license_text, 'Default Mihomo full license differs from pinned source')
    complete_sha = verify_complete_source(notices / 'corresponding-source.tar.gz', source)
    require(validation.get('default_mihomo_bundled') is True and
            validation.get('default_mihomo_complete_source_sha256') == complete_sha,
            'Default Mihomo corresponding source differs from build/test evidence')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=ROOT / 'runtime-inventory/runtime-inventory.json')
    args = parser.parse_args(argv)
    require(sys.platform == 'win32', 'The Windows release gate must run on the actual Windows host')
    report = json.loads(args.inventory.read_text(encoding='utf-8'))
    reviewed = json.loads((ROOT / 'notices/windows-cpython-3.13.16-runtime.json').read_text(encoding='utf-8'))
    binaries = verify_inventory(report, reviewed, os.environ['SystemRoot'], require_default_mihomo=True)
    for binary in binaries:
        for item in binary.get('imports', []):
            if item['name'].lower().startswith('api-ms-win-'):
                require(digest(Path(item['resolved']).read_bytes()) == item['system_sha256'], 'System API-set host changed since inventory')
    from pyyaml_runtime import verify_retained_notices
    app = Path(report['app'])
    verify_retained_notices(app / 'licenses/pyyaml-6.0.3', report['runtime']['pyyaml'])
    require(app.resolve() == (ROOT / 'dist/PSPortalProxy').resolve(), 'Unexpected app inventory path')
    validation = json.loads((ROOT / 'release/VALIDATION.json').read_text(encoding='utf-8'))
    verify_default_core(app, validation)
    require(report['source_commit'] == validation['source_commit'] == os.environ.get('PSPORTAL_SOURCE_COMMIT', os.environ.get('GITHUB_SHA', '')), 'Evidence came from a different commit')
    require(validation['system'] == 'windows' and validation['architecture'] == 'amd64', 'Unreviewed platform')
    require(validation['tests_run'] >= 132 and all(validation.get(key) is True for key in (
        'exact_cpython_runtime_notices', 'actual_external_core_tested', 'native_platform_frozen_window_smoke_tested',
        'source_tk_gui_both_modes_tested', 'matching_bundled_native_discovery_tested')), 'Required tested/runtime-notice evidence is missing')
    from retain_cpython_notices import (verified_supplement_files, WINDOWS_INSTALLED_LICENSE_SHA256,
                                       WINDOWS_VCRUNTIME_SHA256, WINDOWS_VCRUNTIME_1_SHA256)
    source = ROOT / 'notices/cpython-3.13.16'
    retained = app / 'licenses/cpython-3.13.16'
    for path in verified_supplement_files(source):
        require((retained / path.name).read_bytes() == path.read_bytes(), 'Complete reviewed notice not retained: ' + path.name)
    scope = json.loads((retained / 'runtime-scope.json').read_text(encoding='utf-8'))
    require(scope['python'] == reviewed['python_version'] and scope['platform'] == 'win32', 'Wrong notice runtime scope')
    require(scope['installed_python_license_sha256'] == WINDOWS_INSTALLED_LICENSE_SHA256 and
            digest((app / 'licenses/Python-LICENSE.txt').read_bytes()) == WINDOWS_INSTALLED_LICENSE_SHA256, 'Installed license differs from reviewed distribution')
    require(scope['microsoft_runtime']['sha256'] == WINDOWS_VCRUNTIME_SHA256, 'Microsoft runtime scope does not match review')
    require(scope.get('microsoft_runtime_additional', {}).get('sha256') == WINDOWS_VCRUNTIME_1_SHA256,
            'Additional Microsoft runtime scope does not match review')
    for name in ('licenses/PyInstaller-COPYING.txt', 'licenses/PSPortal-OnDemand-LICENSE.txt',
                 'native/LICENSE', 'native/THIRD_PARTY_NOTICES.md', 'native/SOURCE.md', 'native/licenses/ENGINE-NOTICES.txt'):
        require((app / name).stat().st_size > 100, 'Required full notice is missing: ' + name)
    require(digest((app / 'native/corresponding-source.tar.gz').read_bytes()) == validation['corresponding_source_sha256'], 'Native corresponding source mismatch')
    require(digest((app / 'native/psportal-native.exe').read_bytes()) == validation['native_binary_sha256'], 'Native executable mismatch')
    archives = list((ROOT / 'release').glob('PSPortalProxy-windows-*.zip'))
    require(len(archives) == 1, 'Expected one exact Windows archive')
    verify_archive(archives[0], report['files'])
    result = dict(source_commit=validation['source_commit'], unsigned=True,
        scope='Reviewed Windows x64 CPython3.13.16/PyInstaller6.16.0 development GUI archive only',
        runtime_binaries_verified=len(binaries), runtime_review_source=reviewed['evidence_run'],
        complete_versioned_notices_retained=True, matching_native_source_retained=True,
        real_window_and_runtime_checks_passed=True, runtime_inventory_sha256=digest(args.inventory.read_bytes()),
        archive_sha256=digest(archives[0].read_bytes()), physical_portal_or_live_subscription_tested=False)
    release = ROOT / 'release'
    (release / 'WINDOWS-RUNTIME-REVIEW.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    files = sorted(path for path in release.iterdir() if path.is_file() and path.name != 'SHA256SUMS')
    require(sum(path.stat().st_size for path in files) < 150 * 1024 * 1024, 'Windows release exceeds size budget')
    (release / 'SHA256SUMS').write_text(''.join(digest(path.read_bytes()) + '  ' + path.name + '\n' for path in files), encoding='ascii')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
