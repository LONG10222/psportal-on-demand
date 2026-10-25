# Build on each target OS; PyInstaller does not cross-compile.
from pathlib import Path
import sys
import sysconfig

root = Path(SPECPATH).resolve().parent
branding = root.parent / 'native' / 'assets' / 'branding' / 'desktop'
integrations=root.parent/'integrations'
extra_data=[(str(integrations/'xianniu-router/files/usr/share/xianniu-router/catalog.json'),'.')]
ssl_policy=Path(sysconfig.get_path('stdlib'))/'codex-rejected-cas.pem'
if ssl_policy.is_file():extra_data.append((str(ssl_policy),'.'))
analysis = Analysis(
    [str(root / 'packaging' / 'entry.py')], pathex=[str(root),str(integrations/'xianniu-windows/src'),str(integrations/'xianniu-router/src')],
    binaries=[], datas=[(str(branding), 'assets/branding')]+extra_data, hiddenimports=['portalproxy.__main__', 'yaml._yaml','starpass_xianniu.app'],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True, name='PSPortalProxy',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True, hide_console='hide-early' if sys.platform == 'win32' else None,
    disable_windowed_traceback=False,
    icon=str(branding / 'starpass.ico') if sys.platform == 'win32' else None,
)
bundle = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name='PSPortalProxy')
if sys.platform == 'darwin':
    app = BUNDLE(bundle, name='PSPortalProxy.app', icon=str(branding / 'starpass.icns'),
        bundle_identifier='org.psportal.on-demand',
        info_plist={'NSHighResolutionCapable': True, 'CFBundleDisplayName': '星渡 StarPass'})
