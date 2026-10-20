#!/usr/bin/env python3
"""Build and test the frozen desktop with its matching optional native engine.

No installer, signing identity, live subscription, or system networking change.
Linux archive publication requires the exact distro-runtime notice audit.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
PORTABLE = ROOT / 'portable'
NATIVE = ROOT / 'native'


def run(command, *, cwd=ROOT, env=None):
    print('+ ' + ' '.join(map(str, command)), flush=True)
    subprocess.run([str(value) for value in command], cwd=cwd, env=env, check=True)


def source_commit():
    # The workflow uses this same expression for actions/checkout.ref. Avoid
    # changing Git ownership/security settings in containerized build jobs.
    value = os.environ.get('PSPORTAL_SOURCE_COMMIT', os.environ.get('GITHUB_SHA', ''))
    if value and not re.fullmatch(r'[0-9a-f]{40}', value):
        raise ValueError('Build evidence requires a full immutable commit SHA')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--debian-runtime-notices', action='store_true')
    parser.add_argument('--cpython-runtime-notices', action='store_true', help='Retain exact reviewed Windows/macOS CPython component notices')
    parser.add_argument('--xvfb', action='store_true')
    parser.add_argument('--frozen-window', action='store_true', help='Verify native Windows/macOS frozen window launch and normal close')
    parser.add_argument('--source-tk', action='store_true', help='Exercise real source Tk windows on a graphical native runner')
    args = parser.parse_args()
    print('Build Python:', sys.executable, sys.version, flush=True)
    print('Fixture python3 on PATH:', shutil.which('python3'), flush=True)
    system = {'Linux': 'linux', 'Darwin': 'darwin', 'Windows': 'windows'}[platform.system()]
    arch = {'x86_64': 'amd64', 'AMD64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}[platform.machine()]
    run([sys.executable, PORTABLE / 'scripts/fetch_yaml_sources.py'])
    run([sys.executable, NATIVE / 'scripts/build.py', '--target', f'{system}/{arch}'])
    run([sys.executable, NATIVE / 'scripts/source_release.py'])
    native = NATIVE / 'dist' / f'psportal-{system}-{arch}' / ('psportal.exe' if system == 'windows' else 'psportal')
    source = NATIVE / 'dist/psportal-native-corresponding-source.tar.gz'
    env = dict(os.environ, PSPORTAL_NATIVE_BINARY=str(native))
    build = [sys.executable, PORTABLE / 'build.py', '--native-engine', native, '--native-source', source]
    default_core = None
    if system == 'windows':
        from fetch_default_mihomo import prepare
        default_core = prepare(Path(os.environ['RUNNER_TEMP']) / 'psportal-default-core')
        build.extend(['--default-mihomo', default_core[0], '--mihomo-source', default_core[1],
                      '--mihomo-complete-source', default_core[2]])
        # Exercise exactly the distributable compatible core, not another fixture build.
        env['MIHOMO_BINARY'] = str(default_core[0])
    if args.debian_runtime_notices:
        build.append('--debian-runtime-notices')
    if args.cpython_runtime_notices:
        build.append('--cpython-runtime-notices')
    run(build, env=env)
    if system == 'darwin':
        executable = PORTABLE / 'dist/PSPortalProxy.app/Contents/MacOS/PSPortalProxy'
    else:
        executable = PORTABLE / 'dist/PSPortalProxy' / ('PSPortalProxy.exe' if system == 'windows' else 'PSPortalProxy')
    bundled = executable.parent / 'native' / ('psportal-native.exe' if system == 'windows' else 'psportal-native')
    assert bundled.is_file(), 'Matching native executable is missing from desktop package'
    assert hashlib.sha256(bundled.read_bytes()).digest() == hashlib.sha256(native.read_bytes()).digest()
    assert (bundled.parent / 'corresponding-source.tar.gz').read_bytes() == source.read_bytes()
    if default_core:
        from scripts.default_mihomo import verify, verify_complete_source
        notice = executable.parent / 'licenses/mihomo-v1.19.32'
        verify(executable.parent / 'mihomo.exe', notice / 'mihomo-v1.19.32-source.zip')
        verify_complete_source(notice / 'corresponding-source.tar.gz', notice / 'mihomo-v1.19.32-source.zip')
        env['MIHOMO_BINARY'] = str(executable.parent / 'mihomo.exe')
    env.update(PSPORTAL_BINARY=str(executable), PSPORTAL_DUAL_BINARY=str(executable))
    if args.frozen_window:
        env['PSPORTAL_FROZEN_WINDOW_TEST'] = '1'
    if args.source_tk or args.xvfb:
        env['PSPORTAL_TK_TEST'] = '1'
    command = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v']
    if args.xvfb:
        env['PSPORTAL_GUI_TEST'] = '1'
        command = ['xvfb-run', '-a'] + command
    print('+ ' + ' '.join(command), flush=True)
    tested = subprocess.run(command, cwd=PORTABLE, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', timeout=300)
    print(tested.stdout, flush=True)
    tested.check_returncode()
    count = re.search(r'Ran (\d+) tests? in', tested.stdout)
    skips = re.search(r'OK \(skipped=(\d+)\)', tested.stdout)
    assert count, 'Test runner did not report its count'
    release = PORTABLE / 'release'
    # Recheck source/license presence after acceptance tests and before upload.
    sys.path.insert(0, str(PORTABLE))
    from scripts.pyyaml_runtime import installed_evidence, verify_archive_notices
    yaml_evidence = installed_evidence(strict=True)
    archives = list(release.glob('PSPortalProxy-' + system + '-*'))
    assert len(archives) == 1, 'Expected one exact tested desktop archive'
    verify_archive_notices(archives[0], PORTABLE / 'dist/PSPortalProxy/licenses/pyyaml-6.0.3',
                           macos=system == 'darwin')
    if system == 'darwin':
        archives = list(release.glob('PSPortalProxy-darwin-*.tar.gz'))
        assert len(archives) == 1, 'Expected one final macOS archive'
        run([sys.executable, PORTABLE / 'scripts/verify_macos_archive.py',
             '--archive', archives[0], '--output', PORTABLE / 'build/final-macos-archive',
             '--evidence', release / 'MACOS-ARCHIVE-ACCEPTANCE.json'], env=env)
    evidence = dict(source_commit=source_commit(), system=system, architecture=arch,
        platform=platform.platform(), python=sys.version, native_binary_sha256=hashlib.sha256(native.read_bytes()).hexdigest(),
        corresponding_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        tests_run=int(count.group(1)), tests_skipped=int(skips.group(1)) if skips else 0,
        default_mihomo_bundled=bool(default_core),
        default_mihomo_binary_sha256=hashlib.sha256(default_core[0].read_bytes()).hexdigest() if default_core else None,
        default_mihomo_complete_source_sha256=hashlib.sha256(default_core[2].read_bytes()).hexdigest() if default_core else None,
        actual_external_core_tested=bool(env.get('MIHOMO_BINARY')),
        actual_frozen_gui_both_modes_tested=args.xvfb,
        native_platform_frozen_window_smoke_tested=args.frozen_window,
        source_tk_gui_both_modes_tested=args.source_tk or args.xvfb,
        matching_bundled_native_discovery_tested=True,
        exact_pyyaml_wheel_and_frozen_modules_verified=yaml_evidence['reviewed'],
        complete_pyyaml_libyaml_notices_and_sources_archived=True,
        exact_cpython_runtime_notices=args.cpython_runtime_notices,
        exact_debian_runtime_notices=args.debian_runtime_notices,
        final_macos_archive_acceptance_tested=system == 'darwin',
        developer_id_signed=False, notarized=False,
        live_subscription_or_physical_portal_tested=False)
    if args.debian_runtime_notices:
        manifest = PORTABLE / 'dist/PSPortalProxy/licenses/debian/runtime-manifest.json'
        evidence['audited_runtime_elf_count'] = len(json.loads(manifest.read_text()))
        assert evidence['audited_runtime_elf_count'] > 0
    (release / 'VALIDATION.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    files = sorted(path for path in release.iterdir() if path.is_file() and path.name != 'SHA256SUMS')
    assert sum(path.stat().st_size for path in files) < 150 * 1024 * 1024, 'Desktop artifact exceeds 150 MiB budget'
    (release / 'SHA256SUMS').write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n' for path in files), encoding='ascii')
    print(json.dumps(evidence, indent=2), flush=True)


if __name__ == '__main__':
    main()
