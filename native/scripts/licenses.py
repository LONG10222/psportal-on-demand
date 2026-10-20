#!/usr/bin/env python3
"""Collect immutable module versions and bundled license/notice texts."""
import argparse,hashlib,json,os,pathlib,shutil,subprocess,sys,time
import verify_mihomo_patch
ROOT=pathlib.Path(__file__).resolve().parents[1]

# Registry DNS/transport failures are retryable, but source/integrity failures are not.
TRANSIENT = ('i/o timeout', 'connect: operation timed out', 'no such host', 'temporary failure in name resolution',
             'connection reset', 'connection refused', 'tls handshake timeout',
             'network is unreachable', '502 bad gateway', '503 service unavailable',
             '504 gateway timeout')
FATAL = ('checksum mismatch', 'security error', 'unknown revision', 'invalid version',
         'permission denied', '401 unauthorized', '403 forbidden', 'x509:')
STDOUT_DIAGNOSTIC_LIMIT = 8192

def failed_stdout(raw):
 """Report bounded diagnostics; only structured Go errors justify a retry."""
 errors=[]
 try:
  for value in json_objects(raw):
   if not isinstance(value,dict):continue
   error=value.get('Error')
   # go mod download uses a string; go list uses an object with an Err field.
   if isinstance(error,dict):error=error.get('Err')
   if isinstance(error,str) and error:errors.append(error)
 except (ValueError,RecursionError):
  # Partial/malformed stdout is still useful, but is not trusted for retries.
  errors=[]
 diagnostic='\n'.join(errors) or raw
 if len(diagnostic)>STDOUT_DIAGNOSTIC_LIMIT:
  half=STDOUT_DIAGNOSTIC_LIMIT//2
  diagnostic=diagnostic[:half]+'\n... [stdout truncated] ...\n'+diagnostic[-half:]
 if diagnostic:print('Failed module metadata stdout:\n'+diagnostic,file=sys.stderr)
 return '\n'.join(errors)

def network_output(args, *, attempts=3, timeout=120, env=None):
 if attempts < 1 or attempts > 3:
  raise ValueError('Module metadata operations allow at most three attempts')
 for attempt in range(attempts):
  try:
   result=subprocess.run(args,cwd=ROOT,check=True,stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE,text=True,encoding='utf-8',
                         errors='replace',timeout=timeout,env=env)
   if result.stderr:print(result.stderr,end='',file=sys.stderr)
   return result.stdout
  except subprocess.CalledProcessError as error:
   if error.stderr:print(error.stderr,end='',file=sys.stderr)
   stdout=error.stdout or ''
   message=((error.stderr or '')+'\n'+failed_stdout(stdout)).lower()
   # Inspect full output before truncation; fatal failures always take priority.
   full_stdout=stdout.lower()
   fatal=any(x in message or x in full_stdout for x in FATAL)
   transient = (any(x in message for x in TRANSIENT) or
                ('stream error:' in message and 'internal_error; received from peer' in message))
   if attempt+1==attempts or fatal or not transient:
    raise
  except subprocess.TimeoutExpired:
   if attempt+1==attempts:raise
  delay=2**(attempt+1)
  print(f'Transient module metadata failure; retry {attempt+2}/{attempts} in {delay}s',file=sys.stderr,flush=True)
  time.sleep(delay)
TAGS = 'no_easytier,no_zerotier,no_tailscale'
ANDROID_TAGS = TAGS + ',with_gvisor'
# Match build.py and gomobile bind's supported device/simulator architectures.
RELEASE_TARGETS = tuple((system, arch, '0', './cmd/psportal')
 for system in ('linux', 'windows', 'darwin') for arch in ('amd64', 'arm64')) + tuple(
 (system, arch, '1', './androidmobile' if system == 'android' else './mobile')
 for system in ('android', 'ios') for arch in ('amd64', 'arm64'))

def json_objects(raw):
 decoder=json.JSONDecoder()
 while raw.strip():
  value,end=decoder.raw_decode(raw.lstrip());raw=raw.lstrip()[end:]
  yield value

def production_scope(go):
 """Union real non-test package dependencies across every shipped target.

 Never infer test-only status from a module name or a Linux-only dependency set.
 The broad module graph's notices are still retained where present, including
 build/gobind tool dependencies, because source and binding tooling are shipped.
 """
 required=set();targets=[]
 for system,arch,cgo,entry in RELEASE_TARGETS:
  env=dict(os.environ,GOOS=system,GOARCH=arch,CGO_ENABLED=cgo)
  tags = ANDROID_TAGS if system == 'android' else TAGS
  command=[go,'list','-deps','-json','-tags',tags,entry]
  packages=list(json_objects(network_output(command,env=env)))
  if not packages or not any(p.get('ImportPath')=='github.com/psportal/psportal/native/'+entry[2:] for p in packages):
   raise RuntimeError('Incomplete dependency graph for '+system+'/'+arch+' '+entry)
  modules=set()
  for package in packages:
   if package.get('Error') or package.get('DepsErrors') or package.get('Incomplete'):
    raise RuntimeError('Incomplete production dependency package: '+str(package.get('ImportPath')))
   module=package.get('Module')
   if module and not module.get('Main'):
    if not module.get('Path') or not module.get('Version'):
     raise RuntimeError('Unversioned production dependency: '+str(module))
    modules.add((module['Path'],module['Version']))
  if not modules:raise RuntimeError('No module dependencies for '+system+'/'+arch+' '+entry)
  required.update(modules)
  targets.append(dict(goos=system,goarch=arch,cgo_enabled=cgo,entry=entry,tags=tags,
                      modules=[dict(module=p,version=v) for p,v in sorted(modules)]))
 return required,targets

def missing_license_review(manifest,required,targets):
 present={(item['module'],item['version']) for item in manifest}
 if not required <= present:
  raise RuntimeError('Production dependency missing from module license graph: '+str(sorted(required-present)))
 missing=[item for item in manifest if not item['licenses']]
 unlicensed=[item['module'] for item in missing if (item['module'],item['version']) in required]
 if unlicensed:raise RuntimeError('Bundled production modules have no complete license text: '+', '.join(unlicensed))
 return dict(schema_version=1,build_tags=TAGS,targets=targets,
  scope='Union of non-test package dependencies for all supported desktop and mobile release targets; available graph/tool notices are also retained.',
  excluded_graph_only_missing_notices=[dict(module=item['module'],version=item['version'],
   reason='Not imported by any supported production target; no module-name exemptions') for item in missing])

def module_source(go,module):
 """Resolve the source actually built, without silently reverting a local patch."""
 replacement=module.get('Replace')
 source=replacement or module
 directory=source.get('Dir')
 if not directory:
  if replacement and not replacement.get('Version'):
   raise RuntimeError('Missing local replacement source for '+module['Path'])
  data=json.loads(network_output([go,'mod','download','-json',source['Path']+'@'+source['Version']]))
  directory=data.get('Dir')
 if not directory:raise RuntimeError('Missing downloaded source for '+module['Path'])
 base=pathlib.Path(directory)
 if not base.is_dir():raise RuntimeError('Missing source directory for '+module['Path'])
 info=None
 if replacement:
  info=dict(path=replacement['Path'],version=replacement.get('Version'))
  if not replacement.get('Version'):
   # This project's only local production replacement is the reviewed Mihomo
   # derivative. Unexpected local replacements must be reviewed explicitly.
   provenance=verify_mihomo_patch.verify(base)
   if (module['Path'],module['Version']) != (provenance['module'],provenance['version']):
    raise RuntimeError('Local replacement identity differs from its provenance')
   info.update(provenance=provenance,provenance_sha256=hashlib.sha256(
    (base/'PSPORTAL-PATCHES'/'PROVENANCE.json').read_bytes()).hexdigest())
 return base,info

def main():
 p=argparse.ArgumentParser();p.add_argument('--go',default='go');p.add_argument('--output',required=True);a=p.parse_args()
 output=pathlib.Path(a.output);output.mkdir(parents=True,exist_ok=True)
 if output.is_relative_to(ROOT/'dist'):(ROOT/'dist'/'go.mod').write_text('module psportal.local/build-artifacts\n\ngo 1.26.0\n')
 raw=network_output([a.go,'list','-m','-json','all'])
 modules=list(json_objects(raw))
 required,targets=production_scope(a.go)
 manifest=[];combined=['PSPortal native combined application: GPL-3.0-only\n\n'+(ROOT/'LICENSE').read_text()]
 goroot=pathlib.Path(subprocess.check_output([a.go,'env','GOROOT'],cwd=ROOT,text=True).strip())
 for name in ('LICENSE','PATENTS'):
  if (goroot/name).is_file():
   shutil.copyfile(goroot/name,output/('Go-'+name));combined.append('\n\n===== Go standard library / '+name+' =====\n'+(goroot/name).read_text())
 for module in modules:
  if module.get('Main'):continue
  base,replacement=module_source(a.go,module)
  label=module['Path'].replace('/','_')+'@'+module['Version'];target=output/label;target.mkdir(exist_ok=True)
  candidates=[f for f in base.rglob("*") if f.is_file() and f.suffix.lower() not in ('.go','.c','.h','.s','.py','.js','.ts') and f.name.lower().startswith(('license','licence','copying','notice','copyright'))]
  texts=[]
  for f in candidates:
   rel=f.relative_to(base);(target/rel).parent.mkdir(parents=True,exist_ok=True);(target/rel).unlink(missing_ok=True);shutil.copyfile(f,target/rel);texts.append(str(rel));combined.append('\n\n===== '+module['Path']+' '+module['Version']+' / '+str(rel)+' =====\n'+f.read_text(errors='replace'))
  item={'module':module['Path'],'version':module['Version'],'go_mod':module.get('GoModSum'),'licenses':texts}
  if replacement:
   item['replacement']=replacement
   if replacement.get('provenance'):
    item['go_mod']=replacement['provenance']['upstream_go_mod_sum']
    item['upstream_sum']=replacement['provenance']['upstream_module_sum']
    shutil.copytree(base/'PSPORTAL-PATCHES',target/'PSPORTAL-PATCHES',dirs_exist_ok=True)
  manifest.append(item)
 scope=missing_license_review(manifest,required,targets)
 (output/'DEPENDENCY-SCOPE.json').write_text(json.dumps(scope,indent=2)+'\n',encoding='utf-8')
 (output/'MODULES.json').write_text(json.dumps(manifest,indent=2)+'\n')
 (output/'ENGINE-NOTICES.txt').write_text('\n'.join(combined),encoding='utf-8')
 excluded=scope['excluded_graph_only_missing_notices']
 if excluded:print('Recorded graph-only modules with no notice; all shipped targets excluded them: '+', '.join(m['module'] for m in excluded))
if __name__=='__main__':main()
