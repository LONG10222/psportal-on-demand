#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Choose an installed iPhone runtime supported by the selected Xcode SDK."""
import json
import re
import sys


def version(text):
    parts = tuple(int(part) for part in re.split(r"[.-]", text))
    return parts + (0,) * (3 - len(parts))


def select_device(devices, sdk):
    candidates = []
    for runtime, entries in devices.items():
        match = re.fullmatch(r"com\.apple\.CoreSimulator\.SimRuntime\.iOS-(\d+(?:-\d+)*)", runtime)
        if not match:
            continue
        current = version(match.group(1))
        if not version("16.0") <= current <= version(sdk):
            continue
        for device in entries:
            if device.get("isAvailable") and device.get("name", "").startswith("iPhone"):
                candidates.append((current, device["name"], device["udid"]))
    if not candidates:
        raise ValueError("No installed, available iPhone runtime between iOS 16 and selected SDK " + sdk + ". No runtime was downloaded.")
    return max(candidates)[2]


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as source:
        devices = json.load(source)["devices"]
    try:
        print(select_device(devices, sys.argv[2]))
    except ValueError as error:
        raise SystemExit(str(error)) from error
