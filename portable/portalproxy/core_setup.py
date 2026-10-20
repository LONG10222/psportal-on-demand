"""Deterministic desktop core discovery and an explicit, pinned Windows install."""
import hashlib
import io
import os
from pathlib import Path
import platform
import sys
import tempfile
import urllib.request
import zipfile

VERSION = 'v1.19.32'
ASSET = 'mihomo-windows-amd64-compatible-v1.19.32.zip'
SHA256 = '974a4d7ad69aed27aa2e8f91d61113573c14dadb14562c63e58effabf59816f0'
URL = f'https://github.com/MetaCubeX/mihomo/releases/download/{VERSION}/{ASSET}'
RELEASES = 'https://github.com/MetaCubeX/mihomo/releases'
MAX_ARCHIVE = 50 * 1024 * 1024
MAX_BINARY = 100 * 1024 * 1024


def managed_path(config_path):
    return Path(config_path).parent / 'cores' / VERSION / 'mihomo.exe'


def discover_core(config_path, configured=''):
    """Keep explicit choices; consider only known locations, never scan PATH/disk."""
    # An explicit missing path needs repair; do not silently change the user's core.
    if configured:
        try:
            return str(Path(configured)) if Path(configured).is_file() else None
        except (TypeError, ValueError, OSError):
            return None
    candidates = []
    if sys.platform == 'win32':
        managed = managed_path(config_path)
        try:
            _validate_install_path(managed.absolute())
        except (ValueError, OSError, RuntimeError):
            # Do not automatically execute a managed core reached through a
            # redirected directory. Explicit user choices remain separate.
            pass
        else:
            candidates.append(managed)
    name = 'mihomo.exe' if sys.platform == 'win32' else 'mihomo'
    if getattr(sys, 'frozen', False):
        candidates.append(Path(sys.executable).parent / name)
    if sys.platform == 'win32':
        for key in ('ProgramW6432', 'ProgramFiles', 'LOCALAPPDATA'):
            folder = os.environ.get(key)
            if folder and Path(folder).is_absolute():
                base = Path(folder)
                if key == 'LOCALAPPDATA': base = base / 'Programs'
                candidates.append(base / 'Clash Verge' / 'verge-mihomo.exe')
    return next((str(p) for p in candidates if p.is_file() and not p.is_symlink()), None)


def can_install():
    return sys.platform == 'win32' and platform.machine().lower() in ('amd64', 'x86_64')


def discover_clash():
    if sys.platform != 'win32': return None
    for key in ('ProgramW6432', 'ProgramFiles', 'LOCALAPPDATA'):
        folder = os.environ.get(key)
        if not folder or not Path(folder).is_absolute(): continue
        base = Path(folder) / 'Programs' if key == 'LOCALAPPDATA' else Path(folder)
        path = base / 'Clash Verge' / 'clash-verge.exe'
        if path.is_file() and not path.is_symlink(): return path
    return None


def _validate_install_path(target):
    """Reject redirected destinations, except macOS's fixed system aliases.

    macOS temporary directories normally live below /var, which the OS maps to
    /private/var (and /tmp similarly maps to /private/tmp). Do not resolve the
    entire destination first: that would hide links in user-managed directories.
    """
    aliases = {Path('/var'): Path('/private/var'),
               Path('/tmp'): Path('/private/tmp')} if sys.platform == 'darwin' else {}
    for path in (target, *target.parents):
        is_junction = getattr(path, 'is_junction', None)
        if is_junction is not None and is_junction():
            raise ValueError('Core location must not be a junction.')
        if path.is_symlink():
            expected = aliases.get(path)
            if expected is None or path.resolve(strict=True) != expected:
                raise ValueError('Core location must not be a symbolic link.')


def install_core(config_path):
    """Explicit action only. Verify before writing; never run downloaded code here."""
    if not can_install(): raise ValueError('Automatic download supports Windows x64 only.')
    with urllib.request.urlopen(URL, timeout=30) as response:
        payload = response.read(MAX_ARCHIVE + 1)
    if len(payload) > MAX_ARCHIVE or hashlib.sha256(payload).hexdigest() != SHA256:
        raise ValueError('Core download failed checksum verification.')
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        files = [f for f in archive.infolist() if not f.is_dir() and f.filename.lower().endswith('.exe')]
        if len(files) != 1 or files[0].file_size > MAX_BINARY:
            raise ValueError('Invalid core archive.')
        binary = archive.read(files[0])
    if not binary.startswith(b'MZ') or len(binary) > MAX_BINARY:
        raise ValueError('Invalid core executable.')
    # Use an absolute spelling so relative paths cannot omit ancestor checks.
    target = managed_path(config_path).absolute()
    _validate_install_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    _validate_install_path(target)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(binary)
        os.replace(temporary, target)
    finally:
        if temporary: temporary.unlink(missing_ok=True)
    return str(target)
