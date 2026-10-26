#!/usr/bin/python3
"""Install paired official router IPKs after bounded, verified staging."""
import fcntl,hashlib,io,json,os,re,shutil,subprocess,sys,tarfile,tempfile,time
from pathlib import Path,PurePosixPath
from net import request
REPO='LONG10222/psportal-on-demand'
API='https://api.github.com/repos/'+REPO+'/releases?per_page=100'
HOSTS={'api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'}
ROOT=Path('/tmp/portalproxy/update')
STATE=ROOT/'state.json'
PACKAGES=('xianniu-router','luci-app-starpass')

def version(v):
    m=re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:\+git[a-f0-9]+)?(?:-\d+)?',v or '')
    return tuple(int(x) for x in m.groups()) if m else None

def installed(package):
    p=subprocess.run(['opkg','status',package],capture_output=True,text=True,timeout=5)
    match=re.search(r'^Version: (\S+)$',p.stdout,re.M)
    return match[1] if match and re.search(r'^Status:.* installed$',p.stdout,re.M) else ''
def read():
    try:return json.loads(STATE.read_text())
    except (OSError,ValueError):return {}
def write(**values):
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    state={**read(),**values,'updated_at':int(time.time())}
    temp=STATE.with_suffix('.tmp');temp.write_text(json.dumps(state));os.chmod(temp,0o600);temp.replace(STATE)
    return state

def status():
    data=read();allowed=('phase','message','available','target','checked_at','updated_at','backup')
    result={k:data[k] for k in allowed if k in data};result['current']=installed('luci-app-starpass')
    if data.get('phase') in ('checking','downloading','installing') and time.time()-data.get('updated_at',0)>900:
        result.update(phase='error',message='更新任务超时，请检查本地服务与备份')
    return result

def choose(releases,current):
    choices=[]
    for release in releases:
        if release.get('draft') or release.get('prerelease'):continue
        tag=release.get('tag_name','')
        m=re.fullmatch(r'starpass-router-v(\d+\.\d+\.\d+)',tag)
        if not m or not version(m[1]) or not version(current) or version(m[1])<=version(current):continue
        assets=release.get('assets',[]);packages={}
        for package in PACKAGES:
            candidates=[a for a in assets if re.fullmatch(re.escape(package)+r'_(\d+\.\d+\.\d+)_all\.ipk',a.get('name',''))]
            if len(candidates)!=1:break
            a=candidates[0];prefix='https://github.com/'+REPO+'/releases/download/'+tag+'/'
            if a.get('state')!='uploaded' or not isinstance(a.get('size'),int) or not 1<=a['size']<=8*1024*1024:break
            if not re.fullmatch(r'sha256:[a-f0-9]{64}',a.get('digest','')) or a.get('browser_download_url')!=prefix+a['name']:break
            v=a['name'][len(package)+1:-8]
            if not version(v) or (package=='luci-app-starpass' and v!=m[1]):break
            packages[package]={'name':a['name'],'version':v,'url':a['browser_download_url'],'size':a['size'],'sha256':a['digest'][7:]}
        if len(packages)==2:choices.append({'target':m[1],'packages':packages})
    return max(choices,key=lambda r:version(r['target'])) if choices else None

def check():
    write(phase='checking',message='正在检查正式路由器版本',available=False,packages={},backup='')
    _,body=request(API,limit=4*1024*1024,allowed=HOSTS)
    releases=json.loads(body)
    if not isinstance(releases,list):raise ValueError('Invalid release response')
    candidate=choose(releases,installed('luci-app-starpass'))
    return write(phase='ready' if candidate else 'current',message='发现新版本，可一键安装' if candidate else '没有适用的新正式版本',
                 available=bool(candidate),target=candidate['target'] if candidate else '',packages=candidate['packages'] if candidate else {},checked_at=int(time.time()))

def contents(blob,limit):
    result={};total=0
    with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as archive:
        for index,m in enumerate(archive):
            name=m.name.removeprefix('./');parts=PurePosixPath(name)
            if index>2048 or name.startswith('/') or '..' in parts.parts or m.issym() or m.islnk() or not(m.isdir() or m.isfile()):raise ValueError('Unsafe package archive')
            if m.isdir():continue
            total+=m.size
            if total>limit or name in result:raise ValueError('Invalid package size')
            result[name]=archive.extractfile(m).read()
    return result

def validate_package(blob,package,expected):
    outer=contents(blob,16*1024*1024)
    if set(outer)!={'debian-binary','control.tar.gz','data.tar.gz'} or outer['debian-binary']!=b'2.0\n':raise ValueError('Invalid IPK')
    control=contents(outer['control.tar.gz'],512*1024).get('control',b'').decode('utf-8')
    fields=dict(line.split(': ',1) for line in control.splitlines() if ': ' in line)
    if fields.get('Package')!=package or fields.get('Version')!=expected or fields.get('Architecture')!='all':raise ValueError('Wrong package metadata')
    files=contents(outer['data.tar.gz'],32*1024*1024)
    # A verified official package still cannot overwrite unrelated network files.
    prefixes=('usr/libexec/portalproxy/','usr/lib/xianniu-router/','usr/lib/lua/luci/','www/luci-static/resources/','usr/share/','usr/libexec/rpcd/')
    fixed={'etc/config/portalproxy','etc/config/xianniu-router','usr/sbin/portalproxy','usr/bin/xianniu-router','etc/uci-defaults/90-xianniu-router'}
    for name in files:
        if name not in fixed and not name.startswith(prefixes) and not (name.startswith('etc/init.d/') and name.split('/')[-1] in ('portalproxy','portalproxy-core','portalproxy-gateway','portalproxy-starpass','xianniu-router')):
            raise ValueError('Unexpected package path')
    return files

def backup():
    root=Path('/etc/portalproxy-backups')/('update-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+str(os.getpid()))
    root.mkdir(parents=True,mode=0o700)
    paths=['etc/config/portalproxy','etc/portalproxy','etc/config/xianniu-router','etc/xianniu-router']
    for package in PACKAGES:
        listing=Path('/usr/lib/opkg/info/'+package+'.list')
        if listing.exists():paths.extend(p.lstrip('/') for p in listing.read_text().splitlines() if Path(p).is_file())
    paths=sorted(set(p for p in paths if Path('/'+p).exists()))
    subprocess.run(['tar','-czf',str(root/'private-before.tar.gz'),'-C','/']+paths,check=True,capture_output=True,timeout=60)
    os.chmod(root/'private-before.tar.gz',0o600)
    return str(root)

def install():
    old=read()
    if not old.get('available') or time.time()-old.get('checked_at',0)>3600:raise ValueError('Check for updates first')
    # Re-fetch metadata: never accept URLs, versions, or shell arguments from LuCI.
    candidate=check()
    if not candidate.get('available'):return candidate
    for package in PACKAGES:
        target=candidate['packages'][package]['version'];current=installed(package)
        if version(current) and version(target)<version(current):raise ValueError('Dependency downgrade refused')
    stage=Path(tempfile.mkdtemp(prefix='packages-',dir=ROOT));paths=[]
    try:
        write(phase='downloading',message='正在下载并校验安装包')
        for package in PACKAGES:
            asset=candidate['packages'][package]
            _,data=request(asset['url'],limit=8*1024*1024,redirects=4,allowed=HOSTS)
            if len(data)!=asset['size'] or hashlib.sha256(data).hexdigest()!=asset['sha256']:raise ValueError('Package integrity failed')
            validate_package(data,package,asset['version'])
            path=stage/asset['name'];path.write_bytes(data);os.chmod(path,0o600);paths.append(str(path))
        if shutil.disk_usage('/overlay').free<16*1024*1024:raise ValueError('Not enough persistent storage')
        # Dependency failures are caught before touching running services.
        subprocess.run(['opkg','--noaction','install']+paths,check=True,capture_output=True,timeout=60)
        from control import pause_accelerator
        pause_accelerator()  # Paid clock must be confirmed paused before replacement.
        location=backup()
        write(phase='installing',message='备份完成，正在安装；代理连接可能短暂中断',backup=location)
        subprocess.run(['opkg','install']+paths,check=True,capture_output=True,timeout=180)
        for package in PACKAGES:
            if installed(package)!=candidate['packages'][package]['version']:raise ValueError('Installed version did not match')
        write(phase='done',message='更新已安装，配置已保留；请刷新页面',available=False)
    finally:shutil.rmtree(stage,ignore_errors=True)

def worker(command):
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(ROOT/'task.lock','a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        try:
            if command=='check':check()
            elif command=='install':install()
            else:raise ValueError('Invalid action')
        except Exception:
            write(phase='error',message='更新未完成，请重试检查；若已开始安装，请保留备份并检查软件包状态',available=False)

def start(command):
    if command not in ('check','install'):raise ValueError('Invalid action')
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Detached process survives LuCI request completion and package self-replacement.
    subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'worker',command],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    return {'ok':True}

if __name__=='__main__':
    os.umask(0o077)
    if len(sys.argv)==3 and sys.argv[1]=='worker':worker(sys.argv[2])
    elif len(sys.argv)==2 and sys.argv[1] in ('check','install'):print(json.dumps(start(sys.argv[1])))
    else:print(json.dumps(status()))
