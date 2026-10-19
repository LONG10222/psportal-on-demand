"""Check icon bytes, native containers, platform wiring and source provenance."""
import importlib.util
import json
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zlib

import generate_brand_assets as brand

ROOT = Path(__file__).resolve().parents[1]
A = "{http://schemas.android.com/apk/res/android}"


def png_dimensions(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Not a PNG")
    offset, dimensions, ended = 8, None, False
    while offset < len(data):
        size = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + size]
        checksum = struct.unpack_from(">I", data, offset + 8 + size)[0]
        if zlib.crc32(kind + payload) != checksum:
            raise ValueError("Invalid PNG checksum")
        if kind == b"IHDR":
            width, height, depth, color, compression, filters, interlace = struct.unpack(">IIBBBBB", payload)
            if (depth, color, compression, filters, interlace) != (8, 2, 0, 0, 0):
                raise ValueError("Expected opaque 8-bit RGB PNG")
            dimensions = (width, height)
        offset += size + 12
        if kind == b"IEND":
            ended = True
            break
    if not dimensions or not ended or offset != len(data):
        raise ValueError("Incomplete PNG")
    return dimensions


class BrandAssetTests(unittest.TestCase):
    def test_original_and_every_generated_asset_match_manifest(self):
        manifest = brand.verify(ROOT)
        self.assertEqual(manifest["brand"], "星渡 StarPass")
        self.assertEqual(len(manifest["outputs"]), 43)
        self.assertEqual(png_dimensions((ROOT / brand.SOURCE).read_bytes()), (1254, 1254))
        # The latest monochrome source replaces the rejected portrait completely.
        self.assertEqual(manifest["source_sha256"], "cded3888e0a9538615cf9b0841147400f214b7480ac992ef002b729c0006bfab")

    def test_every_raster_is_opaque_rgb_with_platform_dimensions(self):
        manifest = brand.verify(ROOT)
        for path in manifest["outputs"]:
            if path.endswith(".png"):
                size = png_dimensions((ROOT / path).read_bytes())
                self.assertEqual(size[0], size[1], path)
                if Path(path).name.startswith("starpass-"):
                    self.assertEqual(size[0], int(Path(path).stem.split("-")[-1]), path)
        for density, scale in (("mdpi", 1), ("hdpi", 1.5), ("xhdpi", 2), ("xxhdpi", 3), ("xxxhdpi", 4)):
            for name, base in (("ic_launcher", 48), ("ic_launcher_foreground", 108)):
                self.assertEqual(png_dimensions((ROOT / brand.ANDROID / f"mipmap-{density}/{name}.png").read_bytes()),
                                 (int(base * scale), int(base * scale)))

    def test_windows_ico_frames_have_valid_offsets_and_sizes(self):
        data = (ROOT / brand.DESKTOP / "starpass.ico").read_bytes()
        reserved, kind, count = struct.unpack_from("<HHH", data)
        self.assertEqual((reserved, kind, count), (0, 1, len(brand.ICO_SIZES)))
        next_offset = 6 + 16 * count
        for index, size in enumerate(brand.ICO_SIZES):
            width, height, colors, reserved, planes, depth, length, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * index)
            self.assertEqual((width or 256, height or 256, colors, reserved, planes, depth), (size, size, 0, 0, 1, 32))
            self.assertEqual(offset, next_offset)
            self.assertEqual(png_dimensions(data[offset:offset + length]), (size, size))
            self.assertEqual(data[offset:offset + length], (ROOT / brand.DESKTOP / f"starpass-{size}.png").read_bytes())
            next_offset += length
        self.assertEqual(next_offset, len(data))

    def test_macos_icns_has_standard_and_retina_representations(self):
        data = (ROOT / brand.DESKTOP / "starpass.icns").read_bytes()
        self.assertEqual(data[:4], b"icns")
        self.assertEqual(struct.unpack_from(">I", data, 4)[0], len(data))
        offset = 8
        for kind, size in brand.ICNS_SIZES:
            self.assertEqual(data[offset:offset + 4], kind)
            length = struct.unpack_from(">I", data, offset + 4)[0]
            self.assertEqual(png_dimensions(data[offset + 8:offset + length]), (size, size))
            offset += length
        self.assertEqual(offset, len(data))

    def test_android_resources_use_new_brand_without_identity_changes(self):
        manifest = ET.parse(ROOT / "android/app/src/main/AndroidManifest.xml").getroot()
        app = manifest.find("application")
        self.assertEqual(app.get(A + "icon"), "@mipmap/ic_launcher")
        self.assertEqual(app.get(A + "roundIcon"), "@mipmap/ic_launcher_round")
        for name in ("ic_launcher", "ic_launcher_round"):
            adaptive = ET.parse(ROOT / brand.ANDROID / f"mipmap-anydpi-v26/{name}.xml").getroot()
            self.assertEqual(adaptive.tag, "adaptive-icon")
            self.assertEqual(adaptive.find("foreground").get(A + "drawable"), "@mipmap/ic_launcher_foreground")
        for language in ("values", "values-en"):
            strings = {node.get("name"): node.text for node in ET.parse(ROOT / brand.ANDROID / f"{language}/strings.xml").getroot()}
            self.assertEqual(strings["app_name"], "星渡 StarPass")
            self.assertIn("StarPass", strings["notification_title"])
            self.assertIn("StarPass", strings["vpn_notification_title"])
        self.assertIn("applicationId 'org.psportal.host'", (ROOT / "android/app/build.gradle").read_text())

    def test_ios_catalog_and_scope_preserve_identity_and_lifecycle(self):
        catalog = ROOT / brand.CATALOG / "AppIcon.appiconset"
        icons = json.loads((catalog / "Contents.json").read_text())["images"]
        self.assertEqual(len(icons), 18)
        for icon in icons:
            points = float(icon["size"].split("x")[0])
            scale = int(icon["scale"][0])
            size = int(points * scale)
            self.assertEqual(png_dimensions((catalog / icon["filename"]).read_bytes()), (size, size))
        self.assertEqual({item["idiom"] for item in icons}, {"iphone", "ipad", "ios-marketing"})
        info = plistlib.loads((ROOT / "ios/PSPortalHost/Info.plist").read_bytes())
        self.assertEqual(info["CFBundleDisplayName"], "星渡 StarPass")
        self.assertNotIn("UIBackgroundModes", info)
        self.assertEqual(info["CFBundleIdentifier"], "$(PRODUCT_BUNDLE_IDENTIFIER)")
        project = (ROOT / "ios/project.yml").read_text()
        self.assertIn("ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon", project)
        self.assertIn("PRODUCT_BUNDLE_IDENTIFIER: org.psportal.host.foreground", project)
        view = (ROOT / "ios/PSPortalHost/ContentView.swift").read_text()
        self.assertIn('Image("StarPassMark")', view)
        self.assertIn('accessibilityIdentifier("productModeScope")', view)
        self.assertIn("device-wide VPN, and full Clash groups/rules modes are unavailable", view)
        self.assertIn("Sharing stops when backgrounded or locked", view)

    def test_corruption_and_escaping_manifest_path_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / brand.SOURCE).parent.mkdir(parents=True)
            (root / brand.SOURCE).write_bytes((ROOT / brand.SOURCE).read_bytes())
            manifest = brand.manifest_for({"assets/branding/test.png": b"test"})
            (root / brand.MANIFEST).write_bytes(brand.json_bytes(manifest))
            (root / "assets/branding/test.png").write_bytes(b"bad!")
            with self.assertRaisesRegex(ValueError, "Generated asset differs"):
                brand.verify(root)
            manifest["outputs"] = {"../escape.png": {"bytes": 0, "sha256": ""}}
            (root / brand.MANIFEST).write_bytes(brand.json_bytes(manifest))
            with self.assertRaisesRegex(ValueError, "leaves native source root"):
                brand.verify(root)

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Developer-only Pillow is not installed")
    def test_regeneration_is_byte_identical(self):
        import PIL
        if PIL.__version__ != brand.PILLOW_VERSION:
            self.skipTest("Exact regeneration requires pinned developer Pillow " + brand.PILLOW_VERSION)
        outputs = brand.generate(ROOT)
        self.assertEqual((ROOT / brand.MANIFEST).read_bytes(), brand.json_bytes(brand.manifest_for(outputs)))
        for path, data in outputs.items():
            self.assertEqual((ROOT / path).read_bytes(), data, path)


if __name__ == "__main__":
    unittest.main()
