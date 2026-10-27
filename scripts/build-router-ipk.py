#!/usr/bin/env python3
"""Build an architecture-independent opkg package, without a core or credentials.

For opkg firmware only. OpenWrt apk firmware must use the source installer until
an SDK-built, signed apk is available; renaming this file is never sufficient.
"""
import argparse
import gzip
import hashlib
import io
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def tar_gz(entries):
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode='w', format=tarfile.GNU_FORMAT) as archive:
            directories = set()
            for name in entries:
                parent = Path(name).parent
                while parent.as_posix() != '.':
                    directories.add(parent.as_posix()); parent = parent.parent
            for name in sorted(directories):
                info = tarfile.TarInfo('./' + name + '/')
                info.type = tarfile.DIRTYPE
                info.mode = 0o700 if name == 'usr/libexec/portalproxy' else 0o755
                info.mtime = 0
                archive.addfile(info)
            for name, (data, mode) in sorted(entries.items()):
                info = tarfile.TarInfo('./' + name)
                info.size, info.mode, info.mtime = len(data), mode, 0
                archive.addfile(info, io.BytesIO(data))
    return output.getvalue()


def build(destination, version):
    if not re.fullmatch(r'[0-9][A-Za-z0-9.+~_-]{0,95}', version):
        raise ValueError('Invalid package version')
    entries = {}

    def add(source, target, mode):
        path = ROOT / source
        if path.is_symlink() or not path.is_file():
            raise ValueError('Unsafe package source')
        entries[target] = (path.read_bytes().replace(b'\r\n', b'\n'), mode)

    for path in sorted((ROOT / 'src').glob('*.lua')):
        add(path.relative_to(ROOT), 'usr/libexec/portalproxy/' + path.name, 0o700)
    for source, target in [('portalproxy', 'usr/sbin/portalproxy'),
                           ('portalproxy.init', 'etc/init.d/portalproxy'),
                           ('portalproxy-core.init', 'etc/init.d/portalproxy-core'),
                           ('portalproxy-gateway.init','etc/init.d/portalproxy-gateway'),
                           ('portalproxy-starpass.init','etc/init.d/portalproxy-starpass')]:
        add('files/' + source, target, 0o700)
    for path in sorted((ROOT/'gateway').glob('*')):
        if path.suffix in ('.py','.rb'):add(path.relative_to(ROOT),'usr/libexec/portalproxy/gateway/'+path.name,0o700)
    add('files/portalproxy.config', 'etc/config/portalproxy', 0o600)
    for source in ('controller/portalproxy.lua', 'model/cbi/portalproxy.lua',
                   'view/portalproxy/onboarding.htm', 'view/portalproxy/dashboard.htm'):
        add('luci/' + source, 'usr/lib/lua/luci/' + source, 0o644)
    add('luci/static/accelerator.js', 'www/luci-static/resources/starpass/accelerator_v2.js', 0o644)
    add('luci/static/dashboard.js', 'www/luci-static/resources/starpass/dashboard_v5.js', 0o644)
    add('LICENSE', 'usr/share/licenses/starpass/LICENSE', 0o644)
    payload = tar_gz(entries)
    installed_size = len(gzip.decompress(payload))
    control = f'''Package: luci-app-starpass
Version: {version}
Architecture: all
Maintainer: StarPass contributors
Section: luci
Priority: optional
License: MIT
Depends: lua, luci-compat, luci-lib-nixio, luci-lib-jsonc, luci-lib-base, libuci-lua, curl, ca-bundle, xianniu-router (>= 0.5.1)
Installed-Size: {installed_size}
Description: StarPass on-demand HTTP/TCP device sharing with optional OpenClash linking
'''
    scripts = {
        'preinst': '''#!/bin/sh
[ -n "$IPKG_INSTROOT" ] && exit 0
set -eu
set --
for path in etc/config/portalproxy etc/portalproxy usr/libexec/portalproxy etc/init.d/portalproxy etc/init.d/portalproxy-core etc/init.d/portalproxy-gateway etc/init.d/portalproxy-starpass usr/sbin/portalproxy usr/lib/lua/luci/controller/portalproxy.lua usr/lib/lua/luci/model/cbi/portalproxy.lua usr/lib/lua/luci/view/portalproxy www/luci-static/resources/starpass/accelerator_v2.js www/luci-static/resources/starpass/dashboard_v5.js; do
 [ ! -e "/$path" ] || set -- "$@" "$path"
done
if [ "$#" -gt 0 ]; then
 [ ! -L /etc/portalproxy-backups ] || exit 1
 umask 077
 mkdir -p /etc/portalproxy-backups
 chmod 700 /etc/portalproxy-backups
 archive="/etc/portalproxy-backups/opkg-$(date -u +%Y%m%dT%H%M%SZ)-$$.tar.gz"
 tar -czf "$archive.part" -C / "$@"
 chmod 600 "$archive.part"
 mv "$archive.part" "$archive"
fi
exit 0
''',
        'postinst': '''#!/bin/sh
[ -n "$IPKG_INSTROOT" ] && exit 0
set -eu
chmod 600 /etc/config/portalproxy
mkdir -p /etc/portalproxy/providers
chmod 700 /etc/portalproxy /etc/portalproxy/providers /usr/libexec/portalproxy
rm -f /tmp/luci-indexcache /tmp/luci-indexcache.*.json /tmp/luci-indexcache.*.lua /tmp/luci-modulecache/6C7563692E636F6E74726F6C6C65722E706F7274616C70726F7879
if [ "$(uci -q get portalproxy.main.gateway_enabled)" = 1 ] && [ -n "$(uci -q get portalproxy.main.listen_ip)" ]; then
 /etc/init.d/portalproxy-gateway start >/dev/null 2>&1 || true
 /usr/sbin/portalproxy start >/dev/null 2>&1 || true
fi
echo 'StarPass installed; configured entries are restored. Paid acceleration is not resumed.' 
exit 0
''',
        'prerm': '''#!/bin/sh
[ -n "$IPKG_INSTROOT" ] && exit 0
# opkg upgrade also invokes prerm: stop only StarPass before replacing its code.
if [ -x /etc/init.d/portalproxy-gateway ]; then /etc/init.d/portalproxy-gateway stop || exit 1; fi
if [ -x /etc/init.d/portalproxy ]; then /etc/init.d/portalproxy stop || exit 1; fi
if [ "$PKG_UPGRADE" != 1 ]; then
 [ ! -L /etc/portalproxy ] || exit 1
 umask 077
 mkdir -p /etc/portalproxy
 chmod 700 /etc/portalproxy
 if [ -f /etc/config/portalproxy ]; then
  cp -p /etc/config/portalproxy /etc/portalproxy/config.preserved
  chmod 600 /etc/portalproxy/config.preserved
 fi
 /etc/init.d/portalproxy disable 2>/dev/null || true
 /etc/init.d/portalproxy-core disable 2>/dev/null || true
fi
exit 0
''',
        'postrm': '''#!/bin/sh
[ -n "$IPKG_INSTROOT" ] && exit 0
rm -f /tmp/luci-indexcache /tmp/luci-indexcache.*.json /tmp/luci-indexcache.*.lua /tmp/luci-modulecache/6C7563692E636F6E74726F6C6C65722E706F7274616C70726F7879
if [ "$PKG_UPGRADE" != 1 ]; then
 if [ ! -e /etc/config/portalproxy ] && [ -f /etc/portalproxy/config.preserved ]; then
  cp -p /etc/portalproxy/config.preserved /etc/config/portalproxy
 fi
 echo 'StarPass removed. Private UCI configuration/provider data was preserved; disable the device HTTP proxy.'
fi
exit 0
'''}
    controls = {'control': (control.encode(), 0o644), 'conffiles': (b'/etc/config/portalproxy\n', 0o644)}
    controls.update({name: (data.encode(), 0o755) for name, data in scripts.items()})
    # Match OpenWrt scripts/ipkg-build: this opkg fork expects a gzip tar
    # container, rather than assuming Debian's ar container is supported.
    result = tar_gz({'debian-binary': (b'2.0\n', 0o644),
                     'control.tar.gz': (tar_gz(controls), 0o644),
                     'data.tar.gz': (payload, 0o644)})
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(result)
    print(f'{hashlib.sha256(result).hexdigest()}  {destination.name}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    build(args.output, args.version)
