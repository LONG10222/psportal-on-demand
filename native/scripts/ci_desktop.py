#!/usr/bin/env python3
"""Run host-native tests and package matching binaries, source and evidence for CI."""
# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TAGS = 'no_easytier,no_zerotier,no_tailscale'
OUT = ROOT / 'dist' / 'ci-desktop'


def run(args, log=None, timeout=1200):
    print('+ ' + ' '.join(args), flush=True)
    if log:
        with (OUT / log).open('w', encoding='utf-8') as stream:
            result = subprocess.run(args, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        if result.returncode:
            print((OUT / log).read_text(encoding='utf-8', errors='replace')[-20000:])
            result.check_returncode()
    else:
        subprocess.run(args, cwd=ROOT, check=True, timeout=timeout)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # Prevent the generated licenses/vendor sources being scanned as local Go packages.
    (ROOT / 'dist' / 'go.mod').write_text('module psportal.local/build-artifacts\n\ngo 1.26.0\n', encoding='utf-8')
    system = {'Linux': 'linux', 'Windows': 'windows', 'Darwin': 'darwin'}[platform.system()]
    arch = {'x86_64': 'amd64', 'AMD64': 'amd64', 'ARM64': 'arm64', 'aarch64': 'arm64', 'arm64': 'arm64'}[platform.machine()]
    go = os.environ.get('GO', 'go')
    run([go, 'mod', 'download'])
    run([go, 'mod', 'verify'], 'module-verify.txt')
    run([go, 'test', '-count=1', '-json', '-timeout=5m', '-tags', TAGS, './...'], 'go-tests.jsonl')
    race = system != 'windows'
    if race:
        run([go, 'test', '-race', '-count=1', '-timeout=5m', '-tags', TAGS, './engine'], 'race-tests.txt')
    run([go, 'vet', '-tags', TAGS, './...'], 'go-vet.txt')
    run([sys.executable, 'scripts/build.py', '--go', go, '--target', f'{system}/{arch}'])
    label = f'psportal-{system}-{arch}'
    binary = ROOT / 'dist' / label / ('psportal.exe' if system == 'windows' else 'psportal')
    run([sys.executable, 'scripts/verify_binary.py', str(binary)], 'binary-smoke.txt', timeout=90)
    run([sys.executable, 'scripts/source_release.py', '--go', go])
    archive = ROOT / 'dist' / (label + ('.zip' if system == 'windows' else '.tar.gz'))
    for path in (archive, ROOT / 'dist' / 'psportal-native-corresponding-source.tar.gz'):
        shutil.copyfile(path, OUT / path.name)
    for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copyfile(ROOT / name, OUT / name)
    shutil.copyfile(ROOT / 'dist' / 'licenses' / 'ENGINE-NOTICES.txt', OUT / 'ENGINE-NOTICES.txt')
    events = [json.loads(line) for line in (OUT / 'go-tests.jsonl').read_text(encoding='utf-8').splitlines() if line.startswith('{')]
    evidence = {
        'git_commit': os.environ.get('GITHUB_SHA', ''),
        'system': system, 'architecture': arch, 'platform': platform.platform(),
        'go_version': subprocess.check_output([go, 'version'], text=True).strip(),
        'python_version': platform.python_version(),
        'native_runtime_tested': True, 'loopback_only_fixtures': True,
        'passed_test_and_subtest_results': sum(e.get('Action') == 'pass' and bool(e.get('Test')) for e in events),
        'race_tested': race,
        'race_note': 'engine race tests passed' if race else 'Windows race tests skipped; no C toolchain installed by this workflow',
        'signed_or_notarized': False,
        'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
    }
    (OUT / 'VALIDATION.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    files = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != 'SHA256SUMS')
    if sum(path.stat().st_size for path in files) > 200 * 1024 * 1024:
        raise RuntimeError('CI artifact exceeds the 200 MiB publication budget')
    (OUT / 'SHA256SUMS').write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n' for path in files), encoding='ascii')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
