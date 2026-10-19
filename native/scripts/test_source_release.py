# SPDX-License-Identifier: GPL-3.0-only
import contextlib
import io
import pathlib
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import source_release


class CorrespondingSourceTests(unittest.TestCase):
    def test_android_full_core_and_binding_are_archived_before_vendor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            for name in source_release.SOURCE_DIRECTORIES:
                (root / name).mkdir()
                (root / name / 'source.go').write_text('// exact source\n')
            (root / 'assets/branding').mkdir(parents=True)
            (root / 'assets/branding/starpass-original.png').write_bytes(b'original artwork fixture')
            (root / 'assets/branding/manifest.json').write_text('{"source": "fixture"}\n', encoding='utf-8')
            (root / 'scripts/generate_brand_assets.py').write_text('# conversion recipe fixture\n', encoding='utf-8')
            for name in ('.gitignore', 'go.mod', 'go.sum', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'README.md', 'config.example.json'):
                (root / name).write_text('fixture\n')
            (root / 'android' / 'private.p12').write_bytes(b'not a real key')
            replacement = root / 'third_party' / 'mihomo'
            (replacement / 'PSPORTAL-PATCHES').mkdir(parents=True)
            (replacement / 'log').mkdir()
            (replacement / 'unreferenced_upstream_package').mkdir()
            for name in ('go.mod', 'LICENSE', 'NOTICE-PSPORTAL-PATCH.md', 'log/log.go',
                         'PSPORTAL-PATCHES/PROVENANCE.json', 'PSPORTAL-PATCHES/0001-atomic-log-level.patch',
                         'unreferenced_upstream_package/source.go'):
                (replacement / name).write_text('exact replacement fixture\n')
            (replacement / 'Meta.png').write_bytes(b'upstream binary fixture')
            (replacement / '.env').write_text('not a real secret\n')
            (replacement / 'build').mkdir()
            (replacement / 'build' / 'generated.bin').write_bytes(b'generated fixture')
            def vendor(command, *, cwd, check):
                self.assertEqual(command, ['verified-go', 'mod', 'vendor'])
                self.assertTrue(check)
                for name in ('androidcore', 'androidmobile', 'mobile', 'engine'):
                    self.assertEqual((cwd / name / 'source.go').read_text(), '// exact source\n')
                self.assertEqual((cwd / 'third_party/mihomo/log/log.go').read_text(), 'exact replacement fixture\n')
                self.assertEqual((cwd / 'third_party/mihomo/Meta.png').read_bytes(), b'upstream binary fixture')
                self.assertEqual((cwd / 'assets/branding/starpass-original.png').read_bytes(), b'original artwork fixture')
                (cwd / 'vendor').mkdir()
                (cwd / 'vendor' / 'modules.txt').write_text('exact dependency fixture\n')
            with patch.object(source_release, 'ROOT', root), patch.object(source_release.subprocess, 'run', side_effect=vendor), patch.object(source_release.verify_mihomo_patch, 'verify') as verify, patch('sys.argv', ['source_release.py', '--go', 'verified-go']), contextlib.redirect_stdout(io.StringIO()):
                source_release.main()
                verify.assert_called_once()
                self.assertEqual(verify.call_args.args[0].parts[-2:], ('third_party', 'mihomo'))
            with tarfile.open(root / 'dist' / 'psportal-native-corresponding-source.tar.gz') as archive:
                names = set(archive.getnames())
                for path in ('androidcore/source.go', 'androidmobile/source.go', 'mobile/source.go', 'vendor/modules.txt',
                             'third_party/mihomo/go.mod', 'third_party/mihomo/LICENSE', 'third_party/mihomo/log/log.go',
                             'third_party/mihomo/Meta.png', 'third_party/mihomo/PSPORTAL-PATCHES/PROVENANCE.json',
                             'third_party/mihomo/PSPORTAL-PATCHES/0001-atomic-log-level.patch',
                             'third_party/mihomo/unreferenced_upstream_package/source.go',
                             'assets/branding/starpass-original.png', 'assets/branding/manifest.json',
                             'scripts/generate_brand_assets.py'):
                    self.assertIn('psportal-native-source/' + path, names)
                self.assertNotIn('psportal-native-source/android/private.p12', names)
                self.assertNotIn('psportal-native-source/third_party/mihomo/.env', names)
                self.assertNotIn('psportal-native-source/third_party/mihomo/build/generated.bin', names)

    def test_invalid_replacement_fails_before_vendor_or_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            for name in ('.gitignore', 'go.mod', 'go.sum', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'README.md', 'config.example.json'):
                (root / name).write_text('fixture\n')
            with patch.object(source_release, 'ROOT', root), patch.object(source_release.subprocess, 'run') as run, patch.object(source_release.verify_mihomo_patch, 'verify', side_effect=ValueError('source mismatch')), patch('sys.argv', ['source_release.py']):
                with self.assertRaisesRegex(ValueError, 'source mismatch'):
                    source_release.main()
            run.assert_not_called()
            self.assertFalse((root / 'dist' / 'psportal-native-corresponding-source.tar.gz').exists())

    def test_vendor_cannot_silently_change_dependency_pins(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            for name in ('.gitignore', 'go.mod', 'go.sum', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'README.md', 'config.example.json'):
                (root / name).write_text('fixture\n')
            def vendor(command, *, cwd, check):
                (cwd / 'go.sum').write_text('changed dependency sum\n')
            with patch.object(source_release, 'ROOT', root), patch.object(source_release.subprocess, 'run', side_effect=vendor), patch.object(source_release.verify_mihomo_patch, 'verify'), patch('sys.argv', ['source_release.py']):
                with self.assertRaisesRegex(RuntimeError, 'Dependency closure changed'):
                    source_release.main()
            self.assertEqual((root / 'go.sum').read_text(), 'fixture\n')
            self.assertFalse((root / 'dist' / 'psportal-native-corresponding-source.tar.gz').exists())


if __name__ == '__main__':
    unittest.main()
