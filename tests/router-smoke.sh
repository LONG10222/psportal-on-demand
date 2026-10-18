#!/bin/sh
# OpenWrt integration test. All endpoints are loopback-only; no subscription or Internet is used.
set -eu
[ "$(id -u)" = 0 ] && [ -f /etc/rc.common ] || { echo 'Run this test as root on OpenWrt.' >&2; exit 1; }
BASE="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
TMP="$(mktemp -d /tmp/portalproxy-smoke.XXXXXX)"
TAG="$$"
IDLE_SECONDS="${IDLE_SECONDS:-5}"
case "$IDLE_SECONDS" in ''|*[!0-9]*) exit 2 ;; esac
cleanup() {
    for name in listener core lan; do
        service="$TMP/portalproxy-smoke-$name-$TAG"
        [ ! -x "$service" ] || "$service" stop >/dev/null 2>&1 || true
    done
    rm -rf "$TMP"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
lua "$BASE/tests/make-smoke.lua" "$TMP" "$BASE" "$TAG" "$IDLE_SECONDS"
"$TMP/portalproxy-smoke-lan-$TAG" start
"$TMP/portalproxy-smoke-listener-$TAG" start
state() { jsonfilter -i "$TMP/run/status.json" -e "@.$1"; }
i=0
while [ ! -s "$TMP/run/status.json" ]; do i=$((i+1));[ "$i" -lt 40 ];sleep 1;done
[ "$(state core_running)" = false ]
# Loopback services must not be reachable through either HTTP or CONNECT.
code="$(curl -sS --max-time 4 --noproxy '' -x http://127.0.0.1:21081 -o /dev/null -w '%{http_code}' http://127.0.0.1:21084/)"
[ "$code" = 403 ]
curl -sS --max-time 4 --noproxy '' --proxytunnel -x http://127.0.0.1:21081 http://127.0.0.1:21084/ >/dev/null 2>&1 && { echo 'Unexpected loopback CONNECT accepted' >&2;exit 1; }
[ "$(state core_running)" = false ]
curl -sS --max-time 4 --interface 127.0.0.2 --noproxy '' -x http://127.0.0.1:21081 http://1.1.1.1/ >/dev/null 2>&1 && { echo 'Unexpected client accepted' >&2;exit 1; }
sleep 1
[ "$(state core_running)" = false ]
code="$(curl -sS --max-time 15 --noproxy '' -x http://127.0.0.1:21081 -o /dev/null -w '%{http_code}' http://1.1.1.1/)"
[ "$code" = 204 ] && [ "$(state core_running)" = true ]
i=0
while [ "$i" -lt $((IDLE_SECONDS+7)) ]; do
    code="$(curl -sS --max-time 4 --noproxy '' -x http://127.0.0.1:21081 -o /dev/null -w '%{http_code}' http://127.0.0.1:21084/)"
    [ "$code" = 403 ]
    [ "$(state core_running)" != false ] || break
    i=$((i+1));sleep 1
done
[ "$(state core_running)" = false ]
[ "$(state counters.external_requests)" = 1 ]
[ "$(state counters.denied_clients)" = 1 ]
code="$(curl -sS --max-time 15 --noproxy '' -x http://127.0.0.1:21081 -o /dev/null -w '%{http_code}' http://1.1.1.1/)"
[ "$code" = 204 ] && [ "$(state core_running)" = true ]
[ "$(state counters.starts)" = 2 ]
echo 'PASS: loopback HTTP/CONNECT denial, client rejection, external wake, idle shutdown, second wake. LAN concurrency is covered by tests/lifecycle.lua.'
