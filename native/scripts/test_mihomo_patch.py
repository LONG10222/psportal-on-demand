# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import pathlib
import shutil
import subprocess
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

    @unittest.skipUnless(shutil.which('patch'), 'patch utility is required for reproduction check')
    def test_selector_patch_round_trip_matches_pinned_upstream(self):
        original = verify_mihomo_patch.ROOT / 'third_party' / 'mihomo'
        patch = original / 'PSPORTAL-PATCHES' / '0004-selector-synchronization.patch'
        names = ['adapter/outboundgroup/selector.go',
                 'adapter/outboundgroup/selector_concurrency_test.go']
        local = {name: (original / name).read_bytes() for name in names}
        provenance = verify_mihomo_patch.verify()
        pinned = next(item['upstream_sha256'] for item in provenance['modified_files']
                      if item['path'] == names[0])
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            for name, contents in local.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
            command = ['patch', '--batch', '--fuzz=0', '--no-backup-if-mismatch',
                       '-p1', '-i', str(patch)]
            subprocess.run(command + ['--reverse'], cwd=root, check=True,
                           capture_output=True, timeout=10)
            self.assertEqual(hashlib.sha256((root / names[0]).read_bytes()).hexdigest(), pinned)
            self.assertFalse((root / names[1]).exists())
            subprocess.run(command, cwd=root, check=True, capture_output=True, timeout=10)
            self.assertEqual({name: (root / name).read_bytes() for name in names}, local)

    def test_changes_missing_assets_and_extra_files_fail_closed(self):
        original = verify_mihomo_patch.ROOT / 'third_party' / 'mihomo'
        with tempfile.TemporaryDirectory() as temporary:
            copy = pathlib.Path(temporary) / 'mihomo'
            shutil.copytree(original, copy)
            for name in ('adapter/outboundgroup/selector.go', 'adapter/outboundgroup/selector_concurrency_test.go',
                         'PSPORTAL-PATCHES/0004-selector-synchronization.patch',
                         'log/log.go', 'common/queue/queue.go', 'tunnel/ingress.go', 'tunnel/tunnel.go', 'LICENSE', 'Meta.png'):
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
