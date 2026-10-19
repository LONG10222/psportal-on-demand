#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compile the unchanged background driver with an installed modern Apple SDK.

This emits an object only. It never links, launches, signs, or submits a task.
The separate Xcode 16.4 workflow job remains responsible for full-app validation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path("native/ios/PSPortalHost/BackgroundSharingSession.swift")
DEVELOPER_DIR = "/Applications/Xcode_26.3.app/Contents/Developer"
TARGETS = {"iphoneos": "arm64-apple-ios16.0", "iphonesimulator": "arm64-apple-ios16.0-simulator"}
MODULE = "PSPortalSDK26Gate"
LOG_LIMIT = 512 * 1024


def sdk_version(value):
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", value):
        raise ValueError("Unrecognized Apple SDK version: " + value)
    version = tuple(int(part) for part in value.split("."))
    if version < (26, 0):
        raise ValueError("iOS SDK 26.0 or newer is required; no SDK will be downloaded")
    return version


def compiler_guard(sdk):
    environment = "!targetEnvironment(simulator)" if sdk == "iphonesimulator" else "targetEnvironment(simulator)"
    return f'''#if !compiler(>=6.2)
#error("The real SystemBackgroundSharing branch requires compiler >= 6.2")
#endif
#if !os(iOS)
#error("This gate must target iOS")
#endif
#if {environment}
#error("Target environment does not match the requested SDK")
#endif
'''


def compile_flags(sdk, sdk_path, build):
    return ["-parse-as-library", "-Onone", "-swift-version", "5", "-target", TARGETS[sdk],
            "-sdk", str(sdk_path), "-module-name", MODULE,
            "-module-cache-path", str(build / "module-cache")]


def require_defined_methods(symbols):
    # nm -U excludes undefined references. Require implementation method symbols,
    # rather than a string, debug name, or reference to the class alone.
    required = [MODULE + ".SystemBackgroundSharing." + method + "(" for method in ("begin", "finish")]
    if not all(marker in symbols for marker in required):
        raise ValueError("Defined SystemBackgroundSharing begin/finish symbols are missing")
    return required


def require_arm64_object(data):
    if len(data) < 32 or struct.unpack_from("<III", data)[:2] != (0xFEEDFACF, 0x0100000C):
        raise ValueError("Compiler output is not an arm64 Mach-O object")
    if struct.unpack_from("<I", data, 12)[0] != 1:  # MH_OBJECT, never an executable
        raise ValueError("Compiler output must be MH_OBJECT")


def validate_tool_path(path, developer):
    resolved = Path(path).resolve()
    if not resolved.is_file() or not resolved.is_relative_to(developer.resolve()):
        raise ValueError("Tool is outside the selected existing Xcode: " + path)
    # Keep the tool basename: swiftc may be a symlink to the Swift driver.
    return str(Path(path))


def run_gate(sdk, root=ROOT):
    build = root / "native/ios/build/sdk26" / sdk
    build.mkdir(parents=True, exist_ok=True)
    log_path = build / "compile.log"
    evidence = {
        "schema_version": 1, "status": "failed", "sdk": sdk, "target": TARGETS[sdk],
        "swift_language_mode": "5", "deployment_target": "16.0", "source_file": SOURCE.as_posix(),
        "scope": "unchanged production background-driver object compilation only",
        "full_app_build": False, "linked": False, "runtime_tested": False,
        "physical_device_tested": False, "background_tasks_submitted": False,
        "compiler_guard_passed": False, "system_background_sharing_compiled": False,
        "github_sha": os.environ.get("GITHUB_SHA"), "pr_head_sha": os.environ.get("PR_HEAD_SHA"),
        "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "commands": [],
    }
    env = dict(os.environ, TOOLCHAINS="com.apple.dt.toolchain.XcodeDefault")
    log_path.write_text("Compile-only SDK gate; no app or background task is executed.\n", encoding="utf-8")

    def command(args, input_text=None):
        result = subprocess.run(args, cwd=root, env=env, input=input_text, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        output = result.stdout or ""
        evidence["commands"].append({"argv": args, "returncode": result.returncode})
        with log_path.open("a", encoding="utf-8") as log:
            log.write("\n$ " + shlex.join(args) + "\n")
            if len(output) > LOG_LIMIT:
                log.write("[output truncated to final 512 KiB]\n")
            log.write(output[-LOG_LIMIT:] + "\n")
        if result.returncode:
            raise RuntimeError("Command failed (see compile.log): " + shlex.join(args))
        return output.strip()

    try:
        if env.get("DEVELOPER_DIR") != DEVELOPER_DIR or not Path(DEVELOPER_DIR).is_dir():
            raise ValueError("Expected existing Xcode 26.3 via DEVELOPER_DIR; no installation or selection change is allowed")
        developer = Path(DEVELOPER_DIR)
        evidence["developer_dir"] = str(developer)
        evidence["xcode_version"] = command(["/usr/bin/xcodebuild", "-version"])
        source = root / SOURCE
        original = source.read_bytes()
        evidence["source_file_sha256"] = hashlib.sha256(original).hexdigest()
        evidence["checkout_commit"] = command(["git", "rev-parse", "HEAD"])
        evidence["checkout_tree"] = command(["git", "rev-parse", "HEAD^{tree}"])
        evidence["source_git_blob"] = command(["git", "rev-parse", "HEAD:" + SOURCE.as_posix()])
        if command(["git", "hash-object", "--no-filters", str(source)]) != evidence["source_git_blob"]:
            raise ValueError("Production source differs from the checked-out commit")
        sdk_path = Path(command(["/usr/bin/xcrun", "--sdk", sdk, "--show-sdk-path"]))
        if not sdk_path.is_dir() or not sdk_path.resolve().is_relative_to(developer.resolve()):
            raise ValueError("SDK is not inside the selected existing Xcode")
        version = command(["/usr/bin/xcrun", "--sdk", sdk, "--show-sdk-version"])
        sdk_version(version)
        evidence.update(sdk_path=str(sdk_path), sdk_version=version)
        tools = {name: validate_tool_path(command(["/usr/bin/xcrun", "--sdk", sdk, "--find", name]), developer)
                 for name in ("swiftc", "nm", "swift-demangle")}
        evidence["swift_version"] = command([tools["swiftc"], "--version"])
        flags = compile_flags(sdk, sdk_path, build)
        guard = build / "CompilerGuard.swift"
        guard.write_text(compiler_guard(sdk), encoding="utf-8")
        command([tools["swiftc"], *flags, "-typecheck", str(guard)])
        evidence["compiler_guard_passed"] = True
        obj = build / "BackgroundSharingSession.o"
        # Remove a stale output before the compiler runs; it must emit this run's object.
        obj.unlink(missing_ok=True)
        command([tools["swiftc"], *flags, "-emit-object", str(source), "-o", str(obj)])
        require_arm64_object(obj.read_bytes())
        symbols = command([tools["nm"], "-U", str(obj)])
        demangled = command([tools["swift-demangle"]], input_text=symbols)
        evidence["defined_implementation_symbols"] = require_defined_methods(demangled)
        if source.read_bytes() != original:
            raise ValueError("Production source changed during compilation")
        evidence.update(status="passed", system_background_sharing_compiled=True,
                        object_sha256=hashlib.sha256(obj.read_bytes()).hexdigest(),
                        object_bytes=obj.stat().st_size, object_format="arm64 Mach-O MH_OBJECT")
    except (OSError, ValueError, RuntimeError) as error:
        evidence["error"] = str(error)
        with log_path.open("a", encoding="utf-8") as log:
            log.write("\nFAILED: " + str(error) + "\n")
        raise
    finally:
        (build / "EVIDENCE.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", choices=tuple(TARGETS), required=True)
    args = parser.parse_args()
    try:
        evidence = run_gate(args.sdk)
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"{args.sdk}: compiled the real background driver; no linking or runtime validation")
    print("Object SHA-256: " + evidence["object_sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
