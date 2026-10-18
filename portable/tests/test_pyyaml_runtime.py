"""Fail-closed pinned YAML module, binary, license and source coverage."""
import copy
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from scripts import pyyaml_runtime as yaml_runtime
from scripts.audit_linux_runtime import identify_elf
from yaml_packaging_fixtures import add_yaml_evidence


class YamlPackagingTests(unittest.TestCase):
    def fixture(self, system='win32'):
        report = dict(runtime={}, binaries=[], files=[], symlinks=[])
        add_yaml_evidence(report, system)
        return report

    def retained_fixture(self, root):
        import io
        shutil.copytree(yaml_runtime.SOURCE, root)
        review = yaml_runtime.manifest()
        for name in review['sources']:
            with tarfile.open(root / name, 'w:gz') as stream:
                for notice, spec in review['notices'].items():
                    if spec['source_archive'] == name:
                        data = (yaml_runtime.SOURCE / notice).read_bytes()
                        member = tarfile.TarInfo(spec['archive_member'])
                        member.size = len(data)
                        stream.addfile(member, io.BytesIO(data))
            review['sources'][name]['sha256'] = yaml_runtime.digest(root / name)
        patched = patch.object(yaml_runtime, 'manifest', return_value=review)
        patched.start()
        self.addCleanup(patched.stop)
        return review

    def test_all_sources_notices_and_recipe_are_retained_exactly(self):
        review = yaml_runtime.verified_source_files()
        self.assertEqual(len(review['python_modules']), 17)
        self.assertEqual(set(review['wheels']), {'win32', 'linux', 'darwin'})
        self.assertEqual(set(review['sources']), {'pyyaml-6.0.3.tar.gz', 'yaml-0.2.5.tar.gz'})
        self.assertEqual((yaml_runtime.ROOT / 'docs/PyYAML-LICENSE.txt').read_bytes(), (yaml_runtime.SOURCE / 'PyYAML-LICENSE.txt').read_bytes())

    def test_missing_or_modified_source_license_recipe_and_manifest_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'retained'
            review = self.retained_fixture(root)
            for name in [*review['sources'], *review['notices'], review['build_recipe']['filename'], 'manifest.json']:
                path = root / name
                original = path.read_bytes()
                path.write_bytes(original + b'changed')
                with self.subTest(name=name), self.assertRaises(ValueError): yaml_runtime.verified_source_files(root, require_sources=True)
                path.write_bytes(original)
                path.unlink()
                with self.subTest(missing=name), self.assertRaises((ValueError, FileNotFoundError)): yaml_runtime.verified_source_files(root, require_sources=True)
                path.write_bytes(original)

    def test_frozen_python_mapping_requires_every_reviewed_module_and_exact_origin(self):
        report = self.fixture()
        yaml_runtime.verify_python_inventory(report, 'win32')
        for mutation in ('missing', 'extra', 'hash', 'origin', 'duplicate', 'unreviewed', 'extension', 'license'):
            changed = copy.deepcopy(report)
            if mutation == 'missing': changed['collected_dependencies'].pop()
            elif mutation == 'extra': changed['collected_dependencies'].append(dict(destination='yaml.unreviewed',type='PYMODULE',source='x',sha256='a'*64))
            elif mutation == 'hash': changed['collected_dependencies'][0]['sha256'] = 'a'*64
            elif mutation == 'origin': changed['collected_dependencies'][0]['source'] = 'C:/other/yaml.py'
            elif mutation == 'duplicate': changed['collected_dependencies'].append(changed['collected_dependencies'][0])
            elif mutation == 'unreviewed': changed['runtime']['pyyaml']['reviewed'] = False
            elif mutation == 'extension': changed['runtime']['pyyaml']['extension']['sha256'] = 'a'*64
            else: changed['runtime']['pyyaml']['installed_license']['sha256'] = 'a'*64
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): yaml_runtime.verify_python_inventory(changed, 'win32')

    def test_retained_scope_must_match_actual_inventory(self):
        evidence = self.fixture()['runtime']['pyyaml']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'retained'
            self.retained_fixture(root)
            (root / 'runtime-scope.json').write_text(json.dumps(evidence))
            yaml_runtime.verify_retained_notices(root, evidence)
            changed = copy.deepcopy(evidence)
            changed['extension']['source'] = 'other.dll'
            with self.assertRaises(ValueError): yaml_runtime.verify_retained_notices(root, changed)

    def test_linux_extension_is_separately_owned_and_changed_or_unknown_elf_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original, bundled = root / 'installed.so', root / 'bundled.so'
            original.write_bytes(b'\x7fELF reviewed fixture')
            bundled.write_bytes(original.read_bytes())
            evidence = dict(reviewed=True, extension=dict(path='yaml/_yaml.fixture.so', source=str(original), sha256=yaml_runtime.digest(original)))
            item, package = identify_elf(evidence['extension']['path'], bundled, evidence, usr=root / 'usr')
            self.assertIsNone(package)
            self.assertEqual(item['owner'], 'PyYAML 6.0.3 / LibYAML 0.2.5')
            self.assertEqual(len(item['notices']), 2)
            for change in ('bundled', 'origin', 'unreviewed', 'unknown'):
                original.write_bytes(b'\x7fELF reviewed fixture')
                bundled.write_bytes(original.read_bytes())
                changed = copy.deepcopy(evidence)
                relative = evidence['extension']['path']
                if change == 'bundled': bundled.write_bytes(b'\x7fELF changed')
                elif change == 'origin': original.write_bytes(b'\x7fELF changed')
                elif change == 'unreviewed': changed['reviewed'] = False
                else: relative = 'yaml/unknown.so'
                with self.subTest(change=change), self.assertRaises(ValueError): identify_elf(relative, bundled, changed, usr=root / 'usr')

    def test_missing_debian_owner_or_license_stays_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / 'libX11.so.6'
            bundled.write_bytes(b'\x7fELF fixture')
            evidence = dict(extension=dict(path='yaml/_yaml.fixture.so'))
            with self.assertRaises(ValueError): identify_elf('libX11.so.6', bundled, evidence, usr=root)
            origin = root / 'lib/x86_64-linux-gnu/libX11.so.6'
            origin.parent.mkdir(parents=True)
            origin.write_bytes(bundled.read_bytes())
            with self.assertRaises(ValueError): identify_elf('libX11.so.6', bundled, evidence, usr=root)
            notice = root / 'share/doc/libx11-6/copyright'
            notice.parent.mkdir(parents=True)
            notice.write_text('complete fixture notice')
            record, package = identify_elf('libX11.so.6', bundled, evidence, usr=root)
            self.assertEqual(package, 'libx11-6')
            self.assertEqual(record['owner'], 'Debian:libx11-6')

    def test_final_zip_and_tar_bind_all_sources_notices_and_scope(self):
        import io
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            retained = root / 'retained'
            self.retained_fixture(retained)
            (retained / 'runtime-scope.json').write_text(json.dumps(self.fixture()['runtime']['pyyaml']))
            for format in ('zip', 'tar.gz', 'mac.tar.gz'):
                prefix = ('licenses/' if format.startswith('mac') else 'PSPortalProxy/licenses/') + 'pyyaml-6.0.3/'
                for mutation in ('none', 'missing', 'changed', 'duplicate'):
                    archive = root / ('fixture.' + format)
                    payloads = [(prefix + path.name, path.read_bytes()) for path in retained.iterdir() if path.is_file()]
                    if mutation == 'missing': payloads.pop()
                    elif mutation == 'changed': payloads[0] = (payloads[0][0], b'modified')
                    elif mutation == 'duplicate': payloads.append(payloads[0])
                    if format == 'zip':
                        import warnings
                        with warnings.catch_warnings(), zipfile.ZipFile(archive, 'w') as stream:
                            warnings.simplefilter('ignore', UserWarning)
                            for name, data in payloads: stream.writestr(name, data)
                    else:
                        with tarfile.open(archive, 'w:gz') as stream:
                            for name, data in payloads:
                                member = tarfile.TarInfo(name)
                                member.size = len(data)
                                stream.addfile(member, io.BytesIO(data))
                    if mutation == 'none': yaml_runtime.verify_archive_notices(archive, retained, macos=format.startswith('mac'))
                    else:
                        with self.subTest(format=format, mutation=mutation), self.assertRaises(ValueError):
                            yaml_runtime.verify_archive_notices(archive, retained, macos=format.startswith('mac'))

    def test_source_fetch_reuses_exact_cache_and_never_overwrites_modified_file(self):
        import hashlib
        from scripts.fetch_yaml_sources import fetch_sources
        data = b'pinned source fixture'
        review = dict(sources={'fixture.tar.gz': dict(url='https://files.pythonhosted.org/fixture.tar.gz', sha256=hashlib.sha256(data).hexdigest())})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'fixture.tar.gz').write_bytes(data)
            with patch('urllib.request.urlopen', side_effect=AssertionError('Network must not be used')):
                fetch_sources(root, review=review)
            (root / 'fixture.tar.gz').write_bytes(b'modified')
            with self.assertRaises(ValueError): fetch_sources(root, review=review)
            self.assertEqual((root / 'fixture.tar.gz').read_bytes(), b'modified')

    def test_source_fetch_rejects_wrong_hash_and_unapproved_redirect(self):
        import hashlib
        import io
        from scripts.fetch_yaml_sources import fetch_sources
        data = b'pinned source fixture'
        review = dict(sources={'fixture.tar.gz': dict(url='https://files.pythonhosted.org/fixture.tar.gz', sha256=hashlib.sha256(data).hexdigest())})
        class Response(io.BytesIO):
            def __init__(self, payload, url):
                super().__init__(payload)
                self.url = url
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for payload, url in ((b'changed', 'https://files.pythonhosted.org/file'), (data, 'http://files.pythonhosted.org/file'), (data, 'https://unapproved.invalid/file')):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    fetch_sources(root, review=review, opener=lambda *a, **kw: Response(payload, url))
                self.assertEqual(list(root.iterdir()), [])
            fetch_sources(root, review=review, opener=lambda *a, **kw: Response(data, review['sources']['fixture.tar.gz']['url']))
            self.assertEqual((root / 'fixture.tar.gz').read_bytes(), data)
