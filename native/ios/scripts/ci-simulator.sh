#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Native-host simulator tests plus unsigned iPhoneOS ARM64 compilation.
# No signing identities, provisioning or physical-device installation.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NATIVE="$(cd "$ROOT/.." && pwd)"
[[ "$(uname -s)" == Darwin ]] || { echo "Simulator compilation requires macOS/Xcode." >&2; exit 1; }
for tool in go xcodebuild xcrun python3 xcodegen; do
  command -v "$tool" >/dev/null || { echo "Missing prerequisite: $tool" >&2; exit 1; }
done
case "$(uname -m)" in
  arm64) ARCH=arm64; GOARCH=arm64 ;;
  x86_64) ARCH=x86_64; GOARCH=amd64 ;;
  *) echo "Unsupported macOS runner architecture" >&2; exit 1 ;;
esac
export IOS_TARGET="ios/arm64,iossimulator/$GOARCH"
export GOFLAGS="${GOFLAGS:-} -buildvcs=false"
export PATH="$ROOT/.tools/bin:$PATH"
LOGS="$ROOT/build/logs"
mkdir -p "$LOGS"
cd "$NATIVE"
{
  go version
  xcodebuild -version
  xcodegen --version
  xcrun --sdk iphonesimulator --show-sdk-version
  xcrun --sdk iphoneos --show-sdk-version
  printf 'Requested embedded engine target: %s\n' "$IOS_TARGET"
} | tee "$LOGS/toolchains.log"

python3 "$ROOT/scripts/check-ci-helpers.py" 2>&1 | tee "$LOGS/ci-helpers.log"

# Local-fixture Go tests exercise the real adapters without any subscription.
go test -tags=no_easytier,no_zerotier,no_tailscale ./engine ./mobile 2>&1 | tee "$LOGS/go-tests.log"
"$ROOT/scripts/build-engine.sh" 2>&1 | tee "$LOGS/engine-build.log"
"$ROOT/scripts/generate-project.sh" 2>&1 | tee "$LOGS/project-generation.log"
python3 "$ROOT/scripts/check-source.py" 2>&1 | tee "$LOGS/source-guardrails.log"

COMMON=(-project "$ROOT/PSPortalHost.xcodeproj" -scheme PSPortalHost
  -sdk iphonesimulator -derivedDataPath "$ROOT/build/DerivedData"
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO
  "ARCHS=$ARCH" ONLY_ACTIVE_ARCH=YES)
xcodebuild "${COMMON[@]}" -configuration Release \
  -destination 'generic/platform=iOS Simulator' build 2>&1 | tee "$LOGS/simulator-build.log"

xcrun simctl list devices available -j > "$ROOT/build/available-simulators.json"
SDK_VERSION="$(xcrun --sdk iphonesimulator --show-sdk-version)"
SIMULATOR_ID="$(python3 "$ROOT/scripts/select-simulator.py" "$ROOT/build/available-simulators.json" "$SDK_VERSION")"
printf 'Selected installed simulator %s for SDK %s\n' "$SIMULATOR_ID" "$SDK_VERSION" | tee "$LOGS/simulator-selection.log"
# Xcode boots an existing runner simulator; never installs on a physical device.
xcodebuild "${COMMON[@]}" -configuration Debug \
  -destination "platform=iOS Simulator,id=$SIMULATOR_ID" -destination-timeout 120 \
  -parallel-testing-enabled NO -maximum-concurrent-test-simulator-destinations 1 \
  -resultBundlePath "$ROOT/build/TestResults.xcresult" test 2>&1 | tee "$LOGS/simulator-tests.log"

APP="$ROOT/build/DerivedData/Build/Products/Release-iphonesimulator/PSPortalHost.app"
python3 - "$APP" <<'PY'
import pathlib,plistlib,sys
app=pathlib.Path(sys.argv[1])
with (app/'Info.plist').open('rb') as source: info=plistlib.load(source)
assert 'iPhoneSimulator' in info.get('CFBundleSupportedPlatforms',[]), 'Artifact is not an iOS Simulator app'
assert (app/info['CFBundleExecutable']).is_file(), 'Compiled app executable missing'
assert not (app/'embedded.mobileprovision').exists(), 'Unexpected device provisioning profile'
for notice in ('GPL-3.0.txt','PROJECT-MIT.txt','THIRD-PARTY-NOTICES.txt','ENGINE-NOTICES.txt'):
    assert any(app.rglob(notice)), 'Bundled notice missing: '+notice
print('Verified simulator executable, platform metadata and bundled license resources')
PY
xcrun vtool -show-build "$APP/PSPortalHost" > "$LOGS/app-platform.log"

# Compilation/linkage gate only. This does not install on or run a physical device.
xcodebuild -project "$ROOT/PSPortalHost.xcodeproj" -scheme PSPortalHost \
  -sdk iphoneos -configuration Release -destination 'generic/platform=iOS' \
  -derivedDataPath "$ROOT/build/DerivedData" CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO ARCHS=arm64 ONLY_ACTIVE_ARCH=YES build \
  2>&1 | tee "$LOGS/unsigned-device-build.log"
DEVICE_APP="$ROOT/build/DerivedData/Build/Products/Release-iphoneos/PSPortalHost.app"
python3 - "$DEVICE_APP" <<'PY_DEVICE'
import pathlib,plistlib,sys
app=pathlib.Path(sys.argv[1])
with (app/'Info.plist').open('rb') as source: info=plistlib.load(source)
assert 'iPhoneOS' in info.get('CFBundleSupportedPlatforms',[]), 'Artifact is not an iPhoneOS app'
assert (app/info['CFBundleExecutable']).is_file(), 'Device executable missing'
assert not (app/'embedded.mobileprovision').exists(), 'Unexpected provisioning profile'
print('Verified unsigned iPhoneOS ARM64 build metadata. No device installation/runtime proof.')
PY_DEVICE
xcrun vtool -show-build "$DEVICE_APP/PSPortalHost" > "$LOGS/device-platform.log"

# XCTest may shut down its destination (or use a temporary clone). Explicitly
# boot the existing selected simulator before the independent Release launch.
xcrun simctl bootstatus "$SIMULATOR_ID" -b 2>&1 | tee "$LOGS/release-simulator-boot.log"
# Launch the Release simulator app separately from the Debug XCTest host.
xcrun simctl install "$SIMULATOR_ID" "$APP"
LAUNCH="$(xcrun simctl launch --terminate-running-process "$SIMULATOR_ID" org.psportal.host.foreground)"
printf '%s\n' "$LAUNCH" | tee "$LOGS/release-launch.log"
PID="${LAUNCH##*: }"
sleep 3
kill -0 "$PID" # The Release app must still be alive, not a launch-then-crash.
xcrun simctl io "$SIMULATOR_ID" screenshot --type=png "$LOGS/simulator-app.png"
python3 scripts/source_release.py 2>&1 | tee "$LOGS/corresponding-source.log"

OUTPUT="$NATIVE/dist/ios-simulator"
PACKAGE="psportal-ios-simulator-$GOARCH"
STAGING="$ROOT/build/package/$PACKAGE"
mkdir -p "$OUTPUT" "$STAGING"
ditto "$APP" "$STAGING/PSPortalHost.app"
cp "$NATIVE/LICENSE" "$STAGING/LICENSE"
cp "$NATIVE/THIRD_PARTY_NOTICES.md" "$ROOT/README.md" "$STAGING/"
cp "$NATIVE/dist/psportal-native-corresponding-source.tar.gz" "$STAGING/"
cp -R "$NATIVE/dist/licenses" "$STAGING/licenses"
{
  printf 'Artifact: iOS Simulator %s development app, CODE_SIGNING_ALLOWED=NO\n' "$GOARCH"
  printf 'Source commit: %s\n' "$(git -C "$NATIVE" rev-parse HEAD)"
  printf 'Workflow run: %s\n' "${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-local}/actions/runs/${GITHUB_RUN_ID:-local}"
  cat "$LOGS/toolchains.log"
  printf '\nBuild and XCTest command exited successfully. Tests include real generated-framework HTTP/CONNECT direct fixtures, denial and Stop closure. Physical Data Protection test is explicitly skipped on Simulator.\n'
  printf 'Unsigned iPhoneOS ARM64 app compiled/linked separately; not installed or run on a device.\n'
  printf 'No physical iPhone/iPad installation, real Portal session, signing identity, provisioning, or App Store validation is implied.\n'
  printf 'The app runs only while foregrounded; subscription URLs are never persisted.\n'
} > "$STAGING/BUILD-INFO.txt"
# Hash exact matching source, retained notices and executable, not just ZIP wrapper.
python3 - "$STAGING" <<'PY_HASH'
import hashlib,pathlib,sys
root=pathlib.Path(sys.argv[1])
paths=[root/'psportal-native-corresponding-source.tar.gz',root/'PSPortalHost.app/PSPortalHost']
paths += sorted((root/'licenses').rglob('*'))
paths += sorted((root/'PSPortalHost.app').rglob('*.txt'))
(root/'CONTENT-SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(root).as_posix()+'\n' for p in paths if p.is_file()))
PY_HASH
ditto -c -k --keepParent "$STAGING" "$OUTPUT/$PACKAGE.zip"
DEVICE_PACKAGE="psportal-ios-unsigned-device-arm64"
DEVICE_STAGING="$ROOT/build/package/$DEVICE_PACKAGE"
mkdir -p "$DEVICE_STAGING"
ditto "$DEVICE_APP" "$DEVICE_STAGING/PSPortalHost.app"
cp "$STAGING/psportal-native-corresponding-source.tar.gz" "$STAGING/LICENSE" "$STAGING/README.md" "$STAGING/THIRD_PARTY_NOTICES.md" "$DEVICE_STAGING/"
cp -R "$STAGING/licenses" "$DEVICE_STAGING/licenses"
{
  printf 'Unsigned iPhoneOS ARM64 compilation artifact. NOT INSTALLABLE as supplied.\n'
  printf 'Owner-controlled signing/provisioning and real-device tests are still required.\n'
  printf 'No Apple account, signing identity, profile or physical device was used.\n\n'
  cat "$STAGING/BUILD-INFO.txt"
} > "$DEVICE_STAGING/BUILD-INFO.txt"
python3 - "$DEVICE_STAGING" <<'PY_DEVICE_HASH'
import hashlib,pathlib,sys
root=pathlib.Path(sys.argv[1])
paths=[root/'psportal-native-corresponding-source.tar.gz',root/'PSPortalHost.app/PSPortalHost']
paths += sorted((root/'licenses').rglob('*'))
paths += sorted((root/'PSPortalHost.app').rglob('*.txt'))
(root/'CONTENT-SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(root).as_posix()+'\n' for p in paths if p.is_file()))
PY_DEVICE_HASH
ditto -c -k --keepParent "$DEVICE_STAGING" "$OUTPUT/$DEVICE_PACKAGE.zip"
python3 - "$OUTPUT/$PACKAGE.zip" "$OUTPUT/$DEVICE_PACKAGE.zip" <<'PY_SIZE'
import pathlib,sys
size=sum(pathlib.Path(p).stat().st_size for p in sys.argv[1:])
print(f'Combined simulator/device artifact size: {size} bytes (maximum 200 MiB)')
assert size <= 200*1024*1024, 'Artifact exceeds bounded storage budget; not uploaded'
PY_SIZE
(cd "$OUTPUT" && shasum -a 256 "$PACKAGE.zip" "$DEVICE_PACKAGE.zip" > SHA256SUMS)
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    printf '### iOS Simulator source build\n\n'
    printf -- '- Compiled the real embedded engine and simulator app for `%s`\n' "$GOARCH"
    printf -- '- Native Go fixture tests and the Xcode test command passed; see the test result bundle for individual tests/skips\n'
    printf -- '- Separate unsigned iPhoneOS ARM64 app compiled and linked; not installed or run on hardware\n'
    printf -- '- Downloads include apps, GPL/dependency notices, matching source+vendor archives and content/ZIP SHA-256 manifests\n'
    printf -- '- Simulator runtime evidence only. Physical iPhone/iPad and Portal validation remain open\n'
  } >> "$GITHUB_STEP_SUMMARY"
fi

