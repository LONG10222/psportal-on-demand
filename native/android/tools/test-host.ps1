param([string]$Python = 'python')
# SPDX-License-Identifier: GPL-3.0-only
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$out = Join-Path $project 'build/host-tests'
$src = Join-Path $project 'app/src/main/java/org/psportal/host'
New-Item -ItemType Directory -Force $out | Out-Null
$sources = @('HostConfig', 'SessionController', 'LanSetup', 'SubscriptionAccounting',
    'RuntimePresentation', 'RuntimeNodePresentation', 'ProductMode', 'BackgroundPolicy', 'PhoneVpnState') |
    ForEach-Object { Join-Path $src ($_ + '.java') }
$tests = @('HostTests', 'RuntimeNodePresentationTests', 'BackgroundPolicyTests', 'PhoneVpnStateTests')
$sources += $tests | ForEach-Object { Join-Path $project ('tests/' + $_ + '.java') }
& javac -encoding UTF-8 --release 17 -d $out @sources
if ($LASTEXITCODE -ne 0) { throw 'Java host test compilation failed' }
foreach ($test in $tests) {
    & java -cp $out ('org.psportal.host.' + $test)
    if ($LASTEXITCODE -ne 0) { throw "Java host test failed: $test" }
}
& $Python (Join-Path $project 'tests/check_project.py')
if ($LASTEXITCODE -ne 0) { throw 'Android source/resource guardrails failed' }
& $Python (Join-Path $project 'tests/test_apk_manifest.py')
if ($LASTEXITCODE -ne 0) { throw 'APK audit helper tests failed' }
