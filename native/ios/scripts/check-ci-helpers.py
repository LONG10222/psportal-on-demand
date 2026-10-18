#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Linux-compatible tests for CI helpers; these do not execute an Apple build."""
import importlib.util
import pathlib
import plistlib
import shutil
import hashlib
import struct
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


selector = module("select-simulator")
diagnostics = module("collect-ci-diagnostics")
resources = module("audit-app-resources")
packages = module("audit-final-package")


class CIHelpers(unittest.TestCase):
    def test_final_package_rejects_hash_mode_member_and_signature_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            built = root / "built.app"
            built.mkdir()
            (built / "Info.plist").write_bytes(plistlib.dumps({
                "CFBundleExecutable": "Fixture", "CFBundleSupportedPlatforms": ["iPhoneOS"]}))
            executable = struct.pack("<8I", 0xFEEDFACF, 0x100000C, 0, 2, 0, 0, 0, 0)
            (built / "Fixture").write_bytes(executable)
            (built / "Fixture").chmod(0o755)
            (built / "relative-link").symlink_to("Info.plist")
            package = root / "package"
            package.mkdir()
            app = package / "PSPortalHost.app"
            shutil.copytree(built, app, symlinks=True)
            source = package / "psportal-native-corresponding-source.tar.gz"
            source.write_bytes(b"fixture source, not a real source archive")
            manifest = package / "CONTENT-SHA256SUMS"
            def write_manifest():
                manifest.write_text("".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.relative_to(package).as_posix() + "\n"
                                            for path in sorted(package.rglob("*")) if path.is_file() and path != manifest))
            write_manifest()
            valid_manifest = manifest.read_text()
            self.assertTrue(packages.audit(package, built)["app_members_modes_and_links_match_build"])
            for bad, message in [
                ("", "empty"),
                (valid_manifest + valid_manifest.splitlines()[0] + "\n", "Duplicate"),
                ("\n".join(valid_manifest.splitlines()[1:]) + "\n", "omitted"),
                (valid_manifest.upper(), "Malformed"),
                ("0" * 64 + "  ../outside\n", "Unsafe"),
            ]:
                manifest.write_text(bad)
                with self.assertRaisesRegex(AssertionError, message):
                    packages.audit(package, built)
            manifest.write_text(valid_manifest)
            source.write_bytes(b"modified")
            with self.assertRaisesRegex(AssertionError, "Content hash"):
                packages.audit(package, built)
            source.write_bytes(b"fixture source, not a real source archive")
            (app / "Fixture").chmod(0o644)
            with self.assertRaisesRegex(AssertionError, "permission modes"):
                packages.audit(package, built)
            (app / "Fixture").chmod(0o755)
            (app / "injected").write_text("unexpected")
            with self.assertRaisesRegex(AssertionError, "omitted"):
                packages.audit(package, built)
            (app / "injected").unlink()
            old_info = (app / "Info.plist").read_bytes()
            (app / "Info.plist").write_bytes(old_info + b"\n")
            write_manifest()
            with self.assertRaisesRegex(AssertionError, "app bytes"):
                packages.audit(package, built)
            (app / "Info.plist").write_bytes(old_info)
            write_manifest()
            (app / "relative-link").unlink()
            (app / "relative-link").symlink_to("../../outside")
            with self.assertRaisesRegex(AssertionError, "escaped package"):
                packages.audit(package, built)
            (app / "relative-link").unlink()
            (app / "relative-link").symlink_to("Info.plist")
            # A device signature is forbidden even if matching before/after packing.
            signed = struct.pack("<8I", 0xFEEDFACF, 0x100000C, 0, 2, 1, 16, 0, 0) + struct.pack("<4I", 0x1D, 16, 0, 0)
            (built / "Fixture").write_bytes(signed)
            (app / "Fixture").write_bytes(signed)
            write_manifest()
            with self.assertRaisesRegex(AssertionError, "remain unsigned"):
                packages.audit(package, built)

    def test_privacy_import_reader_ignores_debug_and_defined_symbols(self):
        names = [b"_mach_absolute_time", b"_debug", b"_defined"]
        strings = b"\0"
        entries = b""
        for name, kind in zip(names, [0x01, 0xE0, 0x0F]):
            entries += struct.pack("<IBBHQ", len(strings), kind, 0, 0, 0)
            strings += name + b"\0"
        header = struct.pack("<8I", 0xFEEDFACF, 0x100000C, 0, 2, 1, 24, 0, 0)
        command = struct.pack("<6I", 2, 24, 56, 3, 56 + len(entries), len(strings))
        self.assertEqual(resources.undefined_symbols(header + command + entries + strings), {"_mach_absolute_time"})
        with self.assertRaisesRegex(AssertionError, "Mach-O"):
            resources.undefined_symbols(b"not a Mach-O executable")

    def test_ignores_future_unavailable_and_non_iphone_runtimes(self):
        def device(name, udid, available=True):
            return {"name": name, "udid": udid, "isAvailable": available}
        devices = {
            "com.apple.CoreSimulator.SimRuntime.iOS-26-0": [device("iPhone 17", "future")],
            "com.apple.CoreSimulator.SimRuntime.iOS-18-5": [device("iPhone 16", "valid"), device("iPhone 16 Pro", "unavailable", False), device("iPad Pro", "tablet")],
            "com.apple.CoreSimulator.SimRuntime.iOS-17-5": [device("iPhone 15", "older")],
            "com.apple.CoreSimulator.SimRuntime.tvOS-18-5": [device("iPhone fake", "tv")],
        }
        self.assertEqual(selector.select_device(devices, "18.5"), "valid")
        self.assertEqual(selector.select_device(devices, "18.0"), "older")

    def test_missing_compatible_runtime_fails_without_download(self):
        with self.assertRaisesRegex(ValueError, "No runtime was downloaded"):
            selector.select_device({}, "18.5")

    def test_large_diagnostics_are_omitted_with_log_tails_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            build = pathlib.Path(temp)
            (build / "logs").mkdir()
            (build / "logs/test.log").write_bytes(b"A" * (5 * diagnostics.MIB) + b"TAIL")
            result = build / "TestResults.xcresult"
            result.mkdir()
            with (result / "oversized").open("wb") as output:
                output.truncate(51 * diagnostics.MIB)
            destination = build / "diagnostics"
            diagnostics.collect(build, destination)
            self.assertEqual((destination / "test.log").stat().st_size, 4 * diagnostics.MIB)
            self.assertTrue((destination / "test.log").read_bytes().endswith(b"TAIL"))
            self.assertFalse((destination / "TestResults.xcresult").exists())
            self.assertIn("omitted", (destination / "DIAGNOSTICS.txt").read_text())

    def test_small_result_bundle_is_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            build = pathlib.Path(temp)
            result = build / "TestResults.xcresult"
            result.mkdir()
            (result / "fixture").write_text("fixture only")
            destination = build / "diagnostics"
            diagnostics.collect(build, destination)
            self.assertEqual((destination / "TestResults.xcresult/fixture").read_text(), "fixture only")


if __name__ == "__main__":
    unittest.main(verbosity=2)
