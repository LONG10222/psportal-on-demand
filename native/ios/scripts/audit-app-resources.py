#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded resource/import check, not a complete Apple privacy/compliance audit."""
import hashlib
import json
import pathlib
import plistlib
import struct
import sys

EXPECTED = {
    "NSPrivacyAccessedAPICategoryFileTimestamp": ["C617.1"],
    "NSPrivacyAccessedAPICategorySystemBootTime": ["35F9.1"],
}


def undefined_symbols(data):
    # CI builds one native architecture, never a fat binary. Fail closed if this changes.
    assert data[:4] == b"\xcf\xfa\xed\xfe", "Expected little-endian 64-bit Mach-O"
    count = struct.unpack_from("<I", data, 16)[0]
    offset, found, symbols = 32, False, set()
    for _ in range(count):
        command, size = struct.unpack_from("<II", data, offset)
        assert size >= 8 and offset + size <= len(data), "Invalid load command"
        if command == 2:  # LC_SYMTAB
            found = True
            symoff, nsyms, stroff, strsize = struct.unpack_from("<4I", data, offset + 8)
            assert symoff + nsyms * 16 <= len(data) and stroff + strsize <= len(data)
            for index in range(nsyms):
                strx, kind, _, _, _ = struct.unpack_from("<IBBHQ", data, symoff + index * 16)
                if not kind & 0xE0 and kind & 0x0E == 0 and kind & 1:
                    assert strx < strsize, "Invalid external symbol string"
                    end = data.find(b"\0", stroff + strx, stroff + strsize)
                    assert end >= 0, "Unterminated symbol"
                    symbols.add(data[stroff + strx:end].decode("utf-8"))
        offset += size
    assert found, "Mach-O symbol table missing; manual audit required"
    return symbols


def audit(app):
    info = plistlib.loads((app / "Info.plist").read_bytes())
    binary = (app / info["CFBundleExecutable"]).read_bytes()
    symbols = undefined_symbols(binary)
    manifest_path = app / "PrivacyInfo.xcprivacy"
    manifest = plistlib.loads(manifest_path.read_bytes())
    entries = manifest["NSPrivacyAccessedAPITypes"]
    reasons = {entry["NSPrivacyAccessedAPIType"]: entry["NSPrivacyAccessedAPITypeReasons"] for entry in entries}
    assert len(reasons) == len(entries) and reasons == EXPECTED, "Review changed required-reason declarations"
    assert info["NSLocalNetworkUsageDescription"]
    assert not info.get("UIBackgroundModes") and not info.get("UIFileSharingEnabled")
    assert not (app / "embedded.mobileprovision").exists(), "Unexpected device provisioning"
    assert not list(app.rglob("*.appex")), "Unexpected extension target"
    # Newly linked categories need review instead of silently adding blanket reasons.
    review_symbols = {
        "_statfs", "_fstatfs", "_statvfs", "_fstatvfs", "_getattrlist", "_fgetattrlist",
        "_getattrlistat", "_getattrlistbulk", "_OBJC_CLASS_$_NSUserDefaults",
        "_CFPreferencesCopyAppValue", "_CFPreferencesSetAppValue",
    }
    assert not symbols & review_symbols, "New privacy-sensitive import needs review: " + repr(sorted(symbols & review_symbols))
    covered = {"_stat", "_fstat", "_fstatat", "_lstat", "_mach_absolute_time"}
    notices = {}
    for name in ("GPL-3.0.txt", "PROJECT-MIT.txt", "THIRD-PARTY-NOTICES.txt", "ENGINE-NOTICES.txt"):
        matches = list(app.rglob(name))
        assert len(matches) == 1, "Missing/ambiguous bundled notice: " + name
        data = matches[0].read_bytes()
        assert len(data) > 100, "Empty bundled notice: " + name
        notices[name] = hashlib.sha256(data).hexdigest()
    return {
        "bundle": str(app), "bundle_id": info["CFBundleIdentifier"],
        "platform": info["CFBundleSupportedPlatforms"], "required_reason_imports": sorted(symbols & covered),
        "privacy_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "required_reasons": reasons, "notice_sha256": notices,
        "app_icon_declared": bool(info.get("CFBundleIcons") or info.get("CFBundleIconName")),
        "scope": "Required-reason/resource guardrail only; not App Store validation or a full data-flow/privacy audit",
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: audit-app-resources.py APP [APP ...]")
    print(json.dumps([audit(pathlib.Path(path)) for path in sys.argv[1:]], indent=2))
