import io
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

from scripts.verify_macos_archive import archive_records, verify_extracted


@unittest.skipUnless(os.name == 'posix', 'Requires POSIX symlink and executable-mode semantics')
class MacOSArchiveIntegrityTests(unittest.TestCase):
    def make_archive(self, root, extra=None):
        tree = root / 'tree'
        native = tree / 'PSPortalProxy.app/Contents/Resources/native'
        native.mkdir(parents=True)
        code = tree / 'PSPortalProxy.app/Contents/MacOS'
        code.mkdir()
        (code / 'psportal-native').write_bytes(b'executable')
        (code / 'psportal-native').chmod(0o755)
        (native / 'corresponding-source.tar.gz').write_bytes(b'source')
        (native / 'psportal-native').symlink_to('../../MacOS/psportal-native')
        (code / 'native').symlink_to('../Resources/native', target_is_directory=True)
        archive = root / 'app.tar.gz'
        with tarfile.open(archive, 'w:gz') as stream:
            stream.add(tree / 'PSPortalProxy.app', arcname='PSPortalProxy.app')
            if extra:
                stream.addfile(extra, io.BytesIO(b'x') if extra.isfile() else None)
        return archive, tree

    def test_real_layout_aliases_files_and_modes_are_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive, tree = self.make_archive(Path(tmp))
            records = archive_records(archive)
            self.assertEqual(len(verify_extracted(tree, records)), 64)
            self.assertEqual(sum(item['type'] == 'symlink' for item in records.values()), 2)

    def test_changed_bytes_modes_links_and_extra_files_are_rejected(self):
        for mutation in ('bytes', 'mode', 'link', 'extra'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                archive, tree = self.make_archive(Path(tmp))
                records = archive_records(archive)
                native = tree / 'PSPortalProxy.app/Contents/MacOS/psportal-native'
                if mutation == 'bytes':
                    native.write_bytes(b'altered')
                elif mutation == 'mode':
                    native.chmod(0o644)
                elif mutation == 'link':
                    alias = tree / 'PSPortalProxy.app/Contents/MacOS/native'
                    alias.unlink()
                    alias.symlink_to('/tmp')
                else:
                    (tree / 'extra').write_bytes(b'extra')
                with self.assertRaises(ValueError):
                    verify_extracted(tree, records)

    def test_unsafe_tar_paths_hardlinks_and_special_modes_are_rejected(self):
        for name, kind, target, mode in (
                ('../escape', tarfile.REGTYPE, '', 0o644),
                ('/absolute', tarfile.REGTYPE, '', 0o644),
                ('alias', tarfile.SYMTYPE, '../outside', 0o777),
                ('hardlink', tarfile.LNKTYPE, 'PSPortalProxy.app', 0o644),
                ('special', tarfile.FIFOTYPE, '', 0o644),
                ('setuid', tarfile.REGTYPE, '', 0o4755),
                ('PSPortalProxy.app/Contents/MacOS/native/overwrite', tarfile.REGTYPE, '', 0o644)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                member = tarfile.TarInfo(name)
                member.type, member.linkname, member.mode = kind, target, mode
                member.size = 1 if member.isfile() else 0
                archive, _ = self.make_archive(Path(tmp), member)
                with self.assertRaises(ValueError):
                    archive_records(archive)
