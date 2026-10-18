#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Bound optional CI artifact storage; never alters the original test results."""
import pathlib
import shutil

MIB = 1024 * 1024
ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
OUTPUT = BUILD / "diagnostics"


def collect(build=BUILD, output=OUTPUT):
    output.mkdir(parents=True, exist_ok=True)
    report = []
    budget = 20 * MIB
    for log in sorted((build / "logs").glob("*.log")):
        if log.is_symlink() or not log.is_file():
            continue
        size = log.stat().st_size
        count = min(size, 4 * MIB, budget)
        if count <= 0:
            report.append(f"Omitted {log.name}: log budget reached ({size} bytes).")
            continue
        with log.open("rb") as source:
            source.seek(size - count)
            (output / log.name).write_bytes(source.read(count))
        budget -= count
        report.append(f"{log.name}: retained final {count} of {size} bytes.")
    results = build / "TestResults.xcresult"
    if results.is_dir():
        entries = list(results.rglob("*"))
        size = sum(path.stat().st_size for path in entries if path.is_file() and not path.is_symlink())
        if not any(path.is_symlink() for path in entries) and size <= 50 * MIB:
            shutil.copytree(results, output / results.name, dirs_exist_ok=True)
            report.append(f"Complete TestResults.xcresult: {size} bytes.")
        else:
            report.append(f"TestResults.xcresult omitted: {size} bytes exceeds 50 MiB or contains links. Review simulator-tests.log and Actions logs; full results are not retained.")
    else:
        report.append("No XCTest result bundle was produced.")
    summary = "\n".join(report) + "\nArtifact limits: 20 MiB log tails plus 50 MiB XCTest bundle; one-day retention.\n"
    (output / "DIAGNOSTICS.txt").write_text(summary, encoding="utf-8")
    print(summary, end="")


if __name__ == "__main__":
    collect()
