"""Offline checks for the pinned CI-only official-core fetch helper."""
import gzip
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'ci/fetch_test_core.py'
spec = importlib.util.spec_from_file_location('fetch_test_core', SCRIPT)
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


class FetchTestCoreTests(unittest.TestCase):
    def test_checksum_rejects_changed_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'archive'; p.write_bytes(b'fixture')
            fetch.verify_archive(p, hashlib.sha256(b'fixture').hexdigest())
            with self.assertRaises(ValueError):
                fetch.verify_archive(p, '0' * 64)

    def test_gzip_payload_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'archive.gz'; p.write_bytes(gzip.compress(b'fixture'))
            self.assertEqual(fetch.unpack_binary(p, p.name), b'fixture')
            p.write_bytes(gzip.compress(b''))
            with self.assertRaises(ValueError):
                fetch.unpack_binary(p, p.name)

    def test_zip_reads_bytes_without_extracting_member_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'archive.zip'
            with zipfile.ZipFile(p, 'w') as archive:
                archive.writestr('../fixture.exe', b'fixture')
            self.assertEqual(fetch.unpack_binary(p, p.name), b'fixture')
            self.assertEqual(list(Path(tmp).iterdir()), [p])
            with zipfile.ZipFile(p, 'a') as archive:
                archive.writestr('second.exe', b'other')
            with self.assertRaises(ValueError):
                fetch.unpack_binary(p, p.name)
