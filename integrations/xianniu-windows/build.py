"""Build the independent Windows provider preview; never packages user state."""
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]


def main():
    if os.name != 'nt': raise RuntimeError('Build on Windows')
    sys.path.insert(0, str(REPO / 'portable'))
    from scripts.windows_build_environment import windows_pyinstaller_environment
    environment = windows_pyinstaller_environment(os.environ, executable=sys.executable, prefix=sys.prefix, base_prefix=sys.base_prefix)
    dist = ROOT / 'dist'
    # The bundled desktop Python may patch ssl.py to load a public CA policy
    # file beside the module. Retain that exact runtime input; never bypass TLS.
    ssl_policy = Path(sysconfig.get_path('stdlib')) / 'codex-rejected-cas.pem'
    runtime_data = ['--add-data', str(ssl_policy) + ';.'] if ssl_policy.is_file() else []
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--console',
        '--hide-console', 'hide-early', '--name', 'StarPassXianniuPreview',
        '--paths', str(ROOT / 'src'), '--paths', str(ROOT.parent / 'xianniu-router/src'),
        '--add-data', str(ROOT.parent / 'xianniu-router/files/usr/share/xianniu-router/catalog.json') + ';.',
        '--icon', str(REPO / 'native/assets/branding/desktop/starpass.ico'),
        '--distpath', str(dist), '--workpath', str(ROOT / 'build'), '--specpath', str(ROOT / 'build'),
        *runtime_data, str(ROOT / 'run.py')], env=environment, check=True)
    folder = dist / 'StarPassXianniuPreview'
    notices = folder / 'licenses'; notices.mkdir(exist_ok=True)
    shutil.copy2(REPO / 'LICENSE', notices / 'StarPass-MIT.txt')
    python_license = Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt'
    if not python_license.is_file(): python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    shutil.copy2(python_license, notices / 'Python-LICENSE.txt')
    for name in ('Tcl-license.terms', 'Tk-license.terms'):
        shutil.copy2(REPO / 'portable/docs' / name, notices / name)
    for item in importlib.metadata.distribution('pyinstaller').files or ():
        if str(item).endswith('COPYING.txt'):
            shutil.copy2(importlib.metadata.distribution('pyinstaller').locate_file(item), notices / 'PyInstaller-COPYING.txt')
    pillow=importlib.metadata.distribution('Pillow')
    for item in pillow.files or ():
        if '/licenses/' in str(item).replace('\\','/') and not str(item).endswith('/'):
            origin=Path(pillow.locate_file(item))
            if origin.is_file():
                target=notices/'Pillow'/origin.name;target.parent.mkdir(exist_ok=True);shutil.copy2(origin,target)
    for name in ('README.zh-CN.md', 'DESIGN.zh-CN.md', 'VALIDATION.md', 'InstallPreview.cmd', 'InstallPreview.ps1', 'StartPreview.cmd', 'AllowLan.cmd', 'AllowLan.ps1'):
        if (ROOT / name).is_file(): shutil.copy2(ROOT / name, folder / name)
    subprocess.run([str(folder / 'StarPassXianniuPreview.exe'), '--smoke-test'], check=True)
    (folder / 'build-info.json').write_text(json.dumps({'version':'0.2.0','python':sys.version,
        'pyinstaller':importlib.metadata.version('pyinstaller'),'source_base':'f91123f147cd2d931c04c70820c59e02bf3dee1a',
        'local_unsigned_preview':True,'contains_account_data':False},indent=2),encoding='utf-8')
    print(folder)


if __name__=='__main__':main()
