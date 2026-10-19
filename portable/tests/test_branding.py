from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from portalproxy import branding

ROOT = Path(__file__).resolve().parents[1]


class BrandingTests(unittest.TestCase):
    def test_source_assets_and_fixed_basename_resolution(self):
        self.assertEqual(branding.BRAND_NAME, "星渡 StarPass")
        self.assertTrue(branding.asset_path("starpass-64.png").is_file())
        for name in ("../private.txt", "/tmp/private.txt", "", ".."):
            with self.assertRaises(ValueError):
                branding.asset_path(name)

    def test_frozen_assets_resolve_under_pyinstaller_root(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", tmp, create=True):
            self.assertEqual(branding.asset_path("starpass.ico"), Path(tmp) / "assets/branding/starpass.ico")

    def test_avatar_uses_pre_generated_png_without_imaging_dependency(self):
        root = Mock()
        with patch.object(tk, "PhotoImage", return_value="image") as photo:
            self.assertEqual(branding.load_avatar(root), "image")
            photo.assert_called_once_with(master=root, file=str(branding.asset_path("starpass-64.png")))
        with self.assertRaises(ValueError):
            branding.load_avatar(root, 63)
        with patch.object(tk, "PhotoImage", side_effect=tk.TclError("unsupported")):
            self.assertIsNone(branding.load_avatar(root))

    def test_windows_uses_ico_and_other_window_managers_retain_png_references(self):
        root = Mock()
        with patch.object(sys, "platform", "win32"):
            self.assertTrue(branding.apply_window_icon(root))
            root.iconbitmap.assert_called_once_with(default=str(branding.asset_path("starpass.ico")))
        root = Mock()
        images = [Mock() for _ in range(4)]
        with patch.object(sys, "platform", "linux"), patch.object(branding, "load_avatar", side_effect=images):
            self.assertTrue(branding.apply_window_icon(root))
            root.iconphoto.assert_called_once_with(True, *images)
            self.assertEqual(root._starpass_icon_images, images)

    def test_unsupported_icon_api_does_not_break_startup(self):
        root = Mock()
        root.iconbitmap.side_effect = tk.TclError("unsupported")
        root.iconphoto.side_effect = tk.TclError("unsupported")
        with patch.object(sys, "platform", "win32"), patch.object(branding, "load_avatar", return_value=Mock()):
            self.assertFalse(branding.apply_window_icon(root))
        with patch.object(branding, "load_avatar", return_value=None):
            self.assertFalse(branding.apply_window_icon(root))

    def test_packaging_references_icons_without_renaming_product_identity(self):
        spec = (ROOT / "packaging/portalproxy.spec").read_text()
        for value in ("'assets/branding'", "'starpass.ico'", "'starpass.icns'", "'CFBundleDisplayName': '星渡 StarPass'",
                      "name='PSPortalProxy'", "name='PSPortalProxy.app'", "bundle_identifier='org.psportal.on-demand'"):
            self.assertIn(value, spec)
        self.assertIn("generate_brand_assets.py", (ROOT / "build.py").read_text())


if __name__ == "__main__":
    unittest.main()
