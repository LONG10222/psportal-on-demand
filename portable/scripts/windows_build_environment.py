"""Limit PyInstaller dependency discovery to the chosen Python and Windows.

This creates one child environment. It never changes the caller's environment
or any operating-system settings. Unrelated developer-tool PATH entries can
otherwise cause PyInstaller to bundle their private copies of Windows DLLs.
"""
from pathlib import Path
import os


def windows_pyinstaller_environment(environ, *, executable, prefix, base_prefix):
    environment = dict(environ)
    values = {key.casefold(): value for key, value in environ.items()}
    root_text = values.get('systemroot') or values.get('windir')
    if not root_text:
        raise ValueError('Windows build requires SystemRoot or WINDIR')
    windows = Path(root_text)
    python = Path(executable)
    prefixes = [Path(prefix), Path(base_prefix)]
    if not windows.is_absolute() or not (windows / 'System32').is_dir():
        raise ValueError('Windows build requires an existing absolute System32 directory')
    if not python.is_absolute() or not python.is_file():
        raise ValueError('Windows build requires an existing absolute Python executable')
    if any(not path.is_absolute() or not path.is_dir() for path in prefixes):
        raise ValueError('Windows build requires existing absolute Python prefixes')
    candidates = [python.parent]
    for path in prefixes:
        candidates.extend((path, path / 'Scripts', path / 'DLLs'))
    candidates.extend((windows / 'System32', windows))
    paths, seen = [], set()
    for path in candidates:
        if path.is_dir() and str(path).casefold() not in seen:
            seen.add(str(path).casefold())
            paths.append(str(path))
    for key in list(environment):
        if key.casefold() == 'path':
            del environment[key]
    environment['PATH'] = os.pathsep.join(paths)
    return environment
