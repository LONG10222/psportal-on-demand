#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# One native-host-architecture simulator build. No signing identities or devices.
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
export IOS_TARGET="iossimulator/$GOARCH"
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
  printf 'Requested embedded engine target: %s\n' "$IOS_TARGET"
} | tee "$LOGS/toolchains.log"

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
  printf '\nBuild and XCTest command exited successfully. Physical Data Protection test is explicitly skipped on Simulator.\n'
  printf 'No physical iPhone/iPad installation, real Portal session, signing identity, provisioning, or App Store validation is implied.\n'
  printf 'The app runs only while foregrounded; subscription URLs are never persisted.\n'
} > "$STAGING/BUILD-INFO.txt"
ditto -c -k --keepParent "$STAGING" "$OUTPUT/$PACKAGE.zip"
python3 - "$OUTPUT/$PACKAGE.zip" <<'PY_SIZE'
import pathlib,sys
size=pathlib.Path(sys.argv[1]).stat().st_size
print(f'Simulator artifact size: {size} bytes (maximum 200 MiB)')
assert size <= 200*1024*1024, 'Artifact exceeds bounded storage budget; not uploaded'
PY_SIZE
(cd "$OUTPUT" && shasum -a 256 "$PACKAGE.zip" > SHA256SUMS)
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    printf '### iOS Simulator source build\n\n'
    printf -- '- Compiled the real embedded engine and simulator app for `%s`\n' "$GOARCH"
    printf -- '- Native Go fixture tests and the Xcode test command passed; see the test result bundle for individual tests/skips\n'
    printf -- '- Download includes the app, GPL/dependency notices, matching source+vendor archive and SHA-256\n'
    printf -- '- Simulator-only artifact. Physical iPhone/iPad and Portal validation remain open\n'
  } >> "$GITHUB_STEP_SUMMARY"
fi

