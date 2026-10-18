#!/usr/bin/env python3
"""Collect immutable module versions and bundled license/notice texts."""
import argparse,json,pathlib,shutil,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--go',default='go');p.add_argument('--output',required=True);a=p.parse_args()
 output=pathlib.Path(a.output);output.mkdir(parents=True,exist_ok=True)
 if output.is_relative_to(ROOT/'dist'):(ROOT/'dist'/'go.mod').write_text('module psportal.local/build-artifacts\n\ngo 1.26.0\n')
 raw=subprocess.check_output([a.go,'list','-m','-json','all'],cwd=ROOT,text=True)
 decoder=json.JSONDecoder();modules=[]
 while raw.strip():
  module,end=decoder.raw_decode(raw.lstrip());raw=raw.lstrip()[end:];modules.append(module)
 manifest=[];combined=['PSPortal native combined application: GPL-3.0-only\n\n'+(ROOT/'LICENSE').read_text()]
 goroot=pathlib.Path(subprocess.check_output([a.go,'env','GOROOT'],cwd=ROOT,text=True).strip())
 for name in ('LICENSE','PATENTS'):
  if (goroot/name).is_file():
   shutil.copyfile(goroot/name,output/('Go-'+name));combined.append('\n\n===== Go standard library / '+name+' =====\n'+(goroot/name).read_text())
 for module in modules:
  if module.get('Main'):continue
  directory=module.get('Dir')
  if not directory:
   data=json.loads(subprocess.check_output([a.go,'mod','download','-json',module['Path']+'@'+module['Version']],cwd=ROOT,text=True));directory=data.get('Dir')
  if not directory:raise RuntimeError('Missing downloaded source for '+module['Path'])
  base=pathlib.Path(directory);label=module['Path'].replace('/','_')+'@'+module['Version'];target=output/label;target.mkdir(exist_ok=True)
  candidates=[f for f in base.rglob("*") if f.is_file() and f.suffix.lower() not in ('.go','.c','.h','.s','.py','.js','.ts') and f.name.lower().startswith(('license','licence','copying','notice','copyright'))]
  texts=[]
  for f in candidates:
   rel=f.relative_to(base);(target/rel).parent.mkdir(parents=True,exist_ok=True);(target/rel).unlink(missing_ok=True);shutil.copyfile(f,target/rel);texts.append(str(rel));combined.append('\n\n===== '+module['Path']+' '+module['Version']+' / '+str(rel)+' =====\n'+f.read_text(errors='replace'))
  manifest.append({'module':module['Path'],'version':module['Version'],'go_mod':module.get('GoModSum'),'licenses':texts})
 (output/'MODULES.json').write_text(json.dumps(manifest,indent=2)+'\n')
 (output/'ENGINE-NOTICES.txt').write_text('\n'.join(combined),encoding='utf-8')
 missing=[m['module'] for m in manifest if not m['licenses']]
 if missing: print('Review modules with no bundled license text: '+', '.join(missing))
if __name__=='__main__':main()
