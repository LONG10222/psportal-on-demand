#!/usr/bin/env python3
"""Retain exact Debian and pinned upstream PyYAML runtime notices.

Only use with the selected distro Python. Unknown ELF components fail closed;
the PyPI extension is verified independently, never attributed to Debian.
"""
import argparse
import json
from pathlib import Path
import shutil

try:
    from .pyyaml_runtime import digest, installed_evidence, verify_build_modules, verify_retained_notices
except ImportError:
    from pyyaml_runtime import digest, installed_evidence, verify_build_modules, verify_retained_notices

MAP = {
 'libX11.so.6':'libx11-6','libXau.so.6':'libxau6','libXdmcp.so.6':'libxdmcp6',
 'libXext.so.6':'libxext6','libXft.so.2':'libxft2','libXrender.so.1':'libxrender1','libXss.so.1':'libxss1',
 'libbrotlicommon.so.1':'libbrotli1','libbrotlidec.so.1':'libbrotli1',
 'libbz2.so.1.0':'libbz2-1.0','libcrypto.so.3':'libssl3t64','libssl.so.3':'libssl3t64',
 'libexpat.so.1':'libexpat1','libffi.so.8':'libffi8','libfontconfig.so.1':'libfontconfig1',
 'libfreetype.so.6':'libfreetype6','liblzma.so.5':'liblzma5','libpng16.so.16':'libpng16-16t64',
 'libpython3.13.so.1.0':'libpython3.13','libtcl8.6.so':'libtcl8.6','libtk8.6.so':'libtk8.6',
 'libz.so.1':'zlib1g','libzstd.so.1':'libzstd1',
}


def identify_elf(relative, path, yaml_evidence, *, usr=Path('/usr')):
    sha = digest(path)
    extension = yaml_evidence['extension']
    if relative == extension['path']:
        origin = Path(extension['source'])
        if not yaml_evidence.get('reviewed') or sha != extension['sha256'] or digest(origin) != sha:
            raise ValueError('Bundled PyYAML ELF differs from the exact reviewed installed wheel')
        return dict(path='_internal/' + relative, sha256=sha, installed_origin=str(origin),
                    owner='PyYAML 6.0.3 / LibYAML 0.2.5',
                    notices=['licenses/pyyaml-6.0.3/PyYAML-LICENSE.txt', 'licenses/pyyaml-6.0.3/LibYAML-LICENSE.txt'],
                    source_manifest='licenses/pyyaml-6.0.3/manifest.json'), None
    package = 'libpython3.13' if relative.startswith('python3.13/lib-dynload/') else MAP.get(relative)
    if not package:
        raise ValueError('Unmapped bundled ELF: ' + relative)
    origin = usr / 'lib' / relative if relative.startswith('python3.13/lib-dynload/') else usr / 'lib/x86_64-linux-gnu' / path.name
    if not origin.is_file() or digest(origin) != sha:
        raise ValueError('Bundled ELF does not match installed distro origin: ' + relative)
    notice = usr / 'share/doc' / package / 'copyright'
    if not notice.is_file():
        raise ValueError('Missing complete copyright notice: ' + str(notice))
    return dict(path='_internal/' + relative, sha256=sha, installed_origin=str(origin),
                owner='Debian:' + package, notice='licenses/debian/' + package + '.copyright'), package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    args = parser.parse_args()
    root = args.app.resolve()
    internal = root / '_internal'
    evidence = installed_evidence(strict=True)
    verify_build_modules(root.parents[1] / 'build/portalproxy', evidence)
    verify_retained_notices(root / 'licenses/pyyaml-6.0.3', evidence)
    records, packages = [], set()
    for path in sorted(internal.rglob('*')):
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            if stream.read(4) != b'\x7fELF':
                continue
        record, package = identify_elf(path.relative_to(internal).as_posix(), path, evidence)
        records.append(record)
        if package:
            packages.add(package)
    if not records or sum(item['owner'] == 'PyYAML 6.0.3 / LibYAML 0.2.5' for item in records) != 1:
        raise ValueError('Expected distro runtime and exactly one reviewed PyYAML extension')
    out = root / 'licenses/debian'
    out.mkdir(parents=True, exist_ok=True)
    for package in sorted(packages):
        shutil.copy2(Path('/usr/share/doc') / package / 'copyright', out / (package + '.copyright'))
    (out / 'README.txt').write_text(
        'Exact bundled runtime ELF inventory: runtime-manifest.json.\n'
        'Full installed Debian copyright files are retained without editing.\n'
        'PyYAML is a separate reviewed upstream PyPI wheel, not a Debian package.\n'
        'Its exact extension, two licenses and complete upstream sources are under ../pyyaml-6.0.3/.\n'
        'FreeType is used under the FreeType License (FTL), not its alternative GPL option.\n'
        'Portions of this software are copyright The FreeType Project (www.freetype.org). All rights reserved.\n'
        'Zstandard is used under its BSD option. Full Apache-2.0 text referenced by the OpenSSL notice is included in ../PyInstaller-COPYING.txt.\n'
        'System libraries not included in the package remain system prerequisites.\n'
        'Python/PyInstaller/project and embedded-engine notices are retained separately.\n', encoding='utf-8')
    (out / 'runtime-manifest.json').write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')
    print(f'Retained {len(packages)} Debian notices plus PyYAML/LibYAML notices covering {len(records)} bundled ELF files')


if __name__ == '__main__':
    main()
