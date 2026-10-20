#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Linux-runnable mocked/structural tests; these never invoke a Swift compiler."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location("sdk_gate", HERE / "check-sdk26.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
WORKFLOW = ROOT / ".github/workflows/ios-simulator.yml"
JOB = WORKFLOW.read_text().split("  ios-sdk26-background-driver:\n", 1)[1]
SOURCE_BYTES = (ROOT / gate.SOURCE).read_bytes()


class MockAppleRunner:
    """Explicit test doubles: output is synthetic and is not Apple validation."""
    def __init__(self, root):
        self.root = root
        self.developer = root / "Xcode_26.3.app/Contents/Developer"
        self.sdk_path = self.developer / "Platforms/test.sdk"
        self.sdk_path.mkdir(parents=True)
        self.tools = {tool: self.developer / "usr/bin" / tool for tool in ("swiftc", "nm", "swift-demangle")}
        for tool in self.tools.values():
            tool.parent.mkdir(parents=True, exist_ok=True)
            tool.touch()
        source = root / gate.SOURCE
        source.parent.mkdir(parents=True)
        source.write_bytes(SOURCE_BYTES)
        self.commands = []
        self.version = "26.2"
        self.symbols = "\n".join(gate.MODULE + ".SystemBackgroundSharing." + method + "(mocked)" for method in ("begin", "finish"))
        self.fail_guard = False
        self.fail_compile = False
        self.emit_object = True
        self.source_dirty = False
        self.mutate_source = False
        self.object_bytes = struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 1, 0, 0, 0, 0) + b"mock object, not a real Apple compilation"

    def run(self, args, **kwargs):
        self.commands.append(args)
        assert kwargs["cwd"] == self.root
        assert kwargs["env"]["TOOLCHAINS"] == "com.apple.dt.toolchain.XcodeDefault"
        assert "shell" not in kwargs
        result, code = "", 0
        if args[:2] == ["git", "rev-parse"]:
            result = {"HEAD": "1" * 40, "HEAD^{tree}": "2" * 40}.get(args[2], "3" * 40)
        elif args[:2] == ["git", "hash-object"]:
            result = ("4" if self.source_dirty else "3") * 40
        elif args[0] == "/usr/bin/xcodebuild":
            result = "Xcode 26.3\nBuild version MOCK"
        elif args[0] == "/usr/bin/xcrun":
            operation = args[3]
            if operation == "--show-sdk-path":
                result = str(self.sdk_path)
            elif operation == "--show-sdk-version":
                result = self.version
            elif operation == "--find":
                result = str(self.tools[args[4]])
            else:
                raise AssertionError(args)
        elif args[0] == str(self.tools["swiftc"]):
            if "--version" in args:
                result = "Apple Swift version 6.2 (MOCKED)"
            elif "-typecheck" in args:
                code = int(self.fail_guard)
            elif "-emit-object" in args:
                code = int(self.fail_compile)
                if self.emit_object and code == 0:
                    Path(args[args.index("-o") + 1]).write_bytes(self.object_bytes)
                if self.mutate_source:
                    (self.root / gate.SOURCE).write_bytes(b"mutated")
            else:
                raise AssertionError(args)
        elif args[0] == str(self.tools["nm"]):
            assert args[1] == "-U"
            result = "mock defined symbols"
        elif args[0] == str(self.tools["swift-demangle"]):
            assert kwargs["input"] == "mock defined symbols"
            result = self.symbols
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, code, result)


class SDKGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fake = MockAppleRunner(self.root)
        for patcher in (
            patch.object(gate, "DEVELOPER_DIR", str(self.fake.developer)),
            patch.dict(os.environ, {"DEVELOPER_DIR": str(self.fake.developer), "PR_HEAD_SHA": "5" * 40, "GITHUB_SHA": "1" * 40}),
            patch.object(gate.subprocess, "run", side_effect=self.fake.run),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def evidence(self, sdk="iphoneos"):
        return json.loads((self.root / "native/ios/build/sdk26" / sdk / "EVIDENCE.json").read_text())

    def assert_rejected(self, error, pattern):
        with self.assertRaisesRegex(error, pattern):
            gate.run_gate("iphoneos", self.root)
        self.assertEqual(self.evidence()["status"], "failed")
        self.assertFalse(self.evidence()["system_background_sharing_compiled"])
        self.assertNotIn("object_sha256", self.evidence())
        self.assertIn(pattern.split(" ")[0], self.evidence()["error"])

    def test_both_targets_compile_real_path_with_app_settings_and_honest_evidence(self):
        for sdk in gate.TARGETS:
            with self.subTest(sdk=sdk):
                evidence = gate.run_gate(sdk, self.root)
                self.assertEqual(evidence["status"], "passed")
                self.assertTrue(evidence["compiler_guard_passed"])
                self.assertTrue(evidence["system_background_sharing_compiled"])
                for key in ("full_app_build", "linked", "runtime_tested", "physical_device_tested", "background_tasks_submitted"):
                    self.assertFalse(evidence[key])
                self.assertEqual(evidence["source_file_sha256"], hashlib.sha256(SOURCE_BYTES).hexdigest())
                self.assertEqual(evidence["object_sha256"], hashlib.sha256(self.fake.object_bytes).hexdigest())
                self.assertEqual(evidence["checkout_commit"], "1" * 40)
                self.assertEqual(evidence["pr_head_sha"], "5" * 40)
                self.assertEqual(evidence["sdk_version"], "26.2")
                compile_command = next(command for command in reversed(self.fake.commands) if "-emit-object" in command)
                self.assertIn(str(self.root / gate.SOURCE), compile_command)
                self.assertEqual(compile_command[compile_command.index("-target") + 1], gate.TARGETS[sdk])
                self.assertEqual(compile_command[compile_command.index("-swift-version") + 1], "5")
                self.assertIn("-parse-as-library", compile_command)
                self.assertIn("-Onone", compile_command)
                self.assertEqual(sum(arg.endswith(".swift") for arg in compile_command), 1)
                self.assertEqual((self.root / gate.SOURCE).read_bytes(), SOURCE_BYTES)

    def test_sdk_versions_fail_closed(self):
        for value in ("18.5", "25.9", "26", "26.2beta", "garbage", "26.2\n18.5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                gate.sdk_version(value)
        for value in ("26.0", "26.2", "26.2.1", "27.0"):
            self.assertGreaterEqual(gate.sdk_version(value), (26, 0))

    def test_old_sdk_rejected_before_any_compilation(self):
        self.fake.version = "18.5"
        self.assert_rejected(ValueError, "iOS SDK 26.0")
        self.assertFalse(any("-typecheck" in command for command in self.fake.commands))

    def test_missing_or_wrong_developer_dir_fails_before_tools(self):
        with patch.dict(os.environ, {"DEVELOPER_DIR": "/wrong/Xcode"}):
            self.assert_rejected(ValueError, "Expected existing Xcode")
        self.assertEqual(self.fake.commands, [])

    def test_sdk_outside_selected_xcode_rejected(self):
        self.fake.sdk_path = self.root
        self.assert_rejected(ValueError, "SDK is not inside")

    def test_missing_sdk_rejected(self):
        self.fake.sdk_path = self.fake.developer / "missing.sdk"
        self.assert_rejected(ValueError, "SDK is not inside")

    def test_tool_outside_selected_xcode_rejected(self):
        self.fake.tools["swiftc"] = self.root / "unexpected-swiftc"
        self.fake.tools["swiftc"].touch()
        self.assert_rejected(ValueError, "Tool is outside")

    def test_tool_symlink_keeps_swiftc_driver_basename(self):
        swiftc = self.fake.tools["swiftc"]
        driver = swiftc.with_name("swift-driver")
        driver.touch()
        swiftc.unlink()
        swiftc.symlink_to(driver.name)
        self.assertEqual(gate.validate_tool_path(str(swiftc), self.fake.developer), str(swiftc))
        driver.unlink()
        driver.symlink_to("/bin/true")
        with self.assertRaisesRegex(ValueError, "outside"):
            gate.validate_tool_path(str(swiftc), self.fake.developer)

    def test_guard_enforces_compiler_and_sdk_environment(self):
        for sdk in gate.TARGETS:
            text = gate.compiler_guard(sdk)
            self.assertIn("#if !compiler(>=6.2)\n#error", text)
            self.assertIn("#if !os(iOS)\n#error", text)
        self.assertIn("#if targetEnvironment(simulator)\n#error", gate.compiler_guard("iphoneos"))
        self.assertIn("#if !targetEnvironment(simulator)\n#error", gate.compiler_guard("iphonesimulator"))

    def test_guard_failure_stops_production_compilation(self):
        self.fake.fail_guard = True
        self.assert_rejected(RuntimeError, "Command failed")
        self.assertFalse(any("-emit-object" in command for command in self.fake.commands))
        self.assertFalse(self.evidence()["compiler_guard_passed"])

    def test_compile_failure_retains_failure_log(self):
        self.fake.fail_compile = True
        self.assert_rejected(RuntimeError, "Command failed")
        log = (self.root / "native/ios/build/sdk26/iphoneos/compile.log").read_text()
        self.assertIn("-emit-object", log)
        self.assertIn("FAILED:", log)

    def test_stale_object_cannot_pass_without_fresh_compiler_output(self):
        build = self.root / "native/ios/build/sdk26/iphoneos"
        build.mkdir(parents=True)
        (build / "BackgroundSharingSession.o").write_bytes(self.fake.object_bytes)
        self.fake.emit_object = False
        with self.assertRaises(FileNotFoundError):
            gate.run_gate("iphoneos", self.root)
        self.assertEqual(self.evidence()["status"], "failed")

    def test_source_must_match_checkout_commit(self):
        self.fake.source_dirty = True
        self.assert_rejected(ValueError, "Production source differs")
        self.assertFalse(any("-typecheck" in command for command in self.fake.commands))

    def test_source_cannot_change_during_compilation(self):
        self.fake.mutate_source = True
        self.assert_rejected(ValueError, "Production source changed")

    def test_class_reference_or_missing_method_does_not_prove_compilation(self):
        for symbols in ("SystemBackgroundSharing", "Other.SystemBackgroundSharing.begin(mock)",
                        gate.MODULE + ".SystemBackgroundSharing.begin(mock)"):
            with self.subTest(symbols=symbols):
                self.fake.symbols = symbols
                self.assert_rejected(ValueError, "Defined SystemBackgroundSharing")

    def test_non_object_and_non_arm64_output_rejected(self):
        for output in (b"not an object", struct.pack("<8I", 0xFEEDFACF, 0x01000007, 0, 1, 0, 0, 0, 0),
                       struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 2, 0, 0, 0, 0)):
            with self.subTest(output=output), self.assertRaises(ValueError):
                gate.require_arm64_object(output)


class WorkflowTests(unittest.TestCase):
    def test_workflow_and_inactive_template_match(self):
        template = (ROOT / "native/ci/ios-simulator.yml.example").read_text().split("\n", 1)[1]
        self.assertEqual(template, WORKFLOW.read_text())

    def test_narrow_matrix_uses_fixed_existing_xcode_and_public_standard_runner(self):
        for expected in ("runs-on: macos-15", "timeout-minutes: 10", "fail-fast: false",
                         "sdk: [iphoneos, iphonesimulator]", "DEVELOPER_DIR: " + gate.DEVELOPER_DIR,
                         "if: github.event.repository.private == false", "persist-credentials: false"):
            self.assertIn(expected, JOB)
        runs = [line.strip() for line in JOB.splitlines() if line.strip().startswith("run:")]
        self.assertEqual(runs, ["run: python3 native/ios/scripts/check-sdk26-tests.py",
                               "run: python3 native/ios/scripts/check-sdk26.py --sdk ${{ matrix.sdk }}"])
        self.assertNotIn("continue-on-error", JOB)
        self.assertNotIn("needs:", JOB)

    def test_unique_one_day_logs_and_evidence_only_no_distributable(self):
        self.assertIn("name: psportal-ios-sdk26-${{ matrix.sdk }}-${{ env.PSPORTAL_SOURCE_COMMIT }}-${{ github.run_attempt }}", JOB)
        self.assertIn("if: always()", JOB)
        self.assertIn("retention-days: 1", JOB)
        self.assertIn("if-no-files-found: error", JOB)
        for filename in ("EVIDENCE.json", "compile.log"):
            self.assertIn("native/ios/build/sdk26/${{ matrix.sdk }}/" + filename, JOB)
        self.assertNotIn("BackgroundSharingSession.o", JOB)
        uses = [line.split("uses: ", 1)[1].split()[0] for line in JOB.splitlines() if "uses: " in line]
        self.assertEqual(len(uses), 2)
        for action in uses:
            self.assertRegex(action, r"^actions/(?:checkout|upload-artifact)@[0-9a-f]{40}$")

    def test_existing_full_app_job_and_app_language_target_retained(self):
        original_job = WORKFLOW.read_text().split("  ios-sdk26-background-driver:\n", 1)[0]
        self.assertIn("DEVELOPER_DIR: /Applications/Xcode_16.4.app/Contents/Developer", original_job)
        self.assertIn("run: bash native/ios/scripts/ci-simulator.sh", original_job)
        self.assertNotIn("matrix:", original_job)
        project = (ROOT / "native/ios/project.yml").read_text()
        self.assertIn('SWIFT_VERSION: "5.0"', project)
        self.assertIn('iOS: "16.0"', project)


if __name__ == "__main__":
    unittest.main(verbosity=2)
