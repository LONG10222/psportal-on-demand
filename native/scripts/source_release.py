#!/usr/bin/env python3
"""Make corresponding native source with exact dependency sources via go mod vendor."""
import argparse,pathlib,shutil,subprocess,tarfile,tempfile
import verify_mihomo_patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
IGNORE=shutil.ignore_patterns('build','.gradle','.git','.DS_Store','*.aar','*.apk','*.aab','*.xcframework','local.properties','*.keystore','*.jks','*.p12','*.pfx','*.key','*.pem','.env','.env.*','dist','__pycache__','.tools','*.xcodeproj')
def ignored(directory, names):
 ignored_names=set(IGNORE(directory,names))
 # Generated gomobile source JARs are reproducible; retain Gradle's wrapper JAR.
 if pathlib.Path(directory)==ROOT/'android'/'app'/'libs':
  ignored_names.update(name for name in names if name.endswith('.jar'))
 return ignored_names
SOURCE_DIRECTORIES = ('engine','mobile','androidcore','androidmobile','cmd','tools','scripts','android','ios','ci','third_party')

def main():
 p=argparse.ArgumentParser();p.add_argument('--go',default='go');a=p.parse_args()
 dist=ROOT/'dist';dist.mkdir(exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='psportal-source-') as tmp:
  root=pathlib.Path(tmp)/'psportal-native-source';root.mkdir()
  for name in SOURCE_DIRECTORIES:
   src=ROOT/name
   if src.exists():shutil.copytree(src,root/name,ignore=ignored)
  for name in ('.gitignore','go.mod','go.sum','LICENSE','THIRD_PARTY_NOTICES.md','README.md','config.example.json'):
   shutil.copy2(ROOT/name,root/name)
  verify_mihomo_patch.verify(root/'third_party'/'mihomo')
  dependency_inputs={name:(root/name).read_bytes() for name in ('go.mod','go.sum')}
  subprocess.run([a.go,'mod','vendor'],cwd=root,check=True)
  if any((root/name).read_bytes()!=contents for name,contents in dependency_inputs.items()):
   raise RuntimeError('Dependency closure changed while vendoring; update reviewed go.mod/go.sum before release')
  output=dist/'psportal-native-corresponding-source.tar.gz'
  with tarfile.open(output,'w:gz') as archive:archive.add(root,arcname=root.name)
  print(output)
if __name__=='__main__':main()
