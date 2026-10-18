#!/usr/bin/env python3
"""Build native binaries and release archives; no install/sign/publish."""
import argparse, hashlib, json, os, pathlib, platform, shutil, subprocess, sys, tarfile, zipfile
ROOT = pathlib.Path(__file__).resolve().parents[1]
TAGS = 'no_easytier,no_zerotier,no_tailscale'
TARGETS = ('linux/amd64','linux/arm64','windows/amd64','windows/arm64','darwin/amd64','darwin/arm64')
def copy_file(src,dst):
    pathlib.Path(dst).unlink(missing_ok=True)
    return shutil.copyfile(src,dst)
def run(args, **kwargs):
    subprocess.run(args, cwd=ROOT, check=True, **kwargs)
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=TARGETS, action='append')
    parser.add_argument('--all',action='store_true')
    parser.add_argument('--go',default=os.environ.get('GO','go'))
    parser.add_argument('--skip-licenses',action='store_true',help='reuse already generated dist/licenses notices')
    args=parser.parse_args()
    host_os={'Linux':'linux','Windows':'windows','Darwin':'darwin'}.get(platform.system(),'linux')
    host_arch={'x86_64':'amd64','AMD64':'amd64','ARM64':'arm64','aarch64':'arm64','arm64':'arm64'}.get(platform.machine(),'amd64')
    targets=TARGETS if args.all else args.target or [f'{host_os}/{host_arch}']
    dist=ROOT/'dist'; dist.mkdir(exist_ok=True)
    (dist/'go.mod').write_text('module psportal.local/build-artifacts\n\ngo 1.26.0\n')
    if not args.skip_licenses:
        run([sys.executable,'scripts/licenses.py','--go',args.go,'--output',str(dist/'licenses')])
    for target in targets:
        system,arch=target.split('/');label='psportal-'+system+'-'+arch
        staging=dist/label;staging.mkdir(exist_ok=True)
        binary=staging/('psportal.exe' if system=='windows' else 'psportal')
        env=dict(os.environ,GOOS=system,GOARCH=arch,CGO_ENABLED='0')
        run([args.go,'build','-buildvcs=false','-trimpath','-tags',TAGS,'-ldflags=-s -w -buildid=','-o',str(binary),'./cmd/psportal'],env=env)
        for name in ('LICENSE','THIRD_PARTY_NOTICES.md','README.md','config.example.json','go.mod','go.sum'):
            copy_file(ROOT/name,staging/name)
        if not (dist/'licenses'/'ENGINE-NOTICES.txt').is_file():
            raise RuntimeError('Complete license collection is required before packaging')
        shutil.copytree(dist/'licenses',staging/'licenses',dirs_exist_ok=True,copy_function=copy_file)
        (staging/'SOURCE.md').write_text('Corresponding source and build instructions must accompany redistribution.\nGenerate the complete source+vendor archive with scripts/source_release.py.\nThis executable embeds Mihomo v1.19.32 and is GPL-3.0-only.\n',encoding='utf-8')
        if system=='windows':
            output=dist/(label+'.zip')
            with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(staging.rglob('*')):
                    if path.is_file(): archive.write(path,path.relative_to(dist))
        else:
            output=dist/(label+'.tar.gz')
            with tarfile.open(output,'w:gz') as archive: archive.add(staging,arcname=label)
        print(output,flush=True)
    artifacts=sorted(p for p in dist.iterdir() if p.is_file() and (p.name.endswith('.zip') or p.name.endswith('.tar.gz')))
    (dist/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in artifacts),encoding='ascii')
if __name__=='__main__':main()
