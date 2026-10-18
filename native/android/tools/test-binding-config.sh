#!/usr/bin/env sh
# SPDX-License-Identifier: GPL-3.0-only
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT="$ROOT/build/config-roundtrip"
mkdir -p "$OUT"
JAVA=${JAVA:-java}
JAVAC=${JAVAC:-javac}
GO=${GO:-go}
"$JAVAC" --release 17 -d "$OUT" "$ROOT/app/src/main/java/org/psportal/host/HostConfig.java" "$ROOT/tests/ExportConfig.java"
"$JAVA" -cp "$OUT" ExportConfig > "$OUT/config.json"
# The .go fixture lives outside module discovery so normal native `go test ./...`
# does not accidentally treat a build-tool test harness as an application package.
TMP=$(mktemp -d "${TMPDIR:-/tmp}/psportal-config-roundtrip.XXXXXX")
trap 'rm -f "$TMP/main.go"; rmdir "$TMP"' EXIT HUP INT TERM
cp "$ROOT/tests/ConfigRoundTrip.go.txt" "$TMP/main.go"
cd "$ROOT/.."
"$GO" run -tags=no_easytier,no_zerotier,no_tailscale "$TMP/main.go" "$OUT/config.json"
