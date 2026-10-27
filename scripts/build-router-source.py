#!/usr/bin/env python3
"""Deterministic, source-only router bundle. No core/configuration/credentials."""
import argparse
import gzip
import hashlib
import io
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ('install.sh', 'uninstall.sh', 'LICENSE', 'README.zh-CN.md', 'CHANGELOG.md',
         'SECURITY.md', 'scripts/build-router-source.py', 'scripts/build-router-ipk.py')
DIRS = ('src', 'files', 'luci', 'tests', 'docs','gateway')


def build(destination):
    paths = [ROOT / name for name in FILES]
    for name in DIRS:
        paths.extend(p for p in (ROOT / name).rglob('*')
                     if p.is_file() and p.suffix in ('.lua', '.sh', '.md', '.py', '.init', '.config', '.htm', '.js', '.rb', '.json'))
    paths.append(ROOT / 'files/portalproxy')
    entries = {}
    for path in sorted(set(paths)):
        if path.is_symlink():
            raise ValueError('Router bundle does not permit symlinks')
        relative = path.relative_to(ROOT).as_posix()
        executable = relative.endswith(('.sh', '.init')) or relative == 'files/portalproxy'
        entries[relative] = (path.read_bytes().replace(b'\r\n', b'\n'), 0o755 if executable else 0o644)
    entries['SHA256SUMS'] = (''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n'
                                   for name, (data, _) in sorted(entries.items())).encode(), 0o644)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode='w', format=tarfile.PAX_FORMAT) as archive:
            for name, (data, mode) in sorted(entries.items()):
                info = tarfile.TarInfo('starpass-router-source/' + name)
                info.size, info.mode, info.mtime = len(data), mode, 0
                archive.addfile(info, io.BytesIO(data))
    print(f'{hashlib.sha256(destination.read_bytes()).hexdigest()}  {destination.name}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    build(parser.parse_args().output)
