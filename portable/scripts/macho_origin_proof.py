"""Strict, scratch-only proof of PyInstaller's known Mach-O transformations.

The original and packaged files are never changed. On temporary copies only,
apply pinned PyInstaller architecture/install-name processing to the original,
remove signatures from both copies, and require full normalized byte equality.
All tool commands and before/after hashes are retained as diagnostic evidence.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def target_rpath(destination):
    path = PurePosixPath(destination)
    if path.is_absolute() or '..' in path.parts or not path.name:
        raise ValueError('Transformation destination must be a safe relative path')
    return str(PurePosixPath('@loader_path', *('..' for _ in path.parent.parts)))


def prove_macho_origin(original, packaged, destination, kind):
    original, packaged = Path(original), Path(packaged)
    evidence = dict(verified=False, method='pinned-pyinstaller-transform-and-signature-removal',
                    source=str(original), packaged=str(packaged), commands=[])
    if sys.platform != 'darwin':
        evidence['error'] = 'Mach-O origin proof requires native macOS tools'
        return evidence
    if kind not in ('BINARY', 'EXTENSION', 'EXECUTABLE'):
        evidence['error'] = 'Unsupported PyInstaller origin type'
        return evidence
    try:
        if importlib.metadata.version('pyinstaller') != '6.16.0':
            raise ValueError('Only reviewed PyInstaller 6.16.0 transformations are accepted')
        from PyInstaller.utils import osx as osxutils
        _, architectures = osxutils.get_binary_architectures(str(packaged))
        if len(architectures) != 1 or architectures[0] not in ('arm64', 'x86_64'):
            raise ValueError('Origin proof requires an exact single-architecture desktop build')
        evidence.update(architecture=architectures[0], source_sha256=file_hash(original),
                        packaged_sha256=file_hash(packaged), pyinstaller='6.16.0')
        rpath = target_rpath(destination)
        evidence['target_rpath'] = rpath if kind != 'EXECUTABLE' else None
        real_subprocess = osxutils.subprocess

        class RecordedTools:
            def __getattr__(self, name):
                return getattr(real_subprocess, name)

            def run(self, command, **kwargs):
                tool = Path(command[0]).name
                if tool not in ('lipo', 'install_name_tool', 'codesign'):
                    raise ValueError('Unreviewed normalization tool: ' + tool)
                command = ['/usr/bin/' + tool, *map(str, command[1:])]
                evidence['commands'].append(command)
                return real_subprocess.run(command, **dict(kwargs, timeout=30))

        with tempfile.TemporaryDirectory(prefix='psportal-macho-proof-') as temporary:
            root = Path(temporary)
            source_copy = root / 'source' / packaged.name
            bundle_copy = root / 'packaged' / packaged.name
            source_copy.parent.mkdir(); bundle_copy.parent.mkdir()
            shutil.copyfile(original, source_copy)
            shutil.copyfile(packaged, bundle_copy)
            # Substitute only the utility module's subprocess interface, not
            # the global subprocess module; restore it even when a tool fails.
            osxutils.subprocess = RecordedTools()
            try:
                osxutils.binary_to_target_arch(str(source_copy), architectures[0])
                if kind != 'EXECUTABLE':
                    osxutils.set_dylib_dependency_paths(str(source_copy), rpath)
                osxutils.remove_signature_from_binary(str(source_copy))
                osxutils.remove_signature_from_binary(str(bundle_copy))
            finally:
                osxutils.subprocess = real_subprocess
            evidence.update(normalized_source_sha256=file_hash(source_copy),
                            normalized_packaged_sha256=file_hash(bundle_copy))
            if evidence['source_sha256'] != file_hash(original) or evidence['packaged_sha256'] != file_hash(packaged):
                raise ValueError('Original or packaged input changed during the proof')
            evidence['verified'] = evidence['normalized_source_sha256'] == evidence['normalized_packaged_sha256']
            if not evidence['verified']:
                evidence['error'] = 'Normalized bytes differ; origin remains unverified'
    except Exception as error:
        evidence['error'] = str(error)
    return evidence
