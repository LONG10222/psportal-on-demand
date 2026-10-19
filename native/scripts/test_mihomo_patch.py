# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch as mock_patch
import verify_mihomo_patch


def apply_patch_bytes(root, contents, *, reverse=False):
    # Native Python's drive-letter paths are not portable input filenames for
    # POSIX patch builds on Windows. Pass exact bytes on stdin and prevent the
    # Windows C runtime from translating line endings in patched source files.
    command = ['patch', '--batch', '--fuzz=0', '--no-backup-if-mismatch', '-p1']
    if sys.platform == 'win32':
        command.append('--binary')
    if reverse:
        command.append('--reverse')
    result = subprocess.run(command, cwd=root, input=contents,
                            capture_output=True, timeout=10)
    if result.returncode:
        diagnostics = (result.stdout + result.stderr).decode('utf-8', errors='replace')
        raise AssertionError(f'patch exited {result.returncode}: {diagnostics}')


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
            patch_bytes = patch.read_bytes()
            apply_patch_bytes(root, patch_bytes, reverse=True)
            self.assertEqual(hashlib.sha256((root / names[0]).read_bytes()).hexdigest(), pinned)
            self.assertFalse((root / names[1]).exists())
            apply_patch_bytes(root, patch_bytes)
            self.assertEqual({name: (root / name).read_bytes() for name in names}, local)

    def test_patch_uses_binary_stdin_without_platform_specific_filename(self):
        root = pathlib.PureWindowsPath(r'D:\a\checkout with spaces')
        contents = b'--- a/source.go\n+++ b/source.go\n@@ -1 +1 @@\n-old\n+new\n'
        with mock_patch.object(sys, 'platform', 'win32'), \
                mock_patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'', b'')) as run:
            apply_patch_bytes(root, contents, reverse=True)
        command = run.call_args.args[0]
        self.assertIn('--binary', command)
        self.assertIn('--fuzz=0', command)
        self.assertIn('--reverse', command)
        self.assertNotIn('-i', command)
        self.assertEqual(run.call_args.kwargs['input'], contents)
        self.assertEqual(run.call_args.kwargs['cwd'], root)
        self.assertFalse(run.call_args.kwargs.get('text', False))

    def test_patch_failure_preserves_diagnostics(self):
        failed = subprocess.CompletedProcess([], 3, b'patching source.go\n', b'input error\n')
        with mock_patch.object(subprocess, 'run', return_value=failed):
            with self.assertRaisesRegex(AssertionError, r'patch exited 3: patching source.go\ninput error'):
                apply_patch_bytes(pathlib.Path('.'), b'fixture')

    @unittest.skipUnless(shutil.which('patch'), 'patch utility is required for reproduction check')
    def test_patch_rejects_mismatched_hunk_without_fuzz(self):
        contents = b'--- a/source.go\n+++ b/source.go\n@@ -1 +1 @@\n-expected\n+new\n'
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / 'source.go'
            source.write_bytes(b'different\n')
            with self.assertRaisesRegex(AssertionError, r'patch exited [1-9]'):
                apply_patch_bytes(root, contents)
            self.assertEqual(source.read_bytes(), b'different\n')

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
