"""Retain a pinned Windows default core together with matching upstream source."""
import hashlib
from pathlib import Path
import shutil
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


def retain(folder, binary, source):
    license_text = verify(binary, source)
    folder = Path(folder)
    notices = folder / 'licenses' / ('mihomo-' + VERSION)
    notices.mkdir(parents=True, exist_ok=True)
    shutil.copy2(binary, folder / 'mihomo.exe')
    shutil.copy2(source, notices / ('mihomo-' + VERSION + '-source.zip'))
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
