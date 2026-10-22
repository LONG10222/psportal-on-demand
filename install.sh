#!/bin/sh
set -eu
BASE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT=''
CORE=''
LINKED=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --root) [ "$#" -ge 2 ] || exit 2; ROOT="$2"; shift 2 ;;
        --openclash) LINKED=1; shift ;;
        --core) [ "$#" -ge 2 ] || exit 2; CORE="$2"; shift 2 ;;
        *) echo 'Usage: sh install.sh [--openclash | --core /path/to/mihomo] [--root /staging/directory]' >&2; exit 2 ;;
    esac
done
ROOT="${ROOT%/}"
case "$ROOT" in ''|/*) ;; *) echo '--root must be absolute' >&2; exit 2 ;; esac
case "/$ROOT/" in */../*|*/./*) echo 'Use a normalized --root path' >&2; exit 2 ;; esac
if [ -z "$ROOT" ]; then
    [ "$(id -u)" = 0 ] || { echo 'Run as root.' >&2; exit 1; }
    command -v uci >/dev/null && [ -f /etc/rc.common ] || { echo 'OpenWrt with UCI and procd is required.' >&2; exit 1; }
    lua -e 'require "nixio"; require "nixio.fs"; require "luci.jsonc"; require "luci.util"; require "luci.sys"; require "uci"' || {
        echo 'Missing Lua dependencies. See the README dependency section.' >&2; exit 1;
    }
fi
if [ "$LINKED" = 0 ] && [ -z "$CORE" ]; then
    for candidate in "$ROOT/usr/libexec/portalproxy/mihomo" /etc/openclash/core/clash_meta /usr/bin/mihomo; do
        if [ -x "$candidate" ]; then CORE="$candidate"; break; fi
    done
fi
[ "$LINKED" = 1 ] || { [ -n "$CORE" ] && [ -x "$CORE" ]; } || { echo 'Provide a compatible Mihomo executable with --core.' >&2; exit 1; }
umask 077
if [ -f "$ROOT/etc/config/portalproxy" ]; then
    mkdir -p "$ROOT/etc/portalproxy-backups"
    chmod 700 "$ROOT/etc/portalproxy-backups"
    set -- etc/config/portalproxy
    [ ! -d "$ROOT/etc/portalproxy" ] || set -- "$@" etc/portalproxy
    [ ! -d "$ROOT/usr/libexec/portalproxy" ] || set -- "$@" usr/libexec/portalproxy
    archive="$ROOT/etc/portalproxy-backups/$(date -u +%Y%m%dT%H%M%SZ)-$$.tar.gz"
    tar -czf "$archive" -C "${ROOT:-/}" "$@"
    chmod 600 "$archive"
    echo 'Existing project files backed up locally; the archive may contain credentials.'
fi
if [ -z "$ROOT" ] && [ -x /etc/init.d/portalproxy ]; then /etc/init.d/portalproxy stop; fi
mkdir -p "$ROOT/etc/config" "$ROOT/etc/init.d" "$ROOT/etc/portalproxy/providers" "$ROOT/usr/libexec/portalproxy" "$ROOT/usr/sbin"
chmod 700 "$ROOT/etc/portalproxy" "$ROOT/etc/portalproxy/providers" "$ROOT/usr/libexec/portalproxy"
for file in "$BASE"/src/*.lua; do cp "$file" "$ROOT/usr/libexec/portalproxy/"; done
cp "$BASE/files/portalproxy.init" "$ROOT/etc/init.d/portalproxy"
cp "$BASE/files/portalproxy-core.init" "$ROOT/etc/init.d/portalproxy-core"
cp "$BASE/files/portalproxy" "$ROOT/usr/sbin/portalproxy"
if [ ! -f "$ROOT/etc/config/portalproxy" ]; then
    cp "$BASE/files/portalproxy.config" "$ROOT/etc/config/portalproxy"
    [ "$LINKED" = 0 ] || sed -i "s/option core_mode 'standalone'/option core_mode 'openclash'/" "$ROOT/etc/config/portalproxy"
fi
if [ "$LINKED" = 0 ] && [ "$CORE" != "$ROOT/usr/libexec/portalproxy/mihomo" ]; then cp "$CORE" "$ROOT/usr/libexec/portalproxy/mihomo"; fi
chmod 700 "$ROOT/usr/libexec/portalproxy/"* "$ROOT/etc/init.d/portalproxy" "$ROOT/etc/init.d/portalproxy-core" "$ROOT/usr/sbin/portalproxy"
chmod 600 "$ROOT/etc/config/portalproxy"
# Optional legacy LuCI interface; CLI works without luci-compat.
if [ -d "$ROOT/usr/lib/lua/luci" ]; then
    mkdir -p "$ROOT/usr/lib/lua/luci/controller" "$ROOT/usr/lib/lua/luci/model/cbi"
    cp "$BASE/luci/controller/portalproxy.lua" "$ROOT/usr/lib/lua/luci/controller/portalproxy.lua"
    cp "$BASE/luci/model/cbi/portalproxy.lua" "$ROOT/usr/lib/lua/luci/model/cbi/portalproxy.lua"
    mkdir -p "$ROOT/usr/lib/lua/luci/view/portalproxy"
    cp "$BASE/luci/view/portalproxy/onboarding.htm" "$ROOT/usr/lib/lua/luci/view/portalproxy/onboarding.htm"
    chmod 644 "$ROOT/usr/lib/lua/luci/view/portalproxy/onboarding.htm"
    chmod 644 "$ROOT/usr/lib/lua/luci/controller/portalproxy.lua" "$ROOT/usr/lib/lua/luci/model/cbi/portalproxy.lua"
fi

if [ -z "$ROOT" ]; then
    /etc/init.d/portalproxy-core disable
    echo 'Installed. Run: portalproxy setup (choose standalone or openclash explicitly)'
    [ "$LINKED" = 0 ] || echo 'No core copied. Existing configuration was preserved; choose openclash in setup.'
else
    echo 'Staging install complete. No services were started or enabled.'
fi
