# Build on each target OS; PyInstaller does not cross-compile.
from pathlib import Path
import sys

root = Path(SPECPATH).resolve().parent
analysis = Analysis(
    [str(root / 'packaging' / 'entry.py')], pathex=[str(root)],
    binaries=[], datas=[], hiddenimports=['portalproxy.__main__', 'yaml._yaml'],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True, name='PSPortalProxy',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True, hide_console='hide-early' if sys.platform == 'win32' else None,
    disable_windowed_traceback=False,
)
bundle = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name='PSPortalProxy')
if sys.platform == 'darwin':
    app = BUNDLE(bundle, name='PSPortalProxy.app', icon=None,
        bundle_identifier='org.psportal.on-demand',
        info_plist={'NSHighResolutionCapable': True})
