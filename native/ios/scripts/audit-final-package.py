#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Verify an extracted final ZIP against its content list and built app."""
import hashlib
import json
import os
import pathlib
import plistlib
import re
import stat
import struct
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    result = {}
    for path in [root, *root.rglob("*")]:
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            assert path.resolve().is_relative_to(root.resolve()), "App symlink escapes its bundle"
            value = ("symlink", mode, os.readlink(path))
        elif path.is_file():
            value = ("file", mode, digest(path))
        elif path.is_dir():
            value = ("directory", mode, "")
        else:
            raise AssertionError("Unsupported special app member: " + str(path))
        result[path.relative_to(root).as_posix()] = value
    return result


def audit(package, built_app):
    package = package.resolve()
    assert not (package / "CONTENT-SHA256SUMS").is_symlink(), "Content manifest must not be a symlink"
    entries = (package / "CONTENT-SHA256SUMS").read_text().splitlines()
    assert entries, "Content manifest is empty"
    names = set()
    for line in entries:
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\r\n]+)", line)
        assert match, "Malformed lowercase SHA-256 content manifest line"
        expected, name = match.groups()
        relative = pathlib.PurePosixPath(name)
        assert (relative.parts and not relative.is_absolute() and relative.as_posix() == name
                and not any(part in {"", ".", ".."} for part in relative.parts)
                and "\\" not in name and all(32 <= ord(char) != 127 for char in name)), "Unsafe content manifest name"
        assert name not in names, "Duplicate content manifest name: " + name
        names.add(name)
        path = package / name
        assert path.resolve().is_relative_to(package), "Content manifest escaped package"
        assert digest(path) == expected, "Content hash changed: " + name
    for path in package.rglob("*"):
        if path.is_symlink():
            assert path.is_relative_to(package / "PSPortalHost.app"), "Non-app package symlink requires review"
            assert path.resolve().is_relative_to(package / "PSPortalHost.app"), "App symlink escapes its bundle"
    expected_names = {path.relative_to(package).as_posix() for path in package.rglob("*")
                      if path.is_file() and path != package / "CONTENT-SHA256SUMS"}
    assert names == expected_names, "Content manifest omitted or added package files"
    app = package / "PSPortalHost.app"
    assert inventory(app) == inventory(built_app), "Final archive changed app bytes, members or permission modes"
    assert (package / "psportal-native-corresponding-source.tar.gz").is_file()
    assert not list(app.rglob("*.tar.gz")), "Source archive must be beside the app, not injected into it"
    assert not list(app.rglob("*.framework")), "Unexpected nested framework; add explicit nested signature audit"
    assert not list(app.rglob("*.dylib")), "Unexpected nested dylib; add explicit nested signature audit"
    info = plistlib.loads((app / "Info.plist").read_bytes())
    binary = (app / info["CFBundleExecutable"]).read_bytes()
    assert binary[:4] == b"\xcf\xfa\xed\xfe"
    offset, signature = 32, False
    for _ in range(struct.unpack_from("<I", binary, 16)[0]):
        command, size = struct.unpack_from("<II", binary, offset)
        if command == 0x1D:
            signature = True
        offset += size
    simulator = info["CFBundleSupportedPlatforms"] == ["iPhoneSimulator"]
    assert not (app / "embedded.mobileprovision").exists()
    if not simulator:
        assert not signature and not (app / "_CodeSignature").exists(), "Device app must remain unsigned"
    return {"package": str(package), "content_entries_verified": len(entries),
            "app_members_modes_and_links_match_build": True, "app_member_count": len(inventory(app)),
            "source_sha256": digest(package / "psportal-native-corresponding-source.tar.gz"),
            "executable_sha256": digest(app / info["CFBundleExecutable"]),
            "platform": info["CFBundleSupportedPlatforms"], "embedded_code_signature": signature,
            "resource_seal_present": (app / "_CodeSignature/CodeResources").exists(),
            "scope": "A linker-generated Simulator code signature is not identity signing or a sealed distribution app"}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: audit-final-package.py EXTRACTED_PACKAGE ORIGINAL_BUILT_APP")
    print(json.dumps(audit(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])), indent=2))
