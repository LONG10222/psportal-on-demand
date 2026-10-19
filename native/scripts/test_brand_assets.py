"""Check icon bytes, native containers, platform wiring and source provenance."""
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
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
    def test_source_text_checks_ignore_windows_default_codepage(self):
        original = Path.read_text
        encodings = []

        def windows_read_text(path, encoding=None, errors=None, **kwargs):
            encodings.append(encoding)
            return original(path, encoding=encoding or "cp1252", errors=errors, **kwargs)

        with patch.object(Path, "read_text", windows_read_text):
            self.test_android_resources_use_new_brand_without_identity_changes()
            self.test_ios_catalog_and_scope_preserve_identity_and_lifecycle()
            self.test_ios_timed_background_experiment_is_finite_and_grant_gated()
            brand.verify(ROOT)
        self.assertEqual(encodings, ["utf-8"] * 8)

    def test_generated_text_retains_canonical_lf_bytes(self):
        manifest = brand.verify(ROOT)
        text_paths = [brand.MANIFEST] + [path for path in manifest["outputs"]
                                        if Path(path).suffix in (".xml", ".json")]
        self.assertEqual(len(text_paths), 7)
        for path in text_paths:
            data = (ROOT / path).read_bytes()
            self.assertNotIn(b"\r", data, path)
            self.assertTrue(data.endswith(b"\n"), path)

    @unittest.skipUnless(shutil.which("git"), "Checkout regression requires Git")
    def test_autocrlf_checkout_preserves_hashes_and_corruption_detection(self):
        attributes = ROOT.parent / ".gitattributes"
        if not attributes.exists():
            self.skipTest("Source archive has no repository checkout attributes")
        manifest = brand.verify(ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            repository = Path(tmp) / "repository"
            checkout = Path(tmp) / "checkout"
            repository.mkdir()
            (repository / ".gitattributes").write_bytes(attributes.read_bytes())
            # This deliberately unprotected file demonstrates that checkout is
            # actually applying Windows-style conversion, rather than a no-op.
            (repository / "control.txt").write_bytes(b"first\nsecond\n")
            for path in [brand.SOURCE, brand.MANIFEST, *manifest["outputs"]]:
                destination = repository / "native" / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT / path).read_bytes())
            env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_ATTR_NOSYSTEM="1")
            def git(*args):
                return subprocess.run(["git", "-c", "core.autocrlf=true", "-c", "core.eol=crlf",
                                       "-c", "core.safecrlf=false", "-c", "core.attributesfile=", *args],
                                      cwd=repository, env=env, check=True, capture_output=True)
            git("init", "--quiet")
            git("add", "--", ".gitattributes", "control.txt", "native")
            git("checkout-index", "--all", "--prefix=" + checkout.as_posix() + "/")
            self.assertEqual((checkout / "control.txt").read_bytes(), b"first\r\nsecond\r\n")
            native = checkout / "native"
            self.assertEqual(brand.verify(native), manifest)
            self.assertEqual((native / brand.MANIFEST).read_bytes(), (ROOT / brand.MANIFEST).read_bytes())
            for path in manifest["outputs"]:
                self.assertEqual((native / path).read_bytes(), (ROOT / path).read_bytes(), path)
            # No newline normalization is allowed inside the verifier. Either
            # text corruption or binary corruption must still fail closed.
            for path in (brand.ANDROID + "/mipmap-anydpi-v26/ic_launcher.xml",
                         brand.DESKTOP + "/starpass-64.png"):
                target = native / path
                original = target.read_bytes()
                target.write_bytes(original.replace(b"\n", b"\r\n") if path.endswith(".xml") else original + b"\0")
                with self.assertRaisesRegex(ValueError, "Generated asset differs"):
                    brand.verify(native)
                target.write_bytes(original)
            brand.verify(native)

    def test_original_and_every_generated_asset_match_manifest(self):
        manifest = brand.verify(ROOT)
        self.assertEqual(manifest["brand"], "星渡 StarPass")
        self.assertEqual(len(manifest["outputs"]), 43)
        self.assertEqual(png_dimensions((ROOT / brand.SOURCE).read_bytes()), (1254, 1254))
        # Retain the coherent v2 asset set until the candidate swap is authorized.
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
        self.assertIn("applicationId 'org.psportal.host'", (ROOT / "android/app/build.gradle").read_text(encoding="utf-8"))

    def test_ios_catalog_and_scope_preserve_identity_and_lifecycle(self):
        catalog = ROOT / brand.CATALOG / "AppIcon.appiconset"
        icons = json.loads((catalog / "Contents.json").read_text(encoding="utf-8"))["images"]
        self.assertEqual(len(icons), 18)
        for icon in icons:
            points = float(icon["size"].split("x")[0])
            scale = int(icon["scale"][0])
            size = int(points * scale)
            self.assertEqual(png_dimensions((catalog / icon["filename"]).read_bytes()), (size, size))
        self.assertEqual({item["idiom"] for item in icons}, {"iphone", "ipad", "ios-marketing"})
        info = plistlib.loads((ROOT / "ios/PSPortalHost/Info.plist").read_bytes())
        self.assertEqual(info["CFBundleDisplayName"], "星渡 StarPass")
        self.assertEqual(info["UIBackgroundModes"], ["processing"])
        self.assertEqual(info["BGTaskSchedulerPermittedIdentifiers"],
                         ["org.psportal.host.foreground.sharing.*"])
        self.assertEqual(info["CFBundleIdentifier"], "$(PRODUCT_BUNDLE_IDENTIFIER)")
        project = (ROOT / "ios/project.yml").read_text(encoding="utf-8")
        self.assertIn("ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon", project)
        self.assertIn("PRODUCT_BUNDLE_IDENTIFIER: org.psportal.host.foreground", project)
        view = (ROOT / "ios/PSPortalHost/ContentView.swift").read_text(encoding="utf-8")
        self.assertIn('Image("StarPassMark")', view)
        self.assertIn('accessibilityIdentifier("productModeScope")', view)
        self.assertIn("HTTP/CONNECT TCP sharing with an experimental timed background mode", view)
        self.assertIn("device-wide VPN, and full Clash groups/rules modes are unavailable", view)
        self.assertIn("Sharing stops when backgrounded or locked", view)
        self.assertIn("Simulator does not support this task; sharing remains foreground-only", view)
        self.assertIn("Lock-screen networking needs device validation; no unlimited keepalive", view)

    def test_ios_timed_background_experiment_is_finite_and_grant_gated(self):
        # Structural coverage only. Existing Swift lifecycle tests exercise
        # granted lock continuation, expiry, rejected/pending grants and fallback.
        app = ROOT / "ios/PSPortalHost"
        driver = (app / "BackgroundSharingSession.swift").read_text(encoding="utf-8")
        model = (app / "ProxyModel.swift").read_text(encoding="utf-8")
        settings = (app / "ProxySettings.swift").read_text(encoding="utf-8")
        self.assertIn("#if compiler(>=6.2) && !targetEnvironment(simulator)", driver)
        self.assertIn("if #available(iOS 26.0, *)", driver)
        self.assertIn("return UnavailableBackgroundSharing()", driver)
        self.assertIn('".sharing." + UUID().uuidString', driver)
        self.assertIn("BGContinuedProcessingTaskRequest", driver)
        self.assertIn("request.strategy = .fail", driver)
        self.assertIn("max(1, min(minutes, 60)) * 60", driver)
        self.assertIn("continued.expirationHandler", driver)
        self.assertIn("if remaining == 0", driver)
        self.assertIn("BGTaskScheduler.shared.cancel(taskRequestWithIdentifier: previous)", driver)
        self.assertIn("task?.setTaskCompleted(success: success)", driver)
        self.assertIn("@Published var backgroundEnabled = false", model)
        self.assertIn("guard backgroundEnabled else { return }", model)
        self.assertIn("[15, 30, 60].contains(backgroundMinutes)", model)
        self.assertIn("state == .running && backgroundDeadline.map { $0 > Date() } == true", model)
        self.assertIn("self.generation == token, self.state == .running, self.isActive", model)
        self.assertIn("if wasGranted || !self.isActive { self.stop(reason: reason) }", model)
        self.assertNotIn("backgroundEnabled", settings)
        # A valid finite grant intentionally permits background/lock continuation.
        # Without it each path still closes sharing; never require unconditional stop.
        for signature in ("scenePhaseChanged(_ phase: ScenePhase)", "didEnterBackground()", "protectedDataUnavailable()"):
            body = model.split("func " + signature, 1)[1].split("\n    func ", 1)[0]
            self.assertIn("if hasBackgroundGrant { return }", body, signature)
            self.assertIn("stop(reason:", body, signature)
        for forbidden in ("import NetworkExtension", "NEPacketTunnelProvider", "NEVPNManager"):
            self.assertNotIn(forbidden, driver + model)

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
