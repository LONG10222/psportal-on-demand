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

    @unittest.skipIf(os.name == 'nt', 'Creating symlinks requires Windows privileges')
    def test_install_rejects_redirected_ancestors_and_target_before_writing(self):
        payload = self.archive()
        for component in ('config-root', 'cores', 'version', 'target', 'dangling-target'):
            with self.subTest(component=component), tempfile.TemporaryDirectory() as tmp:
                # Canonicalize the test fixture only, not the path being checked.
                root = Path(tmp).resolve()
                config_root = root / 'settings'
                config_root.mkdir()
                config = config_root / 'config.json'
                target = setup.managed_path(config)
                outside = root / 'outside'
                outside.mkdir()
                victim = outside / 'existing.exe'
                victim.write_bytes(b'previous')
                link = {'config-root': config_root, 'cores': config_root / 'cores',
                        'version': target.parent, 'target': target,
                        'dangling-target': target}[component]
                if component == 'config-root':
                    config_root.rmdir()
                else:
                    link.parent.mkdir(parents=True, exist_ok=True)
                destination = (victim if component == 'target' else
                               outside / 'missing.exe' if component == 'dangling-target' else outside)
                link.symlink_to(destination, target_is_directory=component not in ('target', 'dangling-target'))
                with patch.object(setup, 'can_install', return_value=True), \
                        patch.object(setup, 'SHA256', hashlib.sha256(payload).hexdigest()), \
                        patch.object(setup.urllib.request, 'urlopen', return_value=io.BytesIO(payload)):
                    with self.assertRaisesRegex(ValueError, 'symbolic link'):
                        setup.install_core(config)
                self.assertEqual(victim.read_bytes(), b'previous')
                self.assertEqual(list(outside.iterdir()), [victim],
                                 'Reject redirected paths before creating directories or files')

    @unittest.skipIf(os.name == 'nt', 'POSIX system-alias path spellings')
    def test_only_exact_macos_system_aliases_are_allowed(self):
        for alias in ('/var', '/tmp'):
            target = Path(alias) / 'private-user-dir' / 'cores' / setup.VERSION / 'mihomo.exe'
            with self.subTest(alias=alias), \
                    patch.object(Path, 'is_symlink', lambda path: path == Path(alias)), \
                    patch.object(Path, 'resolve', return_value=Path('/private' + alias)):
                with patch.object(setup.sys, 'platform', 'darwin'):
                    setup._validate_install_path(target)
                with patch.object(setup.sys, 'platform', 'linux'):
                    with self.assertRaisesRegex(ValueError, 'symbolic link'):
                        setup._validate_install_path(target)
            with self.subTest(alias=alias, destination='unexpected'), \
                    patch.object(setup.sys, 'platform', 'darwin'), \
                    patch.object(Path, 'is_symlink', lambda path: path == Path(alias)), \
                    patch.object(Path, 'resolve', return_value=Path('/unexpected')):
                with self.assertRaisesRegex(ValueError, 'symbolic link'):
                    setup._validate_install_path(target)

    @unittest.skipIf(os.name == 'nt', 'POSIX system-alias path spellings')
    def test_macos_alias_does_not_hide_nested_symlink(self):
        target = Path('/var/private-user-dir/cores') / setup.VERSION / 'mihomo.exe'
        with patch.object(setup.sys, 'platform', 'darwin'), \
                patch.object(Path, 'is_symlink',
                             lambda path: path in (Path('/var'), Path('/var/private-user-dir/cores'))), \
                patch.object(Path, 'resolve', return_value=Path('/private/var')):
            with self.assertRaisesRegex(ValueError, 'symbolic link'):
                setup._validate_install_path(target)

    def test_junction_ancestors_block_install_and_managed_discovery(self):
        payload = self.archive()
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp).resolve() / 'settings' / 'config.json'
            target = setup.managed_path(config)
            target.parent.mkdir(parents=True)
            target.write_bytes(b'previous')
            for junction in (config.parent, config.parent / 'cores', target.parent, target):
                with self.subTest(junction=junction), \
                        patch.object(Path, 'is_junction', lambda path: path == junction, create=True), \
                        patch.object(setup, 'can_install', return_value=True), \
                        patch.object(setup, 'SHA256', hashlib.sha256(payload).hexdigest()), \
                        patch.object(setup.urllib.request, 'urlopen', return_value=io.BytesIO(payload)):
                    with self.assertRaisesRegex(ValueError, 'junction'):
                        setup.install_core(config)
                    self.assertEqual(target.read_bytes(), b'previous')
                    with patch.object(setup.sys, 'platform', 'win32'), \
                            patch.object(setup.sys, 'frozen', False, create=True), \
                            patch.dict(os.environ, {}, clear=True):
                        self.assertIsNone(setup.discover_core(config))

    def test_junction_probe_failure_is_not_treated_as_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp).resolve() / 'config.json'
            with patch.object(Path, 'is_junction', side_effect=OSError('probe failed'), create=True):
                with self.assertRaisesRegex(OSError, 'probe failed'):
                    setup._validate_install_path(setup.managed_path(config))
                with patch.object(setup.sys, 'platform', 'win32'), \
                        patch.object(setup.sys, 'frozen', False, create=True), \
                        patch.dict(os.environ, {}, clear=True):
                    self.assertIsNone(setup.discover_core(config))

    def test_unsupported_system_never_downloads(self):
        with patch.object(setup, 'can_install', return_value=False), patch.object(setup.urllib.request, 'urlopen') as fetch:
            with self.assertRaises(ValueError): setup.install_core(Path('unused.json'))
            fetch.assert_not_called()
