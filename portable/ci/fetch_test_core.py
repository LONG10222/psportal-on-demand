#!/usr/bin/env python3
"""Fetch an official, checksum-pinned external core for CI fixtures only.

The executable stays in RUNNER_TEMP, outside source and distribution archives.
No subscription, installation, signing or system-network change is performed.
"""
import gzip
import hashlib
import os
from pathlib import Path
import platform
import subprocess
import urllib.request
import zipfile

VERSION = 'v1.19.32'
# Official MetaCubeX release asset SHA-256 values, independently fixed in source.
ASSETS = {
    ('Linux', 'amd64'): ('mihomo-linux-amd64-v1.19.32.gz', '8451100836c9eda194331c2babfad490b2faf30cebc1a04b0e76fd8ac2d35d10'),
    ('Darwin', 'arm64'): ('mihomo-darwin-arm64-v1.19.32.gz', '3312a6780652c622890fd4357c6a853bbf865464fd047ac7b7f52dab8de18652'),
    ('Windows', 'amd64'): ('mihomo-windows-amd64-v1.19.32.zip', '1ac84e795b5b915446e20139677fb6cc013a0778e876e8d4c96f994750b4c4a3'),
}
MAX_ARCHIVE = 50 * 1024 * 1024
MAX_BINARY = 100 * 1024 * 1024


def verify_archive(path, expected):
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError('Official test-core archive checksum mismatch')


def unpack_binary(path, filename):
    if filename.endswith('.gz'):
        with gzip.open(path, 'rb') as stream:
            payload = stream.read(MAX_BINARY + 1)
    elif filename.endswith('.zip'):
        with zipfile.ZipFile(path) as archive:
            candidates = [item for item in archive.infolist()
                          if not item.is_dir() and item.filename.lower().endswith('.exe')]
            if len(candidates) != 1 or candidates[0].file_size > MAX_BINARY:
                raise ValueError('Expected exactly one bounded official core executable')
            # Read only its bytes; never extract archive paths or links.
            payload = archive.read(candidates[0])
    else:
        raise ValueError('Unsupported core archive format')
    if not payload or len(payload) > MAX_BINARY:
        raise ValueError('Empty or oversized test-core executable')
    return payload


def main():
    machine = platform.machine().lower()
    arch = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}[machine]
    filename, expected = ASSETS[(platform.system(), arch)]
    destination = Path(os.environ['RUNNER_TEMP']) / 'psportal-test-core'
    destination.mkdir(exist_ok=True)
    archive = destination / filename
    url = f'https://github.com/MetaCubeX/mihomo/releases/download/{VERSION}/{filename}'
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(MAX_ARCHIVE + 1)
    if len(data) > MAX_ARCHIVE:
        raise ValueError('Test-core archive exceeds size budget')
    archive.write_bytes(data)
    verify_archive(archive, expected)
    binary = destination / ('mihomo.exe' if platform.system() == 'Windows' else 'mihomo')
    binary.write_bytes(unpack_binary(archive, filename))
    binary.chmod(0o700)
    subprocess.run([str(binary), '-v'], check=True, timeout=15)
    with Path(os.environ['GITHUB_ENV']).open('a', encoding='utf-8') as stream:
        stream.write('MIHOMO_BINARY=' + str(binary) + '\n')
    print('Verified official test-only archive:', filename, expected, flush=True)


if __name__ == '__main__':
    main()
