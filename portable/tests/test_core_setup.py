import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from portalproxy import core_setup as setup


class CoreSetupTests(unittest.TestCase):
    def test_discovery_prefers_configured_then_managed_then_stable_clash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'config.json'
            stable = root / 'Clash Verge' / 'verge-mihomo.exe'
            stable.parent.mkdir(); stable.write_bytes(b'stable')
            (stable.parent / 'verge-mihomo-alpha.exe').write_bytes(b'alpha')
            with patch.object(setup.sys, 'platform', 'win32'), patch.dict(os.environ,
                    {'ProgramW6432':tmp, 'ProgramFiles':tmp, 'LOCALAPPDATA':tmp}):
                self.assertEqual(setup.discover_core(config), str(stable))
                managed = setup.managed_path(config)
                managed.parent.mkdir(parents=True); managed.write_bytes(b'managed')
                self.assertEqual(setup.discover_core(config), str(managed))
                custom = root / 'custom.exe'; custom.write_bytes(b'custom')
                self.assertEqual(setup.discover_core(config, str(custom)), str(custom))
                self.assertIsNone(setup.discover_core(config, str(root / 'missing.exe')))
                self.assertIsNone(setup.discover_core(config, 42))

    def archive(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('../escape.exe', b'MZfixture-core')
        return data.getvalue()

    def test_frozen_default_is_preferred_to_an_installed_client_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / 'package'; bundle.mkdir()
            core = bundle / 'mihomo.exe'; core.write_bytes(b'fixture default')
            stable = root / 'Clash Verge' / 'verge-mihomo.exe'
            stable.parent.mkdir(); stable.write_bytes(b'fixture installed')
            with patch.object(setup.sys, 'platform', 'win32'), \
                    patch.object(setup.sys, 'frozen', True, create=True), \
                    patch.object(setup.sys, 'executable', str(bundle / 'PSPortalProxy.exe')), \
                    patch.dict(os.environ, {'ProgramW6432':tmp, 'ProgramFiles':tmp, 'LOCALAPPDATA':tmp}):
                self.assertEqual(setup.discover_core(root / 'config.json'), str(core))

    def test_install_checks_hash_and_extracts_bytes_without_archive_paths(self):
        payload = self.archive()
        with tempfile.TemporaryDirectory() as tmp, patch.object(setup, 'can_install', return_value=True), \
                patch.object(setup, 'SHA256', hashlib.sha256(payload).hexdigest()), \
                patch.object(setup.urllib.request, 'urlopen', return_value=io.BytesIO(payload)) as fetch:
            config = Path(tmp) / 'config.json'
            result = Path(setup.install_core(config))
            self.assertEqual(result, setup.managed_path(config))
            self.assertEqual(result.read_bytes(), b'MZfixture-core')
            self.assertFalse((Path(tmp) / 'escape.exe').exists())
            fetch.assert_called_once_with(setup.URL, timeout=30)

    def test_bad_download_does_not_replace_existing_core(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(setup, 'can_install', return_value=True), \
                patch.object(setup.urllib.request, 'urlopen', return_value=io.BytesIO(b'bad')):
            config = Path(tmp) / 'config.json'
            target = setup.managed_path(config)
            target.parent.mkdir(parents=True); target.write_bytes(b'previous')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                setup.install_core(config)
            self.assertEqual(target.read_bytes(), b'previous')

    def test_unsupported_system_never_downloads(self):
        with patch.object(setup, 'can_install', return_value=False), patch.object(setup.urllib.request, 'urlopen') as fetch:
            with self.assertRaises(ValueError): setup.install_core(Path('unused.json'))
            fetch.assert_not_called()
