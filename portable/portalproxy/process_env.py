"""Launch a separately installed core without a frozen app's library overrides."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys


def external_environment():
    env = dict(os.environ)
    if not getattr(sys, 'frozen', False):
        return env
    if sys.platform.startswith('linux'):
        original = env.pop('LD_LIBRARY_PATH_ORIG', None)
        if original is None:
            env.pop('LD_LIBRARY_PATH', None)
        else:
            env['LD_LIBRARY_PATH'] = original
    bundled = getattr(sys, '_MEIPASS', None)
    if bundled:
        root = Path(bundled).resolve()
        for key in ('PATH', 'DYLD_LIBRARY_PATH'):
            if key not in env:
                continue
            entries = []
            for value in env[key].split(os.pathsep):
                try:
                    inside = bool(value) and Path(value).resolve().is_relative_to(root)
                except (ValueError, OSError):
                    inside = False
                if not inside:
                    entries.append(value)
            env[key] = os.pathsep.join(entries)
    return env


async def launch_external(*args):
    """Only changes the spawned core's environment; never invokes a shell."""
    kwargs = dict(env=external_environment(), stdout=asyncio.subprocess.DEVNULL,
                  stderr=asyncio.subprocess.DEVNULL)
    setter = None
    if sys.platform == 'win32':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        if getattr(sys, 'frozen', False):
            import ctypes
            setter = ctypes.windll.kernel32.SetDllDirectoryW
            setter.argtypes = [ctypes.c_wchar_p]
            setter.restype = ctypes.c_int
            if not setter(None):
                raise OSError('Unable to prepare external core library search path')
    try:
        return await asyncio.create_subprocess_exec(*args, **kwargs)
    finally:
        if setter is not None:
            # PyInstaller's original directory must remain available to this
            # Python process. Do not raise after spawn and lose core ownership.
            setter(getattr(sys, '_MEIPASS', None))
