#!/usr/bin/env sh
# SPDX-License-Identifier: GPL-3.0-only
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT="$ROOT/build/config-roundtrip"
mkdir -p "$OUT"
JAVA=${JAVA:-java}
JAVAC=${JAVAC:-javac}
GO=${GO:-go}
if command -v "$JAVAC" >/dev/null 2>&1; then
  "$JAVAC" --release 17 -d "$OUT" "$ROOT/app/src/main/java/org/psportal/host/HostConfig.java" "$ROOT/app/src/main/java/org/psportal/host/LanSetup.java" "$ROOT/tests/ExportConfig.java"
elif [ -n "${ECJ_JAR:-}" ] && [ -f "$ECJ_JAR" ]; then
  "$JAVA" -jar "$ECJ_JAR" -17 -warn:none -d "$OUT" "$ROOT/app/src/main/java/org/psportal/host/HostConfig.java" "$ROOT/app/src/main/java/org/psportal/host/LanSetup.java" "$ROOT/tests/ExportConfig.java"
else
  echo 'A JDK17+ compiler is required (or set ECJ_JAR).' >&2
  exit 1
fi
# The .go fixture lives outside module discovery so normal native `go test ./...`
# does not accidentally treat a build-tool test harness as an application package.
TMP=$(mktemp -d "${TMPDIR:-/tmp}/psportal-config-roundtrip.XXXXXX")
trap 'rm -f "$TMP/main.go"; rmdir "$TMP"' EXIT HUP INT TERM
cp "$ROOT/tests/ConfigRoundTrip.go.txt" "$TMP/main.go"
cd "$ROOT/.."
for mode in fixed auto fastest; do
  "$JAVA" -cp "$OUT" ExportConfig "$mode" > "$OUT/config-$mode.json"
  "$GO" run -tags=no_easytier,no_zerotier,no_tailscale "$TMP/main.go" "$OUT/config-$mode.json"
done
