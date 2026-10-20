#!/usr/bin/env python3
import hashlib
import tarfile
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_UPSTREAM_CONFIGS = {
    'native/third_party/mihomo/docs/config.yaml':
        'e57eea09cdfb1851acf2cf130b6ef318827ac02fb6c2ebc64e2c77647e21a363',
    'native/third_party/mihomo/.github/release/config.yaml':
        '65696f4b2ac4ec31987b3783b712a2452418cbe464c23b648fca2a515e478377',
}

class PackagingTests(unittest.TestCase):
    def test_shell_syntax(self):
        files = [ROOT / 'install.sh', ROOT / 'uninstall.sh', ROOT / 'files/portalproxy']
        files += list((ROOT / 'files').glob('*.init'))
        files += list((ROOT / 'tests').glob('*.sh'))
        for path in files:
            subprocess.run(['sh', '-n', str(path)], check=True)

    def test_staged_install_preserves_configuration_and_does_not_start_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'root'
            core = Path(tmp) / 'fake-core'
            core.write_text('#!/bin/sh\nexit 0\n')
            core.chmod(0o700)
            cmd = ['sh', str(ROOT / 'install.sh'), '--root', str(target), '--core', str(core)]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE)
            configuration = target / 'etc/config/portalproxy'
            self.assertIn("option enabled '0'", configuration.read_text())
            configuration.write_text("config proxy 'main'\n option enabled '0'\n # retained fixture\n")
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE)
            self.assertIn('retained fixture', configuration.read_text())
            self.assertTrue(list((target / 'etc/portalproxy-backups').glob('*.tar.gz')))
            self.assertFalse((target / 'etc/rc.d').exists())
            self.assertEqual((target / 'usr/libexec/portalproxy/mihomo').read_bytes(), core.read_bytes())
            self.assertEqual(os.stat(configuration).st_mode & 0o777, 0o600)
            subprocess.run(['sh', str(ROOT / 'uninstall.sh'), '--root', str(target)], check=True, stdout=subprocess.PIPE)
            self.assertTrue(configuration.exists())
            self.assertFalse((target / 'usr/libexec/portalproxy').exists())
            subprocess.run(['sh', str(ROOT / 'uninstall.sh'), '--root', str(target), '--purge'], check=True, stdout=subprocess.PIPE)
            self.assertFalse(configuration.exists())

    def test_linked_install_never_requires_or_copies_a_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'root'
            subprocess.run(['sh', str(ROOT / 'install.sh'), '--root', str(target), '--openclash'], check=True, stdout=subprocess.PIPE)
            self.assertFalse((target / 'usr/libexec/portalproxy/mihomo').exists())
            self.assertIn("option core_mode 'openclash'", (target / 'etc/config/portalproxy').read_text())
            self.assertFalse((target / 'etc/rc.d').exists())
            self.assertFalse((target / 'etc/config/openclash').exists())
            self.assertTrue((target / 'usr/libexec/portalproxy/openclash.lua').is_file())

    def test_external_service_is_never_managed(self):
        for directory in ('src', 'files', 'luci'):
            for path in (ROOT / directory).rglob('*'):
                if path.is_file():
                    self.assertNotRegex(path.read_text(), r'/etc/init.d/openclash\s+(?:start|stop|restart|reload|enable|disable)')
        core = (ROOT / 'files/portalproxy-core.init').read_text()
        self.assertIn('c.core_mode~="openclash"', core)
        self.assertIn('/etc/portalproxy/policy.json', core)
        self.assertNotIn('uci -q get portalproxy.main.core_mode', core)
        for path in ('src/nodes.lua', 'src/update-subscription.lua'):
            self.assertIn("core_mode')~='openclash'", (ROOT / path).read_text())

    def test_router_source_bundle_is_reproducible_and_core_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / 'first.tar.gz', Path(tmp) / 'second.tar.gz'
            for output in (first, second):
                subprocess.run(['python3', str(ROOT / 'scripts/build-router-source.py'), str(output)], check=True, stdout=subprocess.PIPE)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with tarfile.open(first) as archive:
                members = archive.getmembers()
                self.assertTrue(all(m.isfile() and not m.issym() and not m.islnk() for m in members))
                names = {m.name for m in members}
                self.assertIn('starpass-router-source/src/openclash.lua', names)
                template_name = 'starpass-router-source/luci/view/portalproxy/onboarding.htm'
                self.assertIn(template_name, names)
                self.assertEqual(archive.extractfile(template_name).read(), (ROOT / 'luci/view/portalproxy/onboarding.htm').read_bytes())
                self.assertFalse(any('mihomo' in name or 'api-secret' in name or 'policy.json' in name for name in names))
                manifest = archive.extractfile('starpass-router-source/SHA256SUMS').read().decode()
                for line in manifest.splitlines():
                    expected, name = line.split('  ', 1)
                    self.assertEqual(hashlib.sha256(archive.extractfile('starpass-router-source/' + name).read()).hexdigest(), expected)

    def test_optional_luci_sources_and_commands(self):
        for relative in ('controller/portalproxy.lua', 'model/cbi/portalproxy.lua', 'view/portalproxy/onboarding.htm'):
            self.assertTrue((ROOT / 'luci' / relative).is_file())
            self.assertIn(relative, (ROOT / 'install.sh').read_text())
            self.assertIn(relative, (ROOT / 'uninstall.sh').read_text())
        shell = (ROOT / 'files/portalproxy').read_text()
        for command in ('nodes)', 'nodes-refresh)', 'prefer)', 'subscription-update)', 'apply)'):
            self.assertIn(command, shell)
        self.assertNotIn('subscription_url', (ROOT / 'src/nodes.lua').read_text())

    def test_luci_onboarding_installs_and_stays_read_only(self):
        template = (ROOT / 'luci/view/portalproxy/onboarding.htm').read_text()
        self.assertIn('class="starpass-guide"', template)
        self.assertIn('prefers-color-scheme:dark', template)
        self.assertIn('max-width:480px', template)
        for forbidden in ('<script', '<form', 'onclick=', 'fetch(', '<%=', '<%--', 'subscription_url'):
            self.assertNotIn(forbidden, template)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'root'
            (target / 'usr/lib/lua/luci').mkdir(parents=True)
            subprocess.run(['sh', str(ROOT / 'install.sh'), '--root', str(target), '--openclash'], check=True, stdout=subprocess.PIPE)
            installed = target / 'usr/lib/lua/luci/view/portalproxy/onboarding.htm'
            self.assertEqual(installed.read_text(), template)
            self.assertEqual(installed.stat().st_mode & 0o777, 0o644)
            self.assertFalse((target / 'etc/rc.d').exists())
            subprocess.run(['sh', str(ROOT / 'uninstall.sh'), '--root', str(target)], check=True, stdout=subprocess.PIPE)
            self.assertFalse(installed.exists())
            self.assertTrue((target / 'etc/config/portalproxy').exists())

    def assert_no_runtime_payload(self, path, root):
        forbidden = {'.env', 'api-header', 'api-secret', 'status.json', 'policy.json', 'config.yaml'}
        expected = PUBLIC_UPSTREAM_CONFIGS.get(path.relative_to(root).as_posix())
        if expected is not None:
            # Preserve immutable public upstream examples in corresponding
            # source, without allowing another config or changed fixture bytes.
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected, path)
        else:
            self.assertNotIn(path.name, forbidden, path)
        self.assertNotIn(path.suffix, {'.gz', '.zip', '.key'}, path)
        self.assertNotRegex(path.read_text(errors='replace'), r'(?m)^-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----', path)

    def test_repository_has_no_runtime_payloads(self):
        for path in ROOT.rglob('*'):
            if '.git' in path.parts or not path.is_file():
                continue
            self.assert_no_runtime_payload(path, ROOT)

    def test_public_upstream_config_requires_exact_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in PUBLIC_UPSTREAM_CONFIGS:
                with self.subTest(path=name):
                    original = (ROOT / name).read_bytes()
                    fixture = root / name
                    fixture.parent.mkdir(parents=True, exist_ok=True)
                    fixture.write_bytes(original)
                    self.assert_no_runtime_payload(fixture, root)
                    fixture.write_bytes(original + b'\n# changed fixture\n')
                    with self.assertRaises(AssertionError):
                        self.assert_no_runtime_payload(fixture, root)

    def test_public_upstream_config_does_not_allow_other_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for source in PUBLIC_UPSTREAM_CONFIGS:
                original = (ROOT / source).read_bytes()
                for name in ('config.yaml', 'native/third_party/mihomo/config.yaml',
                             'native/third_party/mihomo/docs/other/config.yaml',
                             *(path for path in PUBLIC_UPSTREAM_CONFIGS if path != source)):
                    with self.subTest(source=source, path=name):
                        fixture = root / name
                        fixture.parent.mkdir(parents=True, exist_ok=True)
                        fixture.write_bytes(original)
                        with self.assertRaises(AssertionError):
                            self.assert_no_runtime_payload(fixture, root)

if __name__ == '__main__':
    unittest.main()
