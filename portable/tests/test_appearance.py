import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from portalproxy import appearance, i18n

class AppearanceTests(unittest.TestCase):
    def test_custom_theme_persists_without_changing_config_or_language(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';path.write_text('{"listen_port":10081}')
            i18n.save_language(path,'zh');i18n.save_theme(path,'custom','#134e4a')
            self.assertEqual(i18n.load_theme(path),'custom');self.assertEqual(i18n.load_theme_color(path),'#134e4a')
            i18n.save_language(path,'en')
            self.assertEqual(i18n.load_theme_color(path),'#134e4a')
            self.assertEqual(path.read_text(),'{"listen_port":10081}')
            with self.assertRaises(ValueError):i18n.save_theme(path,'custom','red; arbitrary')

    def test_system_palette_and_custom_highlights_remain_readable(self):
        with patch('portalproxy.appearance.system_colors',return_value=('#fafafa','#2368d2')):
            self.assertEqual(appearance.palette('system')['page'],'#fafafa')
        for base in ('#000000','#ffffff','#ff0000','#00ff00','#0000ff','#777777','#134e4a'):
            palette=appearance.palette('custom',base)
            self.assertEqual(palette['page'],base)
            for bg,fg in (('accent','accent_text'),('card','text')):
                a,b=sorted((appearance.luminance(palette[bg]),appearance.luminance(palette[fg])))
                self.assertGreaterEqual((b+.05)/(a+.05),4.5)
            self.assertNotEqual(palette['disabled'],palette['accent'])
