#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Linux-compatible tests for CI helpers; these do not execute an Apple build."""
import importlib.util
import pathlib
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


class CIHelpers(unittest.TestCase):
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
