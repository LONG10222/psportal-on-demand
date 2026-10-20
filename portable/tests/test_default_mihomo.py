import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import default_mihomo


class DefaultMihomoBundleTests(unittest.TestCase):
    def test_bundle_retains_matching_source_and_license_and_rejects_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary, source, output = root / 'official.exe', root / 'source.zip', root / 'dist'
            binary.write_bytes(b'MZsynthetic-never-executed')
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('mihomo-1.19.32/LICENSE', b'fixture license')
            with patch.object(default_mihomo, 'BINARY_SHA256', hashlib.sha256(binary.read_bytes()).hexdigest()), \
                    patch.object(default_mihomo, 'SOURCE_SHA256', hashlib.sha256(source.read_bytes()).hexdigest()):
                default_mihomo.retain(output, binary, source)
                self.assertEqual((output / 'mihomo.exe').read_bytes(), binary.read_bytes())
                notice = output / 'licenses' / ('mihomo-' + default_mihomo.VERSION)
                self.assertEqual((notice / 'LICENSE.txt').read_bytes(), b'fixture license')
                self.assertEqual((notice / ('mihomo-' + default_mihomo.VERSION + '-source.zip')).read_bytes(), source.read_bytes())
                self.assertIn(default_mihomo.COMMIT, (notice / 'SOURCE.md').read_text())
                binary.write_bytes(b'wrong release')
                with self.assertRaisesRegex(ValueError, 'pinned release'):
                    default_mihomo.retain(output, binary, source)
                self.assertEqual((output / 'mihomo.exe').read_bytes(), b'MZsynthetic-never-executed')

    def test_complete_source_preserves_all_upstream_and_requires_vendor(self):
        import io
        import json
        import tarfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, complete = root / 'source.zip', root / 'complete.tar.gz'
            prefix = 'mihomo-1.19.32/'
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr(prefix + 'LICENSE', b'upstream license')
                archive.writestr(prefix + 'go.mod', b'module example.test')
            def create(mod=b'module example.test', vendor=True, unsafe=False):
                with tarfile.open(complete, 'w:gz') as archive:
                    entries = {prefix + 'LICENSE': b'upstream license', prefix + 'go.mod': mod}
                    if vendor:
                        entries[prefix + 'vendor/modules.txt'] = b'# dependency v1.0.0\ndependency/pkg\n'
                        entries[prefix + 'vendor/dependency/pkg/main.go'] = b'package pkg'
                        manifest = {name[len(prefix):]: hashlib.sha256(value).hexdigest() for name, value in entries.items() if name.startswith(prefix + 'vendor/')}
                        entries[prefix + 'VENDOR-SHA256.json'] = json.dumps(manifest).encode()
                    if unsafe: entries['../escape'] = b'bad'
                    for name, payload in entries.items():
                        info = tarfile.TarInfo(name); info.size = len(payload)
                        archive.addfile(info, io.BytesIO(payload))
            create()
            self.assertEqual(default_mihomo.verify_complete_source(complete, source),
                             hashlib.sha256(complete.read_bytes()).hexdigest())
            create(mod=b'changed')
            with self.assertRaisesRegex(ValueError, 'differs'):
                default_mihomo.verify_complete_source(complete, source)
            create(vendor=False)
            with self.assertRaises(KeyError):
                default_mihomo.verify_complete_source(complete, source)
            create(unsafe=True)
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                default_mihomo.verify_complete_source(complete, source)
