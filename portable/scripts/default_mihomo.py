"""Retain a pinned Windows default core together with matching upstream source."""
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import zipfile

VERSION = 'v1.19.32'
BINARY_SHA256 = '04f8d7fc2b314771e1ecbf15951d59f0e1cb7914503c88cfb6972ff6a824e314'
SOURCE_SHA256 = '135f16d1e309f8c0ce2303c86fd38a38624a229e7185ceb74d1d3a4f0d4b66f1'
COMMIT = '88dcbf7f1614a67c3b36b848ee3592dfa92ada36'


def verify(binary, source):
    for path, digest in ((Path(binary), BINARY_SHA256), (Path(source), SOURCE_SHA256)):
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Default Mihomo binary/source does not match the pinned release.')
    with zipfile.ZipFile(source) as archive:
        license_text = archive.read('mihomo-1.19.32/LICENSE')
    if not license_text:
        raise ValueError('Default Mihomo source is missing its license.')
    return license_text


def retain(folder, binary, source, complete_source=None):
    license_text = verify(binary, source)
    folder = Path(folder)
    notices = folder / 'licenses' / ('mihomo-' + VERSION)
    notices.mkdir(parents=True, exist_ok=True)
    shutil.copy2(binary, folder / 'mihomo.exe')
    shutil.copy2(source, notices / ('mihomo-' + VERSION + '-source.zip'))
    if complete_source is not None:
        verify_complete_source(complete_source, source)
        shutil.copy2(complete_source, notices / 'corresponding-source.tar.gz')
    (notices / 'LICENSE.txt').write_bytes(license_text)
    (notices / 'SOURCE.md').write_text(
        '# Default Mihomo\n\nVersion: ' + VERSION + '\nCommit: ' + COMMIT + '\n\n'
        'Unmodified official Windows amd64-compatible executable.\n'
        'Binary SHA-256: ' + BINARY_SHA256 + '\n'
        'Matching upstream source is included in this directory.\n'
        'Source SHA-256: ' + SOURCE_SHA256 + '\n\n'
        'Release: https://github.com/MetaCubeX/mihomo/releases/tag/' + VERSION + '\n'
        'Source: https://github.com/MetaCubeX/mihomo/tree/' + COMMIT + '\n'
        'Dependency versions and checksums are recorded in upstream go.mod/go.sum.\n', encoding='utf-8')


def verify_complete_source(complete_source, source):
    """Verify pinned upstream files plus vendored dependency metadata, never extract."""
    prefix = 'mihomo-' + VERSION.lstrip('v') + '/'
    with tarfile.open(complete_source, 'r:gz') as complete, zipfile.ZipFile(source) as upstream:
        members = complete.getmembers()
        names = [m.name for m in members]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate complete-source members')
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts or not (member.isdir() or member.isfile()):
                raise ValueError('Unsafe complete-source member')
        for item in upstream.infolist():
            if item.is_dir():
                continue
            member = complete.getmember(item.filename)
            if not member.isfile() or complete.extractfile(member).read() != upstream.read(item):
                raise ValueError('Complete source differs from pinned upstream source')
        modules = complete.extractfile(prefix + 'vendor/modules.txt').read()
        if not modules.strip():
            raise ValueError('Complete source lacks vendored dependency metadata')
        manifest = json.load(complete.extractfile(prefix + 'VENDOR-SHA256.json'))
        actual = {m.name[len(prefix):]: hashlib.sha256(complete.extractfile(m).read()).hexdigest()
                  for m in members if m.isfile() and m.name.startswith(prefix + 'vendor/')}
        if not actual or manifest != actual:
            raise ValueError('Vendored source inventory/checksum mismatch')
        for line in modules.decode('utf-8').splitlines():
            package = line.strip()
            if not package or package.startswith('#'):
                continue
            package_prefix = 'vendor/' + package + '/'
            if not any(name.startswith(package_prefix) and '/' not in name[len(package_prefix):]
                       and name.endswith('.go') for name in actual):
                raise ValueError('Vendored dependency package source missing: ' + package)
    return hashlib.sha256(Path(complete_source).read_bytes()).hexdigest()
