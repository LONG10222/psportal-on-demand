#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Install one verified official build tool into this task, never /usr/local.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[[ "$(uname -s)" == Darwin ]] || { echo "XcodeGen CI installer requires macOS." >&2; exit 1; }
VERSION=2.46.0
SHA256=4d9e34b62172d645eed6457cac13fc222569974098ef4ee9c3368bedf0196806
mkdir -p "$ROOT/.tools/downloads"
ARCHIVE="$ROOT/.tools/downloads/xcodegen-$VERSION.zip"
curl --proto '=https' --tlsv1.2 --fail --location --retry 3 --max-time 120 \
  "https://github.com/yonaskolb/XcodeGen/releases/download/$VERSION/xcodegen.zip" -o "$ARCHIVE"
printf '%s  %s\n' "$SHA256" "$ARCHIVE" | shasum -a 256 -c -
ditto -x -k "$ARCHIVE" "$ROOT/.tools"
"$ROOT/.tools/xcodegen/bin/xcodegen" --version
if [[ -n "${GITHUB_PATH:-}" ]]; then
  printf '%s\n' "$ROOT/.tools/xcodegen/bin" >> "$GITHUB_PATH"
fi

