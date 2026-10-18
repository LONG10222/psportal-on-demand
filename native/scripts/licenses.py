#!/usr/bin/env python3
"""Collect immutable module versions and bundled license/notice texts."""
import argparse,json,pathlib,shutil,subprocess,sys,time
ROOT=pathlib.Path(__file__).resolve().parents[1]

# Registry DNS/transport failures are retryable, but source/integrity failures are not.
TRANSIENT = ('i/o timeout', 'no such host', 'temporary failure in name resolution',
             'connection reset', 'connection refused', 'tls handshake timeout',
             'network is unreachable', '502 bad gateway', '503 service unavailable',
             '504 gateway timeout')
FATAL = ('checksum mismatch', 'security error', 'unknown revision', 'invalid version',
         'permission denied', '401 unauthorized', '403 forbidden', 'x509:')
def network_output(args, *, attempts=3, timeout=120):
 if attempts < 1 or attempts > 3:
  raise ValueError('Module metadata operations allow at most three attempts')
 for attempt in range(attempts):
  try:
   result=subprocess.run(args,cwd=ROOT,check=True,stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE,text=True,encoding='utf-8',
                         errors='replace',timeout=timeout)
   if result.stderr:print(result.stderr,end='',file=sys.stderr)
   return result.stdout
  except subprocess.CalledProcessError as error:
   message=(error.stderr or '').lower()
   if error.stderr:print(error.stderr,end='',file=sys.stderr)
   if attempt+1==attempts or any(x in message for x in FATAL) or not any(x in message for x in TRANSIENT):
    raise
  except subprocess.TimeoutExpired:
   if attempt+1==attempts:raise
  delay=2**(attempt+1)
  print(f'Transient module metadata failure; retry {attempt+2}/{attempts} in {delay}s',file=sys.stderr,flush=True)
  time.sleep(delay)
def main():
 p=argparse.ArgumentParser();p.add_argument('--go',default='go');p.add_argument('--output',required=True);a=p.parse_args()
 output=pathlib.Path(a.output);output.mkdir(parents=True,exist_ok=True)
 if output.is_relative_to(ROOT/'dist'):(ROOT/'dist'/'go.mod').write_text('module psportal.local/build-artifacts\n\ngo 1.26.0\n')
 raw=network_output([a.go,'list','-m','-json','all'])
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
   data=json.loads(network_output([a.go,'mod','download','-json',module['Path']+'@'+module['Version']]));directory=data.get('Dir')
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
