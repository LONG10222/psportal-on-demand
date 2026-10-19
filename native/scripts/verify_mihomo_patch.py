#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Verify the complete pinned local module, including unchanged upstream assets."""
import base64
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = 'github.com/metacubex/mihomo'
VERSION = 'v1.19.32'
UPSTREAM_SUM = 'h1:uD7ZC3P77isWD554NNvtee65L+99+/C5hyc+Lk8rVEk='
COMMIT = '88dcbf7f1614a67c3b36b848ee3592dfa92ada36'
MODIFIED = ['adapter/outboundgroup/selector.go', 'common/queue/queue.go',
            'log/log.go', 'tunnel/connection.go', 'tunnel/tunnel.go']
ADDED = {'log/log_concurrency_test.go', 'NOTICE-PSPORTAL-PATCH.md',
         'tunnel/ingress.go', 'tunnel/ingress_test.go', 'common/queue/queue_concurrency_test.go',
         'adapter/outboundgroup/selector_concurrency_test.go'}
PATCHES = ['0001-atomic-log-level.patch', '0002-ingress-quiescence.patch',
           '0003-queue-synchronization.patch', '0004-selector-synchronization.patch']


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_relative(name):
    path = pathlib.PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or not name or '\\' in name:
        raise ValueError('Invalid replacement source path: ' + name)
    return name


def verify(root=None):
    root = pathlib.Path(root) if root is not None else ROOT / 'third_party' / 'mihomo'
    metadata = root / 'PSPORTAL-PATCHES'
    provenance = json.loads((metadata / 'PROVENANCE.json').read_text())
    if (provenance['module'], provenance['version'], provenance['upstream_commit'],
            provenance['upstream_module_sum']) != (MODULE, VERSION, COMMIT, UPSTREAM_SUM):
        raise ValueError('Replacement upstream identity does not match the reviewed pin')
    if provenance['omitted_upstream_files']:
        raise ValueError('Complete upstream source is required')
    original = {}
    for line in (metadata / 'UPSTREAM-FILES.sha256').read_text().splitlines():
        digest, name = line.split('  ', 1)
        safe_relative(name)
        if name in original or len(digest) != 64:
            raise ValueError('Invalid upstream file inventory')
        bytes.fromhex(digest)
        original[name] = digest
    if len(original) != provenance['upstream_file_count']:
        raise ValueError('Upstream file count changed')
    # Go's module h1 digest can be recomputed from the immutable file-hash list.
    canonical = ''.join(f'{digest}  {MODULE}@{VERSION}/{name}\n'
                        for name, digest in sorted(original.items())).encode()
    h1 = 'h1:' + base64.b64encode(hashlib.sha256(canonical).digest()).decode()
    if h1 != UPSTREAM_SUM:
        raise ValueError('Upstream inventory checksum mismatch')
    expected = dict(original)
    if [item['path'] for item in provenance['modified_files']] != MODIFIED:
        raise ValueError('Unexpected upstream production modification')
    for item in provenance['modified_files']:
        name = safe_relative(item['path'])
        if original[name] != item['upstream_sha256']:
            raise ValueError('Modified-file upstream identity mismatch')
        expected[name] = item['local_sha256']
    added = {item['path']: item['sha256'] for item in provenance['added_files']}
    if set(added) != ADDED:
        raise ValueError('Unexpected derivative source additions')
    expected.update(added)
    if provenance['patches'] != PATCHES or set(provenance['metadata_sha256']) != {'README.md', 'UPSTREAM-FILES.sha256', *PATCHES}:
        raise ValueError('Unexpected patch metadata')
    expected.update({'PSPORTAL-PATCHES/' + safe_relative(name): digest
                     for name, digest in provenance['metadata_sha256'].items()})
    expected['PSPORTAL-PATCHES/PROVENANCE.json'] = sha256(metadata / 'PROVENANCE.json')
    found = set()
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlink in local replacement: ' + str(path))
        if path.is_file():
            name = path.relative_to(root).as_posix()
            found.add(name)
            if name not in expected or sha256(path) != expected[name]:
                raise ValueError('Unreviewed or changed replacement file: ' + name)
    if found != set(expected):
        raise ValueError('Missing replacement source: ' + ', '.join(sorted(set(expected) - found)))
    return provenance


if __name__ == '__main__':
    value = verify()
    print(f"PASS: complete {MODULE}@{VERSION} source, reviewed synchronization/lifecycle patches and provenance")
