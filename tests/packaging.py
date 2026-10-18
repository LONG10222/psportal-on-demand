#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

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

    def test_optional_luci_sources_and_commands(self):
        for relative in ('controller/portalproxy.lua', 'model/cbi/portalproxy.lua'):
            self.assertTrue((ROOT / 'luci' / relative).is_file())
            self.assertIn(relative, (ROOT / 'install.sh').read_text())
            self.assertIn(relative, (ROOT / 'uninstall.sh').read_text())
        shell = (ROOT / 'files/portalproxy').read_text()
        for command in ('nodes)', 'nodes-refresh)', 'prefer)', 'subscription-update)', 'apply)'):
            self.assertIn(command, shell)
        self.assertNotIn('subscription_url', (ROOT / 'src/nodes.lua').read_text())

    def test_repository_has_no_runtime_payloads(self):
        forbidden = {'.env', 'api-header', 'api-secret', 'status.json', 'policy.json', 'config.yaml'}
        for path in ROOT.rglob('*'):
            if '.git' in path.parts or not path.is_file():
                continue
            self.assertNotIn(path.name, forbidden, path)
            self.assertNotIn(path.suffix, {'.gz', '.zip', '.key'}, path)
            self.assertNotRegex(path.read_text(errors='replace'), r'(?m)^-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----', path)

if __name__ == '__main__':
    unittest.main()
