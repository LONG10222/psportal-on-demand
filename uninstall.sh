#!/bin/sh
set -eu
ROOT=''
PURGE=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --root) [ "$#" -ge 2 ] || exit 2; ROOT="$2"; shift 2 ;;
        --purge) PURGE=1; shift ;;
        *) echo 'Usage: sh uninstall.sh [--purge] [--root /staging/directory]' >&2; exit 2 ;;
    esac
done
ROOT="${ROOT%/}"
case "$ROOT" in ''|/*) ;; *) exit 2 ;; esac
case "/$ROOT/" in */../*|*/./*) exit 2 ;; esac
safe_target() {
    check=$1
    while [ "$check" != / ] && [ -n "$check" ]; do
        [ ! -L "$check" ] || { echo 'Symlink uninstall target refused.' >&2; exit 1; }
        check=${check%/*}
    done
}
for path in "$ROOT" "$ROOT/etc/init.d/portalproxy" "$ROOT/etc/init.d/portalproxy-core" \
    "$ROOT/etc/init.d/portalproxy-gateway" "$ROOT/etc/init.d/portalproxy-starpass" \
    "$ROOT/usr/sbin/portalproxy" "$ROOT/usr/libexec/portalproxy" \
    "$ROOT/usr/lib/lua/luci/controller/portalproxy.lua" "$ROOT/usr/lib/lua/luci/model/cbi/portalproxy.lua" \
    "$ROOT/usr/lib/lua/luci/view/portalproxy/onboarding.htm" "$ROOT/usr/lib/lua/luci/view/portalproxy/dashboard.htm" \
    "$ROOT/etc/config/portalproxy" "$ROOT/etc/portalproxy" \
    "$ROOT/www/luci-static/resources/starpass/accelerator_v2.js" "$ROOT/www/luci-static/resources/starpass/dashboard_v6.js"; do
    safe_target "$path"
done
mkdir -p "${ROOT:-/tmp}"
lock="${ROOT:-/tmp}/.starpass-install.lock"
mkdir "$lock" 2>/dev/null || { echo 'Another install or uninstall may be active.' >&2; exit 1; }
trap 'rmdir "$lock"' EXIT
trap 'exit 1' HUP INT TERM
if [ -z "$ROOT" ]; then
    [ "$(id -u)" = 0 ] || exit 1
    if command -v opkg >/dev/null && opkg status luci-app-starpass 2>/dev/null | sed -n '/^Status:.* installed$/p' | read -r installed; then
        echo 'Use opkg remove luci-app-starpass first; package removal preserves private configuration. Run this script with --purge afterward only to explicitly delete retained configuration.' >&2; exit 1
    fi
    if [ -x /etc/init.d/portalproxy-starpass ]; then /usr/bin/python3 /usr/libexec/portalproxy/gateway/control.py starpass-off; /etc/init.d/portalproxy-starpass disable; fi
    if [ -x /etc/init.d/portalproxy-gateway ]; then /etc/init.d/portalproxy-gateway stop; /etc/init.d/portalproxy-gateway disable; fi
    if [ -x /etc/init.d/portalproxy ]; then /etc/init.d/portalproxy stop; /etc/init.d/portalproxy disable; fi
    if [ -x /etc/init.d/portalproxy-core ]; then /etc/init.d/portalproxy-core stop; /etc/init.d/portalproxy-core disable; fi
fi
rm -f "$ROOT/etc/init.d/portalproxy" "$ROOT/etc/init.d/portalproxy-core" "$ROOT/usr/sbin/portalproxy"
rm -f "$ROOT/etc/init.d/portalproxy-gateway" "$ROOT/etc/init.d/portalproxy-starpass"
rm -rf "$ROOT/usr/libexec/portalproxy"
rm -f "$ROOT/usr/lib/lua/luci/controller/portalproxy.lua" "$ROOT/usr/lib/lua/luci/model/cbi/portalproxy.lua"
rm -f "$ROOT/usr/lib/lua/luci/view/portalproxy/onboarding.htm"
rm -f "$ROOT/usr/lib/lua/luci/view/portalproxy/dashboard.htm"
rm -f "$ROOT/www/luci-static/resources/starpass/accelerator_v2.js" "$ROOT/www/luci-static/resources/starpass/dashboard_v6.js"
if [ "$PURGE" = 1 ]; then
    rm -f "$ROOT/etc/config/portalproxy"
    rm -rf "$ROOT/etc/portalproxy"
    [ -n "$ROOT" ] || rm -rf /tmp/portalproxy
    echo 'Removed application files and its configuration. Separate backup archives were preserved.'
else
    echo 'Removed application files. Private configuration and backups were preserved.'
fi
