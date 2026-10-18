#!/usr/bin/env python3
"""Retain Debian runtime copyright notices for an exact frozen Linux directory.

Only use with a build made from this machine's distro Python. Unknown ELF
components fail closed; this does not audit arbitrary standalone Python builds.
"""
import argparse, hashlib, json, pathlib, shutil
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
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('app',type=pathlib.Path);a=p.parse_args()
 root=a.app.resolve(); internal=root/'_internal'; records=[]; packages=set()
 for path in sorted(internal.rglob('*')):
  if not path.is_file():continue
  with path.open('rb') as stream: magic=stream.read(4)
  if magic != b'\x7fELF':continue
  relative=path.relative_to(internal).as_posix()
  package='libpython3.13' if relative.startswith('python3.13/lib-dynload/') else MAP.get(relative)
  if not package:raise SystemExit('Unmapped bundled ELF: '+relative)
  origin=(pathlib.Path('/usr/lib')/relative) if relative.startswith('python3.13/lib-dynload/') else pathlib.Path('/usr/lib/x86_64-linux-gnu')/path.name
  digest=hashlib.sha256(path.read_bytes()).hexdigest()
  if not origin.is_file() or hashlib.sha256(origin.read_bytes()).hexdigest()!=digest:
   raise SystemExit('Bundled ELF does not match installed distro origin: '+relative)
  notice=pathlib.Path('/usr/share/doc')/package/'copyright'
  if not notice.is_file():raise SystemExit('Missing complete copyright notice: '+str(notice))
  packages.add(package);records.append({'path':'_internal/'+relative,'sha256':digest,'installed_origin':str(origin),'notice':'licenses/debian/'+package+'.copyright'})
 if not records:raise SystemExit('No bundled runtime ELF found')
 out=root/'licenses'/'debian';out.mkdir(parents=True,exist_ok=True)
 for package in sorted(packages):shutil.copy2(pathlib.Path('/usr/share/doc')/package/'copyright',out/(package+'.copyright'))
 (out/'README.txt').write_text('Exact bundled distro-runtime ELF inventory: runtime-manifest.json.\nFull installed Debian copyright files are retained without editing.\nFreeType is used under the FreeType License (FTL), not its alternative GPL option.\nPortions of this software are copyright The FreeType Project (www.freetype.org). All rights reserved.\nZstandard is used under its BSD option. Full Apache-2.0 text referenced by the OpenSSL notice is included in ../PyInstaller-COPYING.txt.\nSystem libraries not included in the package remain system prerequisites.\nPython/PyInstaller/project and embedded-engine notices are retained separately.\n',encoding='utf-8')
 (out/'runtime-manifest.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
 print(f'Retained {len(packages)} component notices covering {len(records)} bundled ELF files')
if __name__=='__main__':main()
