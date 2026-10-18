#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRAMEWORK="$ROOT/Frameworks/PSPortalEngine.xcframework"
[[ -f "$FRAMEWORK/Info.plist" ]] || {
  echo "Missing real PSPortalEngine.xcframework. Run scripts/build-engine.sh on a Mac with Xcode. There is no placeholder transport." >&2
  exit 1
}
found=0
while IFS= read -r -d '' header; do
  grep -q 'MobileStart' "$header" && grep -q 'MobileStop' "$header" && grep -q 'MobileStatus' "$header" || {
    echo "The generated mobile binding does not match the required Start/Stop/Status contract." >&2; exit 1;
  }
  binary="$(dirname "$(dirname "$header")")/PSPortalEngine"
  [[ -s "$binary" ]] || { echo "The XCFramework is missing its actual static library." >&2; exit 1; }
  found=$((found + 1))
done < <(find "$FRAMEWORK" -name Mobile.objc.h -print0)
[[ "$found" -ge 1 ]] || { echo "The XCFramework has no real mobile binding slice." >&2; exit 1; }
python3 - "$FRAMEWORK/Info.plist" <<'PY'
import pathlib, plistlib, sys
info = pathlib.Path(sys.argv[1])
with info.open('rb') as source:
    libraries = plistlib.load(source).get('AvailableLibraries', [])
if not any(lib.get('SupportedPlatform') == 'ios' and lib.get('SupportedPlatformVariant') == 'simulator' for lib in libraries):
    raise SystemExit('A real iOS Simulator slice is required; no placeholder library is accepted.')
for lib in libraries:
    directory = info.parent / lib['LibraryIdentifier'] / lib['LibraryPath']
    if not directory.is_dir() or not (directory / 'PSPortalEngine').is_file():
        raise SystemExit('XCFramework metadata references a missing engine framework.')
PY
for notice in GPL-3.0 THIRD-PARTY-NOTICES PROJECT-MIT; do
  [[ -s "$ROOT/PSPortalHost/Resources/$notice.txt" ]] || { echo "Missing required license notice: $notice" >&2; exit 1; }
done
[[ -s "$ROOT/PSPortalHost/Resources/Licenses/ENGINE-NOTICES.txt" ]] || {
  echo "Missing complete dependency notices. Rebuild with native/scripts/mobile.sh ios." >&2; exit 1;
}

