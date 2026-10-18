#!/usr/bin/env python3
"""Build on this OS only. Never downloads dependencies, Mihomo, or subscriptions."""
from __future__ import annotations

import argparse
import importlib.util
import importlib.metadata
import sysconfig
from pathlib import Path
import platform
import os
import shutil
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-tests', action='store_true', help='Build without tests; not suitable for release acceptance')
    parser.add_argument('--debian-runtime-notices', action='store_true', help='Audit exact distro Python3.13/Tk8.6 ELF and retain installed Debian notices')
    parser.add_argument('--cpython-runtime-notices', action='store_true', help='Retain the exact reviewed Windows/macOS CPython supplemental notices; fail on unreviewed versions')
    parser.add_argument('--native-engine', type=Path, help='Bundle a reviewed native psportal executable as an experimental option')
    parser.add_argument('--native-source', type=Path, help='Matching complete native source+vendor archive; required with --native-engine')
    args = parser.parse_args(argv)
    if args.debian_runtime_notices and (not sys.platform.startswith('linux') or Path(sys.base_prefix) != Path('/usr')):
        parser.error('--debian-runtime-notices requires the distro /usr Linux Python used for this build')
    if args.cpython_runtime_notices and sys.platform not in ('win32', 'darwin'):
        parser.error('--cpython-runtime-notices is limited to reviewed Windows/macOS CPython builds')
    if bool(args.native_engine) != bool(args.native_source):
        parser.error('--native-engine and --native-source must be supplied together')
    if args.native_engine:
        args.native_engine = args.native_engine.resolve()
        args.native_source = args.native_source.resolve()
        if not args.native_engine.is_file() or not args.native_source.is_file():
            parser.error('Native executable and corresponding-source archive must exist')
        for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'SOURCE.md', 'licenses'):
            if not (args.native_engine.parent / name).exists():
                parser.error('Native release is missing its required license/source notices: ' + name)
    root = Path(__file__).resolve().parent
    if importlib.util.find_spec('PyInstaller') is None:
        parser.error('PyInstaller is missing. Install requirements-build.txt in a local build virtualenv first.')
    if importlib.util.find_spec('tkinter') is None:
        parser.error('This Python has no Tk support. Install a Tk-enabled Python before building.')
    if not args.skip_tests:
        subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=root, check=True)
    build_env = dict(os.environ)
    if sys.platform == 'win32':
        from scripts.windows_build_environment import windows_pyinstaller_environment
        build_env = windows_pyinstaller_environment(
            build_env, executable=sys.executable, prefix=sys.prefix, base_prefix=sys.base_prefix)
    elif sys.platform.startswith('linux'):
        # Standalone Python distributions keep Tcl/Tk beside libpython; make
        # them discoverable to PyInstaller's ldd analysis, for this child only.
        libdir = str(Path(sys.base_prefix) / 'lib')
        build_env['LD_LIBRARY_PATH'] = libdir + os.pathsep + build_env.get('LD_LIBRARY_PATH', '')
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
        '--distpath', str(root / 'dist'), '--workpath', str(root / 'build'),
        str(root / 'packaging' / 'portalproxy.spec'),
    ], cwd=root, check=True, env=build_env)
    folder = root / 'dist' / 'PSPortalProxy'
    executable = folder / ('PSPortalProxy.exe' if sys.platform == 'win32' else 'PSPortalProxy')
    subprocess.run([str(executable), '--smoke-test'], check=True, timeout=30)
    if args.native_engine:
        native_folder = (root / 'dist' / 'PSPortalProxy.app' / 'Contents' / 'MacOS' / 'native') if sys.platform == 'darwin' else folder / 'native'
        native_folder.mkdir(parents=True, exist_ok=True)
        filename = 'psportal-native.exe' if sys.platform == 'win32' else 'psportal-native'
        shutil.copy2(args.native_engine, native_folder / filename)
        shutil.copy2(args.native_source, native_folder / 'corresponding-source.tar.gz')
        for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'SOURCE.md', 'README.md', 'config.example.json'):
            shutil.copy2(args.native_engine.parent / name, native_folder / name)
        shutil.copytree(args.native_engine.parent / 'licenses', native_folder / 'licenses', dirs_exist_ok=True)
        (native_folder / 'README.txt').write_text('Experimental embedded engine. Default external mode is unchanged.\nComplete corresponding source: corresponding-source.tar.gz\nNative engine license: GPL-3.0-only. See LICENSE and licenses/.\n', encoding='utf-8')
    notices = folder / 'licenses'
    notices.mkdir(exist_ok=True)
    shutil.copy2(root.parent / 'LICENSE', notices / 'PSPortal-OnDemand-LICENSE.txt')
    shutil.copy2(root / 'docs' / 'THIRD-PARTY-NOTICES.md', notices / 'THIRD-PARTY-NOTICES.md')
    for filename in ('Tcl-license.terms', 'Tk-license.terms'):
        shutil.copy2(root / 'docs' / filename, notices / filename)
    python_license = Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt'
    if not python_license.is_file():
        python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.is_file():
        shutil.copy2(python_license, notices / 'Python-LICENSE.txt')
    else:
        print('NOTICE: Python license file was not found; add it before redistribution.')
    if args.cpython_runtime_notices:
        from scripts.retain_cpython_notices import retain_supplement
        retain_supplement(root / 'notices' / 'cpython-3.13.16', notices / 'cpython-3.13.16',
            python_license, vcruntime_origin=Path(sys.base_prefix) / 'VCRUNTIME140.dll',
            bundled_vcruntime=folder / '_internal' / 'VCRUNTIME140.dll')
    distribution = importlib.metadata.distribution('pyinstaller')
    for item in distribution.files or ():
        if str(item).endswith('COPYING.txt'):
            shutil.copy2(distribution.locate_file(item), notices / 'PyInstaller-COPYING.txt')
            break
    if args.debian_runtime_notices:
        subprocess.run([sys.executable, str(root / 'scripts' / 'audit_linux_runtime.py'), str(folder)], check=True)
    if (root / 'docs' / 'validation.md').is_file():
        shutil.copy2(root / 'docs' / 'validation.md', folder / 'validation.md')
    release = root / 'release'
    release.mkdir(exist_ok=True)
    name = 'PSPortalProxy-' + platform.system().lower() + '-' + platform.machine().lower()
    if sys.platform == 'darwin':
        # Preserve the .app bundle's symlinks and executable modes.
        archive = release / (name + '.tar.gz')
        import tarfile
        with tarfile.open(archive, 'w:gz') as stream:
            stream.add(root / 'dist' / 'PSPortalProxy.app', arcname='PSPortalProxy.app')
            stream.add(notices, arcname='licenses')
            stream.add(root / 'docs' / 'desktop.md', arcname='desktop.md')
            stream.add(root / 'docs' / 'native-acceptance.md', arcname='native-acceptance.md')
            if (root / 'docs' / 'validation.md').is_file():
                stream.add(root / 'docs' / 'validation.md', arcname='validation.md')
    elif sys.platform == 'win32':
        shutil.copy2(root / 'docs' / 'desktop.md', folder / 'desktop.md')
        shutil.copy2(root / 'docs' / 'native-acceptance.md', folder / 'native-acceptance.md')
        archive = shutil.make_archive(str(release / name), 'zip', root_dir=folder.parent, base_dir=folder.name)
    else:
        shutil.copy2(root / 'docs' / 'desktop.md', folder / 'desktop.md')
        shutil.copy2(root / 'docs' / 'native-acceptance.md', folder / 'native-acceptance.md')
        archive = shutil.make_archive(str(release / name), 'gztar', root_dir=folder.parent, base_dir=folder.name)
    print('Built local archive:', archive)
    print('Native GUI, real Mihomo, Portal, signing and firewall acceptance still required.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
