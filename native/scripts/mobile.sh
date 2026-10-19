#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
set -eu
cd "$(dirname "$0")/.."
MOBILE_VERSION=v0.0.0-20261011034528-197770444867
TAGS=no_easytier,no_zerotier,no_tailscale
ANDROID_TAGS=$TAGS,with_gvisor
GO=${GO:-go}
GOMOBILE=${GOMOBILE:-gomobile}
GOBIND=${GOBIND:-gobind}
export GOFLAGS="${GOFLAGS:-} -buildvcs=false"
mkdir -p dist
printf "module psportal.local/build-artifacts\n\ngo 1.26.0\n" > dist/go.mod
case "${1:-}" in
 tools)
  "$GO" install "golang.org/x/mobile/cmd/gomobile@$MOBILE_VERSION" "golang.org/x/mobile/cmd/gobind@$MOBILE_VERSION"
  ;;
 headers)
  mkdir -p dist/bindings/objc dist/bindings/java
  "$GOBIND" -lang=objc -tags="$TAGS" -outdir=dist/bindings/objc ./mobile
  "$GOBIND" -lang=java -javapkg=org.psportal.engine -tags="$ANDROID_TAGS" -outdir=dist/bindings/java ./androidmobile
  ;;
 android)
  : "${ANDROID_HOME:?Set ANDROID_HOME to an installed, licensed Android SDK}"
  : "${ANDROID_NDK_HOME:?Set ANDROID_NDK_HOME to installed, licensed Android NDK r28 or newer}"
  if ! grep -Eq 'Pkg.Revision = (2[89]|[3-9][0-9])\.' "$ANDROID_NDK_HOME/source.properties"; then
   echo 'Android builds require NDK r28+ for 16 KiB page alignment; no SDK/license changes were made' >&2;exit 1
  fi
  mkdir -p android/app/libs android/app/src/main/assets/licenses
  python3 scripts/licenses.py --go "$GO" --output dist/licenses
  cp dist/licenses/ENGINE-NOTICES.txt android/app/src/main/assets/licenses/ENGINE-NOTICES.txt
  "$GOMOBILE" bind -target=android/arm64,android/amd64 -androidapi=26 -javapkg=org.psportal.engine -tags="$ANDROID_TAGS" -trimpath -ldflags='-s -w -extldflags=-Wl,-z,max-page-size=16384' -o android/app/libs/psportal-engine.aar ./androidmobile
  echo 'AAR generated; build the Android host and verify APK alignment/device behavior separately'
  ;;
 ios)
  test "$(uname -s)" = Darwin || { echo 'XCFramework compilation requires macOS with licensed Xcode' >&2;exit 1; }
  command -v xcodebuild >/dev/null || { echo 'Install and select Xcode before building' >&2;exit 1; }
  mkdir -p ios/Frameworks ios/PSPortalHost/Resources/Licenses
  python3 scripts/licenses.py --go "$GO" --output dist/licenses
  cp dist/licenses/ENGINE-NOTICES.txt ios/PSPortalHost/Resources/Licenses/ENGINE-NOTICES.txt
  "$GOMOBILE" bind -target="${IOS_TARGET:-ios,iossimulator}" -iosversion=16.0 -tags="$TAGS" -trimpath -ldflags='-s -w' -o ios/Frameworks/PSPortalEngine.xcframework ./mobile
  echo 'XCFramework generated; Xcode host build/signing and physical-device tests remain separate'
  ;;
 *) echo 'Usage: scripts/mobile.sh tools|headers|android|ios' >&2;exit 2;;
esac
