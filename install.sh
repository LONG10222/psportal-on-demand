#!/bin/sh
set -eu
BASE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT=''
CORE=''
LINKED=0
MODE_SET=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --root) [ "$#" -ge 2 ] || exit 2; ROOT="$2"; shift 2 ;;
        --openclash) [ "$MODE_SET" = 0 ] || { echo 'Choose only one core mode.' >&2; exit 2; }; LINKED=1; MODE_SET=1; shift ;;
        --core) [ "$#" -ge 2 ] && [ "$MODE_SET" = 0 ] || exit 2; CORE="$2"; MODE_SET=1; shift 2 ;;
        *) echo 'Usage: sh install.sh [--openclash | --core /path/to/mihomo] [--root /staging/directory]' >&2; exit 2 ;;
    esac
done
ROOT="${ROOT%/}"
case "$ROOT" in ''|/*) ;; *) echo '--root must be absolute' >&2; exit 2 ;; esac
case "/$ROOT/" in */../*|*/./*) echo 'Use a normalized --root path' >&2; exit 2 ;; esac
if [ -z "$ROOT" ]; then
    [ "$(id -u)" = 0 ] || { echo 'Run as root.' >&2; exit 1; }
    if command -v opkg >/dev/null && opkg status luci-app-starpass 2>/dev/null | sed -n '/^Status:.* installed$/p' | read -r installed; then
        echo 'This installation is managed by opkg. Upgrade with the matching IPK; do not overwrite package-owned files with the source installer.' >&2; exit 1
    fi
    command -v uci >/dev/null && [ -f /etc/rc.common ] || { echo 'OpenWrt with UCI and procd is required.' >&2; exit 1; }
    lua -e 'require "nixio"; require "nixio.fs"; require "luci.jsonc"; require "luci.util"; require "luci.sys"; require "uci"' || {
        echo 'Missing Lua dependencies. Install lua luci-lib-nixio luci-lib-jsonc luci-lib-base libuci-lua curl ca-bundle using this firmware package manager.' >&2; exit 1;
    }
    if [ -d /usr/lib/lua/luci ]; then
        lua -e 'require "luci.cbi"' >/dev/null 2>&1 || { echo 'LuCI needs luci-compat. Install it with opkg install luci-compat or apk add luci-compat, matching this firmware.' >&2; exit 1; }
    fi
    if [ "$MODE_SET" = 0 ] && [ "$(uci -q get portalproxy.main.core_mode 2>/dev/null || true)" = openclash ]; then LINKED=1; fi
fi
if [ "$LINKED" = 0 ] && [ -z "$CORE" ]; then
    for candidate in "$ROOT/usr/libexec/portalproxy/mihomo" "$ROOT/etc/openclash/core/clash_meta" "$ROOT/usr/bin/mihomo"; do
        if [ -x "$candidate" ]; then CORE="$candidate"; break; fi
    done
fi
if [ -n "$CORE" ]; then
    [ -x "$CORE" ] || { echo 'Core is not executable.' >&2; exit 1; }
    if [ -z "$ROOT" ]; then
        "$CORE" -v >/dev/null 2>&1 || { echo 'Core cannot run on this firmware/CPU. Existing files were not changed.' >&2; exit 1; }
    fi
fi
umask 077
# Prepare every payload before touching installed files or stopping a service.
# A failed upgrade never starts a service automatically. Power loss still needs
# manual recovery using the complete, private backup below.
safe_target() {
    check=$1
    while [ "$check" != / ] && [ -n "$check" ]; do
        [ ! -L "$check" ] || { echo 'Symlink install target refused.' >&2; exit 1; }
        check=${check%/*}
    done
}
for path in "$ROOT" "$ROOT/etc/config/portalproxy" "$ROOT/etc/portalproxy/providers" \
    "$ROOT/etc/portalproxy-backups" "$ROOT/usr/libexec/portalproxy/mihomo"; do safe_target "$path"; done
mkdir -p "${ROOT:-/tmp}"
lock="${ROOT:-/tmp}/.starpass-install.lock"
mkdir "$lock" 2>/dev/null || { echo 'Another install may be active; inspect the local install lock before retrying.' >&2; exit 1; }
work="$(mktemp -d "${ROOT:-/tmp}/.starpass-install.XXXXXX")" || { rmdir "$lock"; exit 1; }
changed=0
committed=0
cleanup() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ "$changed" = 1 ] && [ "$committed" = 0 ]; then
        failed=0
        while IFS= read -r path; do
            if [ -f "$work/old/$path" ]; then
                cp -p "$work/old/$path" "$ROOT/$path" || failed=1
            else
                rm -f "$ROOT/$path" || failed=1
            fi
        done < "$work/manifest"
        if [ "$failed" = 0 ]; then
            echo 'Update failed; previous files restored. Services remain stopped; verify configuration before starting.' >&2
        else
            echo "Update failed and rollback was incomplete. Keep services stopped; restore the local backup. Recovery files: $work" >&2
            exit 1
        fi
    fi
    rm -rf "$work"
    rmdir "$lock"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
mkdir -p "$work/new" "$work/old"
: > "$work/manifest"
stage() {
    source=$1 destination=$2 mode=$3
    [ -f "$source" ] && [ ! -L "$source" ] || { echo 'Missing or unsafe install source.' >&2; exit 1; }
    # Reject symlink destinations/ancestors rather than write outside --root or
    # into unrelated files. Existing configuration contents are never rewritten.
    safe_target "$ROOT/$destination"
    [ ! -e "$ROOT/$destination" ] || [ -f "$ROOT/$destination" ] || { echo 'Non-file install target refused.' >&2; exit 1; }
    mkdir -p "$work/new/${destination%/*}" "$work/old/${destination%/*}"
    cp "$source" "$work/new/$destination"
    chmod "$mode" "$work/new/$destination"
    if [ -f "$ROOT/$destination" ]; then cp -p "$ROOT/$destination" "$work/old/$destination"; fi
    printf '%s\n' "$destination" >> "$work/manifest"
}
for file in "$BASE"/src/*.lua; do stage "$file" "usr/libexec/portalproxy/${file##*/}" 700; done
stage "$BASE/files/portalproxy.init" etc/init.d/portalproxy 700
stage "$BASE/files/portalproxy-core.init" etc/init.d/portalproxy-core 700
stage "$BASE/files/portalproxy-gateway.init" etc/init.d/portalproxy-gateway 700
stage "$BASE/files/portalproxy-starpass.init" etc/init.d/portalproxy-starpass 700
for file in "$BASE"/gateway/*.py "$BASE"/gateway/*.rb; do stage "$file" "usr/libexec/portalproxy/gateway/${file##*/}" 700; done
stage "$BASE/files/portalproxy" usr/sbin/portalproxy 700
if [ ! -f "$ROOT/etc/config/portalproxy" ]; then
    stage "$BASE/files/portalproxy.config" etc/config/portalproxy 600
    if [ "$LINKED" != 0 ]; then
        sed "s/option core_mode 'standalone'/option core_mode 'openclash'/" "$work/new/etc/config/portalproxy" > "$work/new/etc/config/portalproxy.new"
        mv "$work/new/etc/config/portalproxy.new" "$work/new/etc/config/portalproxy"
    fi
fi
if [ "$LINKED" = 0 ] && [ -n "$CORE" ] && [ "$CORE" != "$ROOT/usr/libexec/portalproxy/mihomo" ]; then
    stage "$CORE" usr/libexec/portalproxy/mihomo 700
fi
if [ -d "$ROOT/usr/lib/lua/luci" ]; then
    stage "$BASE/luci/controller/portalproxy.lua" usr/lib/lua/luci/controller/portalproxy.lua 644
    stage "$BASE/luci/model/cbi/portalproxy.lua" usr/lib/lua/luci/model/cbi/portalproxy.lua 644
    stage "$BASE/luci/view/portalproxy/onboarding.htm" usr/lib/lua/luci/view/portalproxy/onboarding.htm 644
    stage "$BASE/luci/view/portalproxy/dashboard.htm" usr/lib/lua/luci/view/portalproxy/dashboard.htm 644
    stage "$BASE/luci/static/accelerator.js" www/luci-static/resources/starpass/accelerator_v2.js 644
fi
# Preserve all installed project files, including old launchers and LuCI, not
# just UCI/core data. Archive remains local and may contain subscription secrets.
set --
for path in etc/config/portalproxy etc/portalproxy usr/libexec/portalproxy \
    etc/init.d/portalproxy etc/init.d/portalproxy-core etc/init.d/portalproxy-gateway etc/init.d/portalproxy-starpass usr/sbin/portalproxy \
    usr/lib/lua/luci/controller/portalproxy.lua usr/lib/lua/luci/model/cbi/portalproxy.lua \
    usr/lib/lua/luci/view/portalproxy www/luci-static/resources/starpass/accelerator_v2.js; do
    [ ! -e "$ROOT/$path" ] || set -- "$@" "$path"
done
if [ "$#" -gt 0 ]; then
    [ ! -L "$ROOT/etc/portalproxy-backups" ] || { echo 'Symlink backup directory refused.' >&2; exit 1; }
    mkdir -p "$ROOT/etc/portalproxy-backups"
    chmod 700 "$ROOT/etc/portalproxy-backups"
    archive="$ROOT/etc/portalproxy-backups/$(date -u +%Y%m%dT%H%M%SZ)-$$.tar.gz"
    tar -czf "$archive.part" -C "${ROOT:-/}" "$@"
    chmod 600 "$archive.part"
    mv "$archive.part" "$archive"
    echo 'Existing project files backed up locally; the archive may contain credentials.'
fi
if [ -z "$ROOT" ] && [ -x /etc/init.d/portalproxy ]; then /etc/init.d/portalproxy stop; fi
changed=1
while IFS= read -r path; do
    mkdir -p "$ROOT/${path%/*}"
    cp -p "$work/new/$path" "$ROOT/$path"
done < "$work/manifest"
mkdir -p "$ROOT/etc/portalproxy/providers"
chmod 700 "$ROOT/etc/portalproxy" "$ROOT/etc/portalproxy/providers" "$ROOT/usr/libexec/portalproxy"
chmod 600 "$ROOT/etc/config/portalproxy"

if [ -z "$ROOT" ]; then
    /etc/init.d/portalproxy-core disable
    rm -f /tmp/luci-indexcache /tmp/luci-indexcache.*.json
    echo 'Installed. Run: portalproxy setup (choose standalone or openclash explicitly)'
    [ "$LINKED" = 0 ] || echo 'No core copied. Existing configuration was preserved; choose openclash in setup.'
else
    echo 'Staging install complete. No services were started or enabled.'
fi
if [ "$LINKED" = 0 ] && [ -z "$CORE" ]; then
    echo 'Installed without a core. Existing OpenClash can be linked in LuCI; standalone needs a compatible Mihomo before Start.'
fi

committed=1
