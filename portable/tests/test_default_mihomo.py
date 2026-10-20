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
