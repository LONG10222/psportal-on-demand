#!/usr/bin/env python3
import hashlib
import shutil
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
    def test_router_scripts_are_lf_even_on_windows_checkout(self):
        for directory in ('src', 'files', 'tests'):
            for path in (ROOT / directory).rglob('*'):
                if path.is_file() and (path.suffix in ('.lua', '.sh', '.init') or path.name == 'portalproxy'):
                    self.assertNotIn(b'\r\n', path.read_bytes(), path)

    def test_no_core_install_still_allows_configuration_and_never_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'root'
            result = subprocess.run(['sh', str(ROOT / 'install.sh'), '--root', str(target)], check=True, capture_output=True, text=True)
            self.assertIn('Installed without a core', result.stdout)
            self.assertFalse((target / 'usr/libexec/portalproxy/mihomo').exists())
            self.assertIn("option enabled '0'", (target / 'etc/config/portalproxy').read_text())
            self.assertFalse((target / 'etc/rc.d').exists())

    def test_uninstall_refuses_symlink_ancestors_and_concurrent_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, outside = Path(tmp) / 'root', Path(tmp) / 'outside'
            target.mkdir(); outside.mkdir()
            (outside / 'libexec/portalproxy').mkdir(parents=True)
            sentinel = outside / 'libexec/portalproxy/keep'
            sentinel.write_text('unrelated file')
            (target / 'usr').symlink_to(outside, target_is_directory=True)
            command = ['sh', str(ROOT / 'uninstall.sh'), '--root', str(target), '--purge']
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(sentinel.read_text(), 'unrelated file')
            (target / 'usr').unlink()
            (target / '.starpass-install.lock').mkdir()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_ipk_is_reproducible_arch_all_core_free_and_preserves_configuration(self):
        import io
        with tempfile.TemporaryDirectory() as tmp:
            outputs = [Path(tmp) / name for name in ('first.ipk', 'second.ipk')]
            for output in outputs:
                subprocess.run(['python3', str(ROOT / 'scripts/build-router-ipk.py'), str(output), '--version', '0.1.0+test-1'], check=True, capture_output=True)
            raw = outputs[0].read_bytes()
            self.assertEqual(raw, outputs[1].read_bytes())
            with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
                members = {m.name.removeprefix('./'): archive.extractfile(m).read() for m in archive if m.isfile()}
            self.assertEqual(members['debian-binary'], b'2.0\n')
            with tarfile.open(fileobj=io.BytesIO(members['control.tar.gz'])) as archive:
                self.assertIn(b'Architecture: all', archive.extractfile('./control').read())
                self.assertEqual(archive.extractfile('./conffiles').read(), b'/etc/config/portalproxy\n')
                self.assertIn(b'gateway_enabled', archive.extractfile('./postinst').read())
                self.assertNotIn(b'xianniu-router start', archive.extractfile('./postinst').read())
                self.assertNotIn(b'portalproxy enable', archive.extractfile('./postinst').read())
            with tarfile.open(fileobj=io.BytesIO(members['data.tar.gz'])) as archive:
                self.assertTrue(archive.getmember('./usr/libexec/portalproxy').isdir())
                self.assertTrue(archive.getmember('./usr/lib/lua/luci/view/portalproxy').isdir())
                self.assertIn(b'starpass-form', archive.extractfile('./usr/lib/lua/luci/view/portalproxy/dashboard.htm').read())
                self.assertFalse(any(m.name.endswith('/mihomo') for m in archive))
                self.assertEqual(archive.getmember('./etc/config/portalproxy').mode, 0o600)
                self.assertIn(b"option enabled '0'", archive.extractfile('./etc/config/portalproxy').read())

    def test_router_update_guidance_is_read_only_and_preserves_config(self):
        template = (ROOT / 'luci/view/portalproxy/onboarding.htm').read_text()
        section = template.split('<details class="starpass-updates">', 1)[1].split('</details>', 1)[0]
        for expected in ['https://github.com/LONG10222/psportal-on-demand/releases',
                         'referrerpolicy="no-referrer"', 'rel="noopener noreferrer"',
                         '不执行在线更新检查', '固件和 CPU 架构',
                         '核心由 OpenClash 更新', '可能含凭据',
                         '不保证断电恢复', '不要清除配置']:
            self.assertIn(expected, section)
        for forbidden in ['<script', '<form', 'onclick=', 'fetch(', 'XMLHttpRequest', '<%=', 'os.execute']:
            self.assertNotIn(forbidden, section)

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

    def test_upgrade_backup_contains_launchers_luci_and_private_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'root'
            (target / 'usr/lib/lua/luci').mkdir(parents=True)
            command = ['sh', str(ROOT / 'install.sh'), '--root', str(target), '--openclash']
            subprocess.run(command, check=True, capture_output=True)
            private = target / 'etc/portalproxy/providers/private.yml'
            private.write_text('fixture-only-secret')
            dashboard = target / 'usr/lib/lua/luci/view/portalproxy/dashboard.htm'
            self.assertEqual(dashboard.read_bytes(), (ROOT / 'luci/view/portalproxy/dashboard.htm').read_bytes())
            old_init = (target / 'etc/init.d/portalproxy').read_bytes()
            subprocess.run(command, check=True, capture_output=True)
            archives = list((target / 'etc/portalproxy-backups').glob('*.tar.gz'))
            self.assertEqual(len(archives), 1)
            with tarfile.open(archives[0]) as archive:
                for path in ('etc/init.d/portalproxy', 'etc/init.d/portalproxy-core',
                             'usr/sbin/portalproxy', 'usr/lib/lua/luci/controller/portalproxy.lua',
                             'usr/lib/lua/luci/model/cbi/portalproxy.lua',
                             'usr/lib/lua/luci/view/portalproxy/onboarding.htm',
                             'etc/config/portalproxy', 'etc/portalproxy/providers/private.yml'):
                    self.assertIn(path, archive.getnames())
                self.assertEqual(archive.extractfile('etc/init.d/portalproxy').read(), old_init)
            self.assertEqual(archives[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(private.read_text(), 'fixture-only-secret')

    def test_upgrade_copy_failure_restores_previous_files_and_removes_added_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'root'
            command = ['sh', str(ROOT / 'install.sh'), '--root', str(target), '--openclash']
            subprocess.run(command, check=True, capture_output=True)
            # A preexisting launcher/core must survive a later partially written copy.
            (target / 'etc/init.d/portalproxy').write_text('old init fixture')
            next((target / 'usr/libexec/portalproxy').glob('*.lua')).unlink()
            before = {p.relative_to(target): p.read_bytes() for p in target.rglob('*') if p.is_file()}
            shim = Path(tmp) / 'bin'
            shim.mkdir()
            cp = shim / 'cp'
            cp.write_text('#!/bin/sh\ncase "$1:$2" in -p:*/.starpass-install.*/new/etc/init.d/portalproxy)\n'
                          '  printf broken > "$3"; exit 1;;\nesac\nexec ' + shutil.which('cp') + ' "$@"\n')
            cp.chmod(0o700)
            result = subprocess.run(command, env={**os.environ, 'PATH': str(shim) + ':' + os.environ['PATH']},
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('previous files restored', result.stderr)
            after = {p.relative_to(target): p.read_bytes() for p in target.rglob('*')
                     if p.is_file() and 'portalproxy-backups' not in p.parts}
            self.assertEqual(after, before)
            self.assertFalse((target / '.starpass-install.lock').exists())
            self.assertFalse(list(target.glob('.starpass-install.*')))
            self.assertFalse((target / 'etc/rc.d').exists())

    def test_backup_failure_never_changes_installed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'root'
            command = ['sh', str(ROOT / 'install.sh'), '--root', str(target), '--openclash']
            subprocess.run(command, check=True, capture_output=True)
            before = {p.relative_to(target): p.read_bytes() for p in target.rglob('*') if p.is_file()}
            shim = Path(tmp) / 'bin'
            shim.mkdir()
            tar = shim / 'tar'
            tar.write_text('#!/bin/sh\nexit 1\n')
            tar.chmod(0o700)
            result = subprocess.run(command, env={**os.environ, 'PATH': str(shim) + ':' + os.environ['PATH']},
                                    capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            after = {p.relative_to(target): p.read_bytes() for p in target.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            self.assertFalse((target / '.starpass-install.lock').exists())
            self.assertFalse(list((target / 'etc/portalproxy-backups').glob('*.tar.gz')))

    def test_missing_payload_fails_before_installed_files_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'root'
            subprocess.run(['sh', str(ROOT / 'install.sh'), '--root', str(target), '--openclash'],
                           check=True, capture_output=True)
            fixture = Path(tmp) / 'source'
            fixture.mkdir()
            shutil.copy(ROOT / 'install.sh', fixture)
            for directory in ('src', 'files', 'luci'):
                shutil.copytree(ROOT / directory, fixture / directory)
            (fixture / 'files/portalproxy-core.init').unlink()
            before = {p.relative_to(target): p.read_bytes() for p in target.rglob('*') if p.is_file()}
            result = subprocess.run(['sh', str(fixture / 'install.sh'), '--root', str(target), '--openclash'],
                                    capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            after = {p.relative_to(target): p.read_bytes() for p in target.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            self.assertFalse((target / '.starpass-install.lock').exists())

    def test_upgrade_refuses_symlink_config_and_concurrent_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'root'
            (target / 'etc/config').mkdir(parents=True)
            outside = Path(tmp) / 'outside'
            outside.write_text('must not touch')
            outside.chmod(0o644)
            (target / 'etc/config/portalproxy').symlink_to(outside)
            command = ['sh', str(ROOT / 'install.sh'), '--root', str(target), '--openclash']
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Symlink', result.stderr)
            self.assertEqual(outside.read_text(), 'must not touch')
            self.assertEqual(outside.stat().st_mode & 0o777, 0o644)
            (target / 'etc/config/portalproxy').unlink()
            (target / '.starpass-install.lock').mkdir()
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Another install', result.stderr)
            self.assertFalse((target / 'usr').exists())

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
        for relative in ('controller/portalproxy.lua', 'model/cbi/portalproxy.lua',
                         'view/portalproxy/onboarding.htm', 'view/portalproxy/dashboard.htm'):
            self.assertTrue((ROOT / 'luci' / relative).is_file())
            self.assertIn(relative, (ROOT / 'install.sh').read_text())
            self.assertIn(relative, (ROOT / 'uninstall.sh').read_text())
        shell = (ROOT / 'files/portalproxy').read_text()
        for command in ('nodes)', 'nodes-refresh)', 'prefer)', 'subscription-update)', 'apply)'):
            self.assertIn(command, shell)
        self.assertNotIn('subscription_url', (ROOT / 'src/nodes.lua').read_text())

    def test_luci_onboarding_installs_and_stays_read_only(self):
        template = (ROOT / 'luci/view/portalproxy/onboarding.htm').read_text()
        self.assertIn('class="starpass-help-brand"', template)
        dashboard = (ROOT / 'luci/view/portalproxy/dashboard.htm').read_text()
        self.assertIn('prefers-color-scheme:dark', dashboard)
        self.assertIn('max-width:700px', dashboard)
        for forbidden in ('<script', '<form', 'onclick=', 'fetch(', '<%=', '<%--', 'subscription_url'):
            self.assertNotIn(forbidden, template)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'root'
            (target / 'usr/lib/lua/luci').mkdir(parents=True)
            subprocess.run(['sh', str(ROOT / 'install.sh'), '--root', str(target), '--openclash'], check=True, stdout=subprocess.PIPE)
            installed = target / 'usr/lib/lua/luci/view/portalproxy/onboarding.htm'
            self.assertEqual(installed.read_text(), template)
            self.assertEqual(installed.stat().st_mode & 0o777, 0o644)
            workspace = target / 'www/luci-static/resources/starpass/accelerator_v2.js'
            self.assertEqual(workspace.read_bytes(), (ROOT / 'luci/static/accelerator.js').read_bytes())
            self.assertFalse((target / 'etc/rc.d').exists())
            subprocess.run(['sh', str(ROOT / 'uninstall.sh'), '--root', str(target)], check=True, stdout=subprocess.PIPE)
            self.assertFalse(installed.exists())
            self.assertFalse(workspace.exists())
            self.assertFalse((target / 'usr/lib/lua/luci/view/portalproxy/dashboard.htm').exists())
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
