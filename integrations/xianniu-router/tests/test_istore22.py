import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from build_ipk import VERSION

ROOT = Path(__file__).resolve().parents[1]


class IStore22Compatibility(unittest.TestCase):
    def init_start(self, transparent=False, fw4=False, workspace=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'session.json'
            config.write_text('{}')
            for name in ('logger', 'nft', 'fw4'):
                if name in ('nft', 'fw4') and not fw4:
                    continue
                program = root / name
                program.write_text('#!/bin/sh\nexit 0\n')
                program.chmod(0o700)
            source = (ROOT / 'files/etc/init.d/xianniu-router').read_text()
            source = source.replace('/etc/xianniu-router/session.json', str(config))
            starpass = root / 'portalproxy.config'
            if workspace is not None:starpass.write_text('fixture')
            source = source.replace('/etc/config/portalproxy', str(starpass))
            prefix = '''
config_load() { :; }
uci() { printf '%s' "$TEST_WORKSPACE"; }
config_get_bool() {
 case "$3" in
  enabled) eval "$1=1" ;;
  transparent_enabled) eval "$1=$TEST_TRANSPARENT" ;;
 esac
}
procd_open_instance() { echo OPEN; }
procd_set_param() { printf 'SET'; printf ' <%s>' "$@"; printf '\\n'; }
procd_append_param() { printf 'APPEND'; printf ' <%s>' "$@"; printf '\\n'; }
procd_close_instance() { echo CLOSE; }
'''
            env = dict(os.environ, PATH=tmp, TEST_TRANSPARENT='1' if transparent else '0',TEST_WORKSPACE=workspace or '')
            return subprocess.run(['/bin/sh'], input=prefix + source + '\nstart_service\n',
                                  text=True, capture_output=True, env=env)

    def test_stop_waits_on_integer_only_busybox_sleep(self):
        source = (ROOT / 'files/etc/init.d/xianniu-router').read_text()
        start = source.index('service_stopped()')
        end = source.index('reload_service()', start)
        source = source[start:end].replace('/usr/bin/xianniu-router', 'cleanup')
        prefix = """
xn_stopping_pid=123
attempt=0
kill() { attempt=$((attempt + 1)); [ "$attempt" -le 3 ]; }
sleep() { [ "$1" = 1 ] || exit 88; echo WAIT; }
cleanup() { echo CLEANUP; }
"""
        result = subprocess.run(['/bin/sh'], input=prefix + source + '\nservice_stopped\n',
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['WAIT', 'WAIT', 'WAIT', 'CLEANUP'])

    def test_http_mode_has_no_firewall_or_transparent_arguments(self):
        result = self.init_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('OPEN', result.stdout)
        self.assertIn('<--uci>', result.stdout)
        for option in ('--manage-routing', '--transparent-port', '--dns-port'):
            self.assertNotIn(option, result.stdout)

    def test_explicit_start_is_independent_of_game_workspace(self):
        result=self.init_start(workspace='game')
        self.assertEqual(result.returncode,0)
        self.assertIn('OPEN',result.stdout)

    def test_accelerator_workspace_can_start_explicit_session(self):
        result=self.init_start(workspace='accelerator')
        self.assertEqual(result.returncode,0)
        self.assertIn('OPEN',result.stdout)

    def test_transparent_mode_refuses_fw3_before_launch(self):
        result = self.init_start(transparent=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('OPEN', result.stdout)

    def test_explicit_fw4_mode_keeps_original_routing_arguments(self):
        result = self.init_start(transparent=True, fw4=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for option in ('--manage-routing', '--transparent-port', '--dns-port'):
            self.assertIn(option, result.stdout)

    def test_package_defaults_to_http_without_nftables_dependency(self):
        package = ROOT / ('xianniu-router_' + VERSION + '_all.ipk')
        with tarfile.open(package) as outer:
            with tarfile.open(fileobj=io.BytesIO(outer.extractfile('./control.tar.gz').read())) as control:
                text = control.extractfile('./control').read().decode()
                depends = next(line for line in text.splitlines() if line.startswith('Depends:'))
                self.assertNotIn('nftables', depends)
            with tarfile.open(fileobj=io.BytesIO(outer.extractfile('./data.tar.gz').read())) as data:
                text = data.extractfile('./etc/config/xianniu-router').read().decode()
                self.assertIn("option transparent_enabled '0'", text)
                self.assertIn("option enabled '0'", text)


if __name__ == '__main__':
    unittest.main()
