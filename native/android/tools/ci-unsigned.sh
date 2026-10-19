#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Builds unsigned artifacts only; no SDK agreement acceptance or signing keys.
set -euo pipefail
ANDROID_PROJECT=$(cd "$(dirname "$0")/.." && pwd)
NATIVE=$(cd "$ANDROID_PROJECT/.." && pwd)
cd "$ANDROID_PROJECT"
mkdir -p build
exec > >(tee build/ci-build.log) 2>&1
export JAVA_HOME="${JAVA_HOME_21_X64:-${JAVA_HOME:?Set JAVA_HOME to an installed JDK 17+}}"
export ANDROID_HOME="${ANDROID_HOME:-${ANDROID_SDK_ROOT:?Set ANDROID_HOME to an installed, licensed SDK}}"
export ANDROID_NDK_HOME="$ANDROID_HOME/ndk/30.0.16248370"
export PATH="$JAVA_HOME/bin:$(go env GOPATH)/bin:$PATH"
if [[ ! -f "$ANDROID_HOME/platforms/android-36/android.jar" || ! -x "$ANDROID_HOME/build-tools/35.0.0/aapt2" || ! -f "$ANDROID_NDK_HOME/source.properties" ]]; then
  if [[ "${PSPORTAL_INSTALL_SDK:-0}" != 1 ]]; then
    echo 'Exact SDK packages are missing. Enable the explicit install input only with approved SDK terms.' >&2
    exit 1
  fi
  SDKMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
  # No blanket --licenses/yes or fabricated acceptance hashes. A new or changed
  # agreement receives EOF and fails; the maintainer must approve it separately.
  "$SDKMANAGER" --sdk_root="$ANDROID_HOME" 'platforms;android-36' 'build-tools;35.0.0' 'ndk;30.0.16248370' </dev/null
fi
test -f "$ANDROID_HOME/platforms/android-36/android.jar"
test -x "$ANDROID_HOME/build-tools/35.0.0/aapt2"
test -f "$ANDROID_NDK_HOME/source.properties"
java -version
go version
./tools/test-host.sh
python3 tests/test_apk_manifest.py
./tools/test-binding-config.sh
python3 "$NATIVE/scripts/verify_mihomo_patch.py"
(cd "$NATIVE" && go test -race github.com/metacubex/mihomo/log github.com/metacubex/mihomo/tunnel)
(cd "$NATIVE/third_party/mihomo" && go test -race ./common/queue)
(cd "$NATIVE" && go test -race -tags=no_easytier,no_zerotier,no_tailscale,with_gvisor ./androidcore ./androidmobile)
(cd "$NATIVE/scripts" && python3 -m unittest test_licenses test_source_release test_mihomo_patch)
(cd "$NATIVE" && ./scripts/mobile.sh tools && ./scripts/mobile.sh android)
./gradlew --no-daemon --max-workers=2 :app:assembleRelease :app:lintRelease
python3 tools/audit-apk.py app/build/outputs/apk/release/app-release-unsigned.apk \
  --sdk "$ANDROID_HOME" --report build/reports/apk-audit.json
python3 "$NATIVE/scripts/source_release.py"
OUT="$NATIVE/dist/android-unsigned"
mkdir -p "$OUT"
cp app/build/outputs/apk/release/app-release-unsigned.apk "$OUT/psportal-android-unsigned.apk"
cp "$NATIVE/dist/psportal-native-corresponding-source.tar.gz" "$OUT/"
cp build/reports/apk-audit.json README.md VALIDATION.md FULL-CORE.md BACKGROUND.md PHONE-VPN.md "$OUT/"
cp "$NATIVE/LICENSE" "$NATIVE/THIRD_PARTY_NOTICES.md" "$OUT/"
tar -czf "$OUT/engine-dependency-licenses.tar.gz" -C "$NATIVE/dist" licenses
{ git -C "$NATIVE" rev-parse HEAD; java -version 2>&1; go version; cat "$ANDROID_NDK_HOME/source.properties"; } >"$OUT/build-toolchain.txt"
(cd "$OUT" && find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
echo "Unsigned artifacts ready in $OUT; signing and runtime validation remain separate."
