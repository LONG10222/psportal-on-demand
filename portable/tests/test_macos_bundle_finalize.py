import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.macos_bundle_finalize import arrange_native, finalize_bundle, sha256


@unittest.skipUnless(os.name == 'posix', 'Requires POSIX symlink and executable-mode semantics')
class MacOSBundleFinalizeTests(unittest.TestCase):
    def fixture(self, root):
        app = root / 'PSPortalProxy.app'
        for directory in ('MacOS', 'Resources/native', 'Frameworks', '_CodeSignature'):
            (app / 'Contents' / directory).mkdir(parents=True)
        (app / 'Contents/MacOS/PSPortalProxy').write_bytes(bytes.fromhex('cffaedfe') + b'app')
        native = app / 'Contents/Resources/native/psportal-native'
        native.write_bytes(bytes.fromhex('cffaedfe') + b'native')
        native.chmod(0o755)
        (native.parent / 'corresponding-source.tar.gz').write_bytes(b'source')
        (app / 'Contents/Frameworks/runtime.so').write_bytes(bytes.fromhex('cffaedfe') + b'runtime')
        (app / 'Contents/_CodeSignature/CodeResources').write_bytes(plistlib.dumps(
            {'files2': {'MacOS/psportal-native': {'cdhash': b'hash'}}}))
        return app, sha256(native)

    def test_layout_preserves_native_and_existing_frozen_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, digest = self.fixture(Path(tmp))
            native = arrange_native(app, digest)
            self.assertEqual(sha256(native), digest)
            self.assertEqual(native.stat().st_mode & 0o777, 0o755)
            discovered = app / 'Contents/MacOS/native/psportal-native'
            self.assertEqual(discovered.resolve(), native.resolve())
            self.assertEqual((discovered.parent / 'corresponding-source.tar.gz').read_bytes(), b'source')
            self.assertEqual(os.readlink(app / 'Contents/MacOS/native'), '../Resources/native')
            self.assertEqual(os.readlink(app / 'Contents/Resources/native/psportal-native'), '../../MacOS/psportal-native')

    def test_outer_only_sign_and_strict_checks_preserve_nested_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app, digest = self.fixture(root)
            calls = []
            def run(argv, **kwargs):
                calls.append(argv)
                if '--sign' in argv:
                    (app / 'Contents/MacOS/PSPortalProxy').write_bytes(bytes.fromhex('cffaedfe') + b'new-app-signature')
                return subprocess.CompletedProcess(argv, 0, '', '')
            with patch('scripts.macos_bundle_finalize.sys.platform', 'darwin'), patch(
                    'scripts.macos_bundle_finalize.subprocess.run', side_effect=run):
                report = finalize_bundle(app, root / 'seal.json', digest)
            self.assertTrue(report['passed'])
            signing = [cmd for cmd in calls if '--sign' in cmd]
            self.assertEqual(len(signing), 1)
            self.assertNotIn('--deep', signing[0])
            self.assertIn('--timestamp=none', signing[0])
            self.assertEqual(sum('--deep' in cmd and '--strict' in cmd for cmd in calls), 2)
            self.assertEqual(report['native_sha256'], digest)
            self.assertEqual(json.loads((root / 'seal.json').read_text()), report)

    def test_nested_rewrite_and_final_verification_failure_are_hard_errors(self):
        for tamper in (True, False):
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                app, digest = self.fixture(root)
                signed = False
                def run(argv, **kwargs):
                    nonlocal signed
                    if '--sign' in argv:
                        signed = True
                        if tamper:
                            (app / 'Contents/Frameworks/runtime.so').write_bytes(bytes.fromhex('cffaedfe') + b'tampered')
                    code = 1 if signed and '--verify' in argv and not tamper else 0
                    return subprocess.CompletedProcess(argv, code, '', 'invalid signature' if code else '')
                with patch('scripts.macos_bundle_finalize.sys.platform', 'darwin'), patch(
                        'scripts.macos_bundle_finalize.subprocess.run', side_effect=run):
                    with self.assertRaises((RuntimeError, ValueError)):
                        finalize_bundle(app, root / 'seal.json', digest)
                self.assertFalse(json.loads((root / 'seal.json').read_text())['passed'])

    def test_wrong_native_hash_or_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, digest = self.fixture(Path(tmp))
            with self.assertRaises(ValueError):
                arrange_native(app, '0' * 64)
            (app / 'Contents/MacOS/psportal-native').write_bytes(b'unexpected')
            with self.assertRaises(ValueError):
                arrange_native(app, digest)
