# SPDX-License-Identifier: GPL-3.0-only
import pathlib
import shutil
import tempfile
import unittest
import verify_mihomo_patch


class LocalPatchIntegrityTests(unittest.TestCase):
    def test_complete_real_source_and_patch_series_match_provenance(self):
        value = verify_mihomo_patch.verify()
        self.assertEqual(value['upstream_file_count'], 1009)
        self.assertEqual(value['omitted_upstream_files'], [])
        self.assertEqual({item['path'] for item in value['reviewed_upstream_binary_assets']},
                         {'Meta.png', 'docs/logo.png'})
        self.assertEqual(value['patches'], verify_mihomo_patch.PATCHES)
        self.assertEqual([item['path'] for item in value['modified_files']], verify_mihomo_patch.MODIFIED)

    def test_changes_missing_assets_and_extra_files_fail_closed(self):
        original = verify_mihomo_patch.ROOT / 'third_party' / 'mihomo'
        with tempfile.TemporaryDirectory() as temporary:
            copy = pathlib.Path(temporary) / 'mihomo'
            shutil.copytree(original, copy)
            for name in ('log/log.go', 'common/queue/queue.go', 'tunnel/ingress.go', 'tunnel/tunnel.go', 'LICENSE', 'Meta.png'):
                path = copy / name
                contents = path.read_bytes()
                path.write_bytes(contents + b'changed')
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'changed replacement'):
                    verify_mihomo_patch.verify(copy)
                path.write_bytes(contents)
            extra = copy / '.env'
            extra.write_text('not a real secret\n')
            with self.assertRaisesRegex(ValueError, 'Unreviewed'):
                verify_mihomo_patch.verify(copy)
            extra.unlink()
            (copy / 'docs/logo.png').unlink()
            with self.assertRaisesRegex(ValueError, 'Missing replacement'):
                verify_mihomo_patch.verify(copy)


if __name__ == '__main__':
    unittest.main()
