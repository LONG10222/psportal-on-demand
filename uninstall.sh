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
if [ -z "$ROOT" ]; then
    [ "$(id -u)" = 0 ] || exit 1
    if [ -x /etc/init.d/portalproxy ]; then /etc/init.d/portalproxy stop; /etc/init.d/portalproxy disable; fi
    if [ -x /etc/init.d/portalproxy-core ]; then /etc/init.d/portalproxy-core stop; /etc/init.d/portalproxy-core disable; fi
fi
rm -f "$ROOT/etc/init.d/portalproxy" "$ROOT/etc/init.d/portalproxy-core" "$ROOT/usr/sbin/portalproxy"
rm -rf "$ROOT/usr/libexec/portalproxy"
if [ "$PURGE" = 1 ]; then
    rm -f "$ROOT/etc/config/portalproxy"
    rm -rf "$ROOT/etc/portalproxy"
    [ -n "$ROOT" ] || rm -rf /tmp/portalproxy
    echo 'Removed application files and its configuration. Separate backup archives were preserved.'
else
    echo 'Removed application files. Private configuration and backups were preserved.'
fi
