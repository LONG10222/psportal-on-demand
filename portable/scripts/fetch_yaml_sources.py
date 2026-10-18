#!/usr/bin/env python3
"""Prepare pinned public YAML sources in a generated cache before packaging.

Existing exact files are reused offline. Modified files fail closed and are
never overwritten. No archives are extracted, installed or executed.
"""
import argparse
import hashlib
from pathlib import Path
import tempfile
import urllib.parse
import urllib.request

try:
    from .pyyaml_runtime import SOURCE_CACHE, digest, manifest, require, verify_source_archives
except ImportError:
    from pyyaml_runtime import SOURCE_CACHE, digest, manifest, require, verify_source_archives

MAX_BYTES = 8 * 1024 * 1024
ALLOWED_HOSTS = {'files.pythonhosted.org', 'pyyaml.org'}


def fetch_sources(output, *, review=None, opener=None):
    review = review or manifest()
    opener = opener or urllib.request.urlopen
    require(not output.is_symlink(), 'Source cache must not be a symlink')
    output.mkdir(parents=True, exist_ok=True)
    for name, expected in review['sources'].items():
        require(Path(name).name == name, 'Unsafe source archive name')
        target = output / name
        if target.exists() or target.is_symlink():
            require(target.is_file() and not target.is_symlink() and digest(target) == expected['sha256'],
                    'Existing source cache differs; refusing replacement: ' + name)
            continue
        parsed = urllib.parse.urlsplit(expected['url'])
        require(parsed.scheme == 'https' and parsed.hostname in ALLOWED_HOSTS and not parsed.username and not parsed.password,
                'Unreviewed source download URL')
        with opener(expected['url'], timeout=60) as response:
            final = urllib.parse.urlsplit(response.url)
            require(final.scheme == 'https' and final.hostname in ALLOWED_HOSTS, 'Unexpected source download destination')
            data = response.read(MAX_BYTES + 1)
        require(len(data) <= MAX_BYTES and hashlib.sha256(data).hexdigest() == expected['sha256'],
                'Source archive size or SHA-256 mismatch: ' + name)
        with tempfile.NamedTemporaryFile(prefix=name + '.', suffix='.part', dir=output, delete=False) as temporary:
            temporary.write(data)
            prepared = Path(temporary.name)
        try:
            # Do not overwrite a concurrent fetch or a pre-existing changed file.
            import os
            try:
                os.link(prepared, target)
            except FileExistsError:
                require(target.is_file() and not target.is_symlink() and digest(target) == expected['sha256'],
                        'Concurrent source cache differs: ' + name)
        finally:
            prepared.unlink(missing_ok=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=SOURCE_CACHE)
    args = parser.parse_args()
    verify_source_archives(fetch_sources(args.output))
    print('Verified complete pinned PyYAML and LibYAML source archives:', args.output)


if __name__ == '__main__':
    main()
