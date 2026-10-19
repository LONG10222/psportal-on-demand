#!/usr/bin/env python3
"""Exact PyYAML/LibYAML ownership, source and license evidence for frozen apps.

A pip-installed extension is not a Debian or CPython library. Its separate
upstream wheel hash review never exempts it from the host's binary/import audit.
No downloads or source builds are performed by this module.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'notices/pyyaml-6.0.3'
SOURCE_CACHE = ROOT / 'build/dependency-sources'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def manifest():
    return json.loads((SOURCE / 'manifest.json').read_text(encoding='utf-8'))


def verify_source_archives(directory, review=None):
    """Verify cached archives against versioned locks and retained full notices."""
    review = review or manifest()
    for name, expected in review['sources'].items():
        path = directory / name
        require(path.is_file() and not path.is_symlink() and digest(path) == expected['sha256'],
                'Missing or modified YAML source archive; run scripts/fetch_yaml_sources.py: ' + name)
    for name, expected in review['notices'].items():
        with tarfile.open(directory / expected['source_archive'], 'r:gz') as archive:
            require(archive.extractfile(expected['archive_member']).read() == (SOURCE / name).read_bytes(),
                    'Source archive notice differs from retained upstream notice: ' + name)


def verified_source_files(directory=SOURCE, *, require_sources=False):
    """Verify tracked notices/recipe; distribution checks also require sources."""
    review = manifest()
    for name, expected in {**review['notices'],
                           review['build_recipe']['filename']: review['build_recipe']}.items():
        path = directory / name
        require(path.is_file() and not path.is_symlink() and digest(path) == expected['sha256'],
                'Missing or modified PyYAML/LibYAML notice or build recipe: ' + name)
    require((directory / 'manifest.json').read_bytes() == (SOURCE / 'manifest.json').read_bytes(),
            'Packaged YAML review manifest differs')
    if require_sources:
        verify_source_archives(directory, review)
    return review


def installed_evidence(*, strict=False):
    """Bind installed modules/license/extension to independently retained wheel bytes."""
    review = verified_source_files()
    distribution = importlib.metadata.distribution('PyYAML')
    require(distribution.version == review['version'], 'Unreviewed PyYAML version')
    files = {str(item).replace('\\', '/'): item for item in distribution.files or ()}
    def installed(name):
        require(name in files, 'PyYAML distribution does not own: ' + name)
        path = Path(distribution.locate_file(files[name])).resolve(strict=True)
        require(path.is_file(), 'Missing installed PyYAML component: ' + name)
        return path
    license_path = installed('pyyaml-6.0.3.dist-info/licenses/LICENSE')
    require(digest(license_path) == review['notices']['PyYAML-LICENSE.txt']['sha256'],
            'Installed PyYAML license differs from upstream release')
    modules = {}
    for name, expected in review['python_modules'].items():
        path = installed(expected['path'])
        require(digest(path) == expected['sha256'], 'Installed PyYAML module differs: ' + name)
        modules[name] = dict(source=str(path), sha256=digest(path))
    import yaml
    from yaml import _yaml
    require(yaml.__version__ == review['version'] and yaml.__with_libyaml__ is True and
            _yaml.get_version_string() == review['libyaml_version'], 'Unreviewed PyYAML/LibYAML runtime')
    extension = Path(_yaml.__file__).resolve(strict=True)
    owned = [name for name in files if name.startswith('yaml/') and name.endswith(('.so', '.pyd'))]
    require(len(owned) == 1 and installed(owned[0]) == extension,
            'Imported YAML extension is not the unique installed distribution extension')
    expected = review['wheels'].get(sys.platform)
    arch = {'x86_64': 'amd64', 'AMD64': 'amd64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(platform.machine())
    reviewed = bool(expected and sys.implementation.cache_tag == 'cpython-313' and
                    arch == expected['architecture'] and owned[0] == expected['extension_path'] and
                    digest(extension) == expected['extension_sha256'])
    require(not strict or reviewed, 'YAML extension requires exact wheel/platform review')
    return dict(version=review['version'], libyaml_version=review['libyaml_version'],
                platform=sys.platform, architecture=arch, reviewed=reviewed,
                extension=dict(path=owned[0], source=str(extension), sha256=digest(extension)),
                python_modules=modules, installed_license=dict(source=str(license_path), sha256=digest(license_path)))


def retain_notices(destination, *, strict=False):
    evidence = installed_evidence(strict=strict)
    verify_source_archives(SOURCE_CACHE)
    shutil.copytree(SOURCE, destination, dirs_exist_ok=True)
    for name in manifest()['sources']:
        shutil.copyfile(SOURCE_CACHE / name, destination / name)
    (destination / 'runtime-scope.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    return evidence


def verify_python_inventory(report, target_platform):
    """Reject absent, injected or modified frozen YAML modules and extension origins."""
    review = manifest()
    evidence = report['runtime'].get('pyyaml', {})
    expected = review['wheels'][target_platform]
    require(evidence.get('reviewed') is True and evidence.get('version') == review['version'] and
            evidence.get('libyaml_version') == review['libyaml_version'] and
            evidence.get('platform') == target_platform and evidence.get('architecture') == expected['architecture'],
            'Missing exact installed PyYAML/LibYAML runtime review')
    extension = evidence.get('extension', {})
    require(extension.get('path') == expected['extension_path'] and
            extension.get('sha256') == expected['extension_sha256'], 'Unreviewed YAML extension')
    require(evidence.get('installed_license', {}).get('sha256') == review['notices']['PyYAML-LICENSE.txt']['sha256'],
            'Installed YAML license evidence differs')
    installed = evidence.get('python_modules', {})
    require(set(installed) == set(review['python_modules']), 'Missing installed YAML Python-module evidence')
    collected = {}
    for item in report.get('collected_dependencies', []):
        name = item['destination']
        if name == 'yaml' or name.startswith('yaml.'):
            if item['type'].startswith('PYMODULE'):
                require(name not in collected, 'Duplicate frozen YAML module')
                collected[name] = item
    require(set(collected) == set(review['python_modules']), 'Frozen YAML module mapping is incomplete or unexpected')
    for name, item in collected.items():
        require(item['sha256'] == installed[name].get('sha256') == review['python_modules'][name]['sha256'] and
                item['source'] == installed[name].get('source'), 'Frozen YAML module differs from its reviewed installed source: ' + name)
    return expected, extension


def verify_retained_notices(directory, evidence):
    verified_source_files(directory, require_sources=True)
    retained = json.loads((directory / 'runtime-scope.json').read_text(encoding='utf-8'))
    require(retained == evidence and retained.get('reviewed') is True,
            'Retained YAML scope differs from installed/frozen inventory')


def verify_build_modules(build, evidence):
    """Prove the actual Analysis TOC owns every frozen YAML Python module."""
    import ast
    try:
        from .inventory_desktop_runtime import toc_entries
    except ImportError:
        from inventory_desktop_runtime import toc_entries
    entries = list(toc_entries(ast.literal_eval((build / 'Analysis-00.toc').read_text(encoding='utf-8'))))
    modules = {name: (source, kind) for name, source, kind in entries
               if (name == 'yaml' or name.startswith('yaml.')) and kind.startswith('PYMODULE')}
    require(set(modules) == set(manifest()['python_modules']), 'Frozen YAML Python module set differs from review')
    for name, (source, kind) in modules.items():
        require(str(Path(source).resolve()) == evidence['python_modules'][name]['source'] and
                digest(source) == evidence['python_modules'][name]['sha256'],
                'Frozen YAML module does not match installed source: ' + name)
    extensions = [(name, source) for name, source, kind in entries
                  if kind == 'EXTENSION' and name.replace('\\', '/').startswith('yaml/')]
    require(len(extensions) == 1 and extensions[0][0].replace('\\', '/') == evidence['extension']['path'] and
            str(Path(extensions[0][1]).resolve()) == evidence['extension']['source'] and
            digest(extensions[0][1]) == evidence['extension']['sha256'],
            'Frozen YAML extension does not match installed source')


def verify_archive_notices(archive, retained, *, macos=False):
    """Require every retained YAML source/notice/scope byte in the final archive."""
    import zipfile
    verified_source_files(retained, require_sources=True)
    prefix = ('licenses/' if macos else 'PSPortalProxy/licenses/') + 'pyyaml-6.0.3/'
    expected = {prefix + path.name: path.read_bytes() for path in retained.iterdir() if path.is_file()}
    require(prefix + 'runtime-scope.json' in expected, 'YAML runtime scope missing before archive')
    if str(archive).endswith('.zip'):
        with zipfile.ZipFile(archive) as stream:
            members = [item for item in stream.infolist() if not item.is_dir() and item.filename.startswith(prefix)]
            require(len(members) == len(expected) and {item.filename for item in members} == set(expected),
                    'YAML ZIP member set differs from retained notices/sources')
            require(all(stream.read(item) == expected[item.filename] for item in members), 'YAML ZIP notice/source bytes changed')
    else:
        with tarfile.open(archive, 'r:gz') as stream:
            members = [item for item in stream.getmembers() if not item.isdir() and item.name.startswith(prefix)]
            require(len(members) == len(expected) and {item.name for item in members} == set(expected) and
                    all(item.isfile() for item in members), 'YAML tar member set differs from retained notices/sources')
            require(all(stream.extractfile(item).read() == expected[item.name] for item in members),
                    'YAML tar notice/source bytes changed')
