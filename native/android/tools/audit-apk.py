#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Read-only structural audit for the unsigned development APK; not device execution."""
import argparse, hashlib, json, pathlib, struct, subprocess, zipfile
from apk_manifest import VERSION_CODE, VERSION_NAME, audit_manifest
p = argparse.ArgumentParser()
p.add_argument('apk', type=pathlib.Path)
p.add_argument('--sdk', type=pathlib.Path, required=True)
p.add_argument('--report', type=pathlib.Path, required=True)
p.add_argument('--abis', nargs='+', choices=['arm64-v8a', 'x86_64'], default=['arm64-v8a', 'x86_64'],
               help='Exact expected ABI set; defaults to the universal APK')
a = p.parse_args()
tools = a.sdk / 'build-tools/35.0.0'
report = {'apk': a.apk.name, 'sha256': hashlib.sha256(a.apk.read_bytes()).hexdigest(), 'bytes': a.apk.stat().st_size, 'native_libraries': {}}
with zipfile.ZipFile(a.apk) as apk:
    for asset in ['assets/licenses/ENGINE-NOTICES.txt', 'assets/licenses/GPL-3.0.txt', 'assets/licenses/PROJECT-MIT.txt', 'classes.dex', 'AndroidManifest.xml']:
        assert apk.getinfo(asset).file_size > 0, asset
    expected_native = {f'lib/{abi}/libgojni.so' for abi in a.abis}
    assert {name for name in apk.namelist() if name.startswith('lib/')} == expected_native, 'Unexpected or missing native ABI payload'
    for abi in a.abis:
        machine = {'arm64-v8a': 183, 'x86_64': 62}[abi]
        name = f'lib/{abi}/libgojni.so'; data = apk.read(name)
        assert data[:6] == b'\x7fELF\x02\x01', 'Expected 64-bit little-endian ELF'
        assert struct.unpack_from('<H', data, 18)[0] == machine, abi
        phoff = struct.unpack_from('<Q', data, 32)[0]
        entsize, number = struct.unpack_from('<HH', data, 54)
        loads = []
        for i in range(number):
            kind, flags, offset, virtual, physical, filesz, memsz, align = struct.unpack_from('<IIQQQQQQ', data, phoff+i*entsize)
            if kind == 1:
                assert align >= 16384 and align & (align-1) == 0, f'{abi} ELF page alignment {align}'
                assert offset % align == virtual % align, 'ELF alignment congruence'
                loads.append(align)
        assert loads and apk.getinfo(name).compress_type == zipfile.ZIP_STORED
        report['native_libraries'][abi] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'load_segment_alignments': loads, 'stored_uncompressed': True}
aligned = subprocess.run([str(tools/'zipalign'), '-c', '-P', '16', '-v', '4', str(a.apk)], text=True, capture_output=True)
assert aligned.returncode == 0, aligned.stdout + aligned.stderr
report['zipalign_16k'] = 'passed'
badging = subprocess.check_output([str(tools/'aapt2'), 'dump', 'badging', str(a.apk)], text=True)
for expected in ["package: name='org.psportal.host'", "minSdkVersion:'26'", "targetSdkVersion:'36'", "launchable-activity: name='org.psportal.host.MainActivity'"]:
    assert expected in badging, expected
assert 'RECEIVE_BOOT_COMPLETED' not in badging
manifest = subprocess.check_output([str(tools/'aapt2'), 'dump', 'xmltree', str(a.apk), '--file', 'AndroidManifest.xml'], text=True)
a.report.parent.mkdir(parents=True, exist_ok=True)
(a.report.parent/'compiled-manifest.txt').write_text(manifest)
report['compiled_manifest'] = audit_manifest(manifest)
report['package'] = 'org.psportal.host'; report['min_sdk'] = 26; report['target_sdk'] = 36
report['version_code'] = VERSION_CODE; report['version_name'] = VERSION_NAME
signature = subprocess.run([str(tools/'apksigner'), 'verify', '--verbose', str(a.apk)], text=True, capture_output=True)
# This workflow intentionally creates no signing identity. Require the specific
# unsigned failure, not an arbitrary verifier error, so packaging defects fail.
assert signature.returncode != 0 and 'Missing META-INF/MANIFEST.MF' in signature.stderr, signature.stdout + signature.stderr
report['signing'] = 'unsigned; Android installation requires separately authorized signing'
a.report.parent.mkdir(parents=True, exist_ok=True)
a.report.write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
