#!/usr/bin/env python3
"""Fetch the pinned official Windows core and retain its matching source closure.

CI only: no subscription, system network configuration or installation. The
upstream archive and executable are independently SHA-pinned before use.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

PORTABLE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PORTABLE))
from scripts import default_mihomo
from portalproxy import core_setup

SOURCE_URL = 'https://github.com/MetaCubeX/mihomo/archive/refs/tags/' + default_mihomo.VERSION + '.zip'
MAX_SOURCE = 10 * 1024 * 1024


def download(url, digest, limit):
    with urllib.request.urlopen(url, timeout=90) as response:
        data = response.read(limit + 1)
    if len(data) > limit or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('Default core download failed its pinned checksum/size gate')
    return data


def prepare(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    source = destination / 'upstream-source.zip'
    source.write_bytes(download(SOURCE_URL, default_mihomo.SOURCE_SHA256, MAX_SOURCE))
    payload = download(core_setup.URL, core_setup.SHA256, core_setup.MAX_ARCHIVE)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = [x for x in archive.infolist() if not x.is_dir() and x.filename.lower().endswith('.exe')]
        if len(members) != 1 or members[0].file_size > core_setup.MAX_BINARY:
            raise ValueError('Expected one bounded pinned Windows executable')
        binary = destination / 'mihomo.exe'
        binary.write_bytes(archive.read(members[0]))
    default_mihomo.verify(binary, source)
    # Source ZIP is exact/hash-verified; nevertheless reject unsafe archive paths.
    with zipfile.ZipFile(source) as archive:
        for item in archive.infolist():
            path = Path(item.filename)
            if path.is_absolute() or '..' in path.parts or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsafe upstream source archive member')
        archive.extractall(destination / 'source')
    root = destination / 'source' / ('mihomo-' + default_mihomo.VERSION.lstrip('v'))
    inputs = {name: (root / name).read_bytes() for name in ('go.mod', 'go.sum')}
    subprocess.run(['go', 'mod', 'vendor'], cwd=root, check=True)
    if any((root / name).read_bytes() != content for name, content in inputs.items()):
        raise ValueError('Vendoring modified the pinned dependency closure')
    manifest = {str(p.relative_to(root)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted((root / 'vendor').rglob('*')) if p.is_file()}
    (root / 'VENDOR-SHA256.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    closure = destination / 'corresponding-source.tar.gz'
    with tarfile.open(closure, 'w:gz') as archive:
        archive.add(root, arcname=root.name)
    return binary, source, closure


def main():
    binary, source, closure = prepare(Path(os.environ['RUNNER_TEMP']) / 'psportal-default-core')
    print('Verified default Windows core, pinned upstream source, and complete vendored source:', binary, source, closure)


if __name__ == '__main__':
    main()
