#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NATIVE="$(cd "$ROOT/.." && pwd)"
if [[ "$(uname -s)" != Darwin ]]; then
  echo "Apple XCFramework builds require macOS and Xcode. No iOS binary was built." >&2
  exit 1
fi
for tool in go xcrun xcodebuild python3; do
  command -v "$tool" >/dev/null || { echo "Missing prerequisite: $tool" >&2; exit 1; }
done
# Do not install Xcode, select a developer directory, accept licenses, create
# signing identities, or change the user's computer configuration.
# CI may request only the runner's simulator architecture to avoid three builds.
if [[ "${IOS_TARGET:-ios,iossimulator}" == *ios,* ]] || [[ "${IOS_TARGET:-ios,iossimulator}" == ios/* ]]; then
  xcrun --sdk iphoneos --show-sdk-path >/dev/null
fi
xcrun --sdk iphonesimulator --show-sdk-path >/dev/null
mkdir -p "$ROOT/.tools/bin" "$ROOT/Frameworks"
export GOBIN="$ROOT/.tools/bin"
export PATH="$GOBIN:$PATH"
cd "$NATIVE"
# Use the exact mobile version recorded by the shared module, not @latest.
MOBILE_VERSION="$(go list -m -f '{{.Version}}' golang.org/x/mobile)"
if [[ -z "$MOBILE_VERSION" ]]; then
  echo "golang.org/x/mobile must be pinned in native/go.mod first." >&2
  exit 1
fi
go install "golang.org/x/mobile/cmd/gomobile@$MOBILE_VERSION"
go install "golang.org/x/mobile/cmd/gobind@$MOBILE_VERSION"
gomobile init
# The shared recipe pins adapter build tags and copies full dependency notices.
# This compiles only executable code already included in the app at build time.
./scripts/mobile.sh ios
"$ROOT/scripts/verify-build-inputs.sh"
printf 'Built real embedded engine at %s\n' "$ROOT/Frameworks/PSPortalEngine.xcframework"

