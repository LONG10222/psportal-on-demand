"""Verify the game listener boot state does not depend on the visible page."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]

class Coexistence(unittest.TestCase):
    def start(self,enabled,page):
        source=(ROOT/'files/portalproxy.init').read_text()
        source=source.replace('/usr/bin/lua /usr/libexec/portalproxy/render.lua','render_config')
        prefix='''
uci() {
 case "$*" in
  *main.enabled) echo ENABLED ;;
  *main.product_mode) echo PAGE ;;
  *main.core_mode) echo standalone ;;
  *main.routing_mark) echo 0 ;;
 esac
}
render_config() { echo RENDER; }
mkdir() { :; }
chmod() { :; }
procd_open_instance() { echo OPEN; }
procd_set_param() { :; }
procd_close_instance() { echo CLOSE; }
'''.replace('ENABLED',enabled).replace('PAGE',page)
        return subprocess.run(['sh'],input=prefix+source+'\nstart_service\n',text=True,capture_output=True)

    def test_enabled_listener_starts_in_both_pages(self):
        for page in ['game','accelerator']:
            with self.subTest(page=page):
                result=self.start('1',page)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout.splitlines(),['RENDER','OPEN','CLOSE'])

    def test_disabled_listener_stays_off_in_both_pages(self):
        for page in ['game','accelerator']:
            with self.subTest(page=page):
                result=self.start('0',page)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout,'')

if __name__=='__main__':unittest.main()
