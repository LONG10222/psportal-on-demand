#!/bin/sh
# Parse a generated fixture with the actual core; do not start a proxy service.
set -eu
BASE="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
CORE="${1:-}"
if [ -z "$CORE" ]; then
    for candidate in /usr/libexec/portalproxy/mihomo /etc/openclash/core/clash_meta /usr/bin/mihomo; do
        if [ -x "$candidate" ]; then CORE="$candidate";break;fi
    done
fi
[ -n "$CORE" ] && [ -x "$CORE" ] || { echo 'Usage: sh tests/core-config.sh /path/to/mihomo' >&2;exit 2; }
umask 077
TMP="$(mktemp -d /tmp/portalproxy-config-test.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
lua "$BASE/tests/core-config.lua" "$TMP"
"$CORE" -t -d "$TMP" -f "$TMP/config.yaml"
