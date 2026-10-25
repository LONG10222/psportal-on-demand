"""Build a reproducible architecture-independent OpenWrt package with stdlib."""
import gzip
import hashlib
import io
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
VERSION = '0.5.1'


def archive(files, sort=True):
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', mtime=0, filename='') as gz:
        with tarfile.open(fileobj=gz, mode='w', format=tarfile.GNU_FORMAT) as tar:
            directories = sorted({str(p) for name in files for p in PurePosixPath(name).parents if str(p) != '.'}, key=lambda v: (v.count('/'), v))
            for directory in directories:
                entry = tarfile.TarInfo('./' + directory + '/')
                entry.type = tarfile.DIRTYPE
                entry.mode = 0o755
                tar.addfile(entry)
            for name, (data, mode) in (sorted(files.items()) if sort else files.items()):
                entry = tarfile.TarInfo('./' + name)
                entry.mode, entry.size = mode, len(data)
                tar.addfile(entry, io.BytesIO(data))
    return output.getvalue()


def main():
    files = {}
    for path in (ROOT / 'files').rglob('*'):
        if path.is_file():
            name = path.relative_to(ROOT / 'files').as_posix()
            mode = 0o755 if name.startswith(('etc/init.d/', 'usr/bin/', 'usr/libexec/rpcd/')) else 0o644
            files[name] = (path.read_bytes().replace(b'\r\n', b'\n'), mode)
    for package in ('xianniu_router', 'starpass_http'):
        for path in (ROOT / 'src' / package).glob('*.py'):
            files['usr/lib/xianniu-router/' + package + '/' + path.name] = (path.read_bytes().replace(b'\r\n', b'\n'), 0o644)
    size = sum(len(data) for data, _ in files.values()) // 1024
    control = (f'Package: xianniu-router\nVersion: {VERSION}\nArchitecture: all\n'
               f'Installed-Size: {size}\nSection: net\nPriority: optional\n'
               'Depends: python3-base, python3-light, python3-asyncio, python3-urllib, python3-openssl, python3-codecs, python3-logging, luci-base\n'
               'Maintainer: Local interoperability experiment\n'
               'Description: Experimental Xianniu IPv4 relay and HTTP proxy for N1/iStoreOS\n').encode()
    postinst = b'''#!/bin/sh
[ -n "$IPKG_INSTROOT" ] || {
 mkdir -p /etc/xianniu-router
 chmod 700 /etc/xianniu-router
 /usr/bin/python3 -c 'from pathlib import Path; root=Path("/usr/lib/xianniu-router").resolve(); [p.unlink() for name in ("xianniu_router","starpass_http") for p in (root/name/"__pycache__").glob("*.pyc") if p.is_file() and p.parent.resolve()==root/name/"__pycache__"]'
 [ ! -x /etc/init.d/rpcd ] || /etc/init.d/rpcd reload
 if [ -f /etc/config/portalproxy ]; then /etc/init.d/xianniu-router disable; else /etc/init.d/xianniu-router enable; fi
}
exit 0
'''
    prerm = b'#!/bin/sh\n[ -n "$IPKG_INSTROOT" ] || {\n /etc/init.d/xianniu-router stop\n /etc/init.d/xianniu-router disable\n}\nexit 0\n'
    members = [('debian-binary', b'2.0\n'), ('control.tar.gz', archive({
        'control': (control, 0o644), 'conffiles': (b'/etc/config/xianniu-router\n', 0o644),
        'postinst': (postinst, 0o755), 'prerm': (prerm, 0o755)})), ('data.tar.gz', archive(files))]
    # OpenWrt's ipkg-build uses an outer gzip tar, unlike Debian's ar.
    output = archive({name: (data, 0o644) for name, data in members}, sort=False)
    destination = ROOT / f'xianniu-router_{VERSION}_all.ipk'
    destination.write_bytes(output)
    digest = hashlib.sha256(output).hexdigest()
    (ROOT / 'SHA256SUMS').write_text(digest + '  ' + destination.name + '\n', encoding='ascii')
    print(destination.name, len(output), digest)


if __name__ == '__main__':
    main()
