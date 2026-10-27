#!/usr/bin/python3
"""Serialize feature toggles, preserve a permanent entry and own only our core."""
import fcntl,json,os,subprocess,sys,time,socket,shutil,ipaddress
from pathlib import Path
sys.path[:0]=['/usr/lib/xianniu-router',str(Path(__file__).parent)]
from entry import option,service_running


def run(args,seconds=45,input=None):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=seconds,input=input)
def set_options(**values):
    for k,v in values.items():run(['uci','set','portalproxy.main.'+k+'='+str(v)])
    run(['uci','commit','portalproxy']);os.chmod('/etc/config/portalproxy',0o600)
def ensure_entry():
    bind=option('portalproxy','main.listen_ip')
    if not bind:
        bind=option('network','lan.ipaddr').split('/')[0]
        if not ipaddress.ip_address(bind).is_private:raise ValueError('LAN address required')
        set_options(listen_ip=bind)
    if not option('portalproxy','main.local_dns'):
        dns=option('network','lan.gateway') or option('network','lan.dns').split(' ')[0] or bind
        if not isinstance(ipaddress.ip_address(dns),ipaddress.IPv4Address):raise ValueError('LAN DNS required')
        set_options(local_dns=dns)
    shared=int(option('portalproxy','main.listen_port','10081'))
    accelerator=int(option('xianniu-router','main.http_port','10082'))
    internal=int(option('portalproxy','main.entry_backend_port','18880'))
    if len({shared,accelerator,internal})!=3:raise ValueError('Entry ports must be distinct')
    if option('portalproxy','main.gateway_enabled')!='1':
        migrate_entry()
    run(['/etc/init.d/portalproxy-gateway','enable']);run(['/etc/init.d/portalproxy-starpass','enable'])
    if not service_running('portalproxy-gateway'):run(['/etc/init.d/portalproxy-gateway','start'])
    for port in (shared,accelerator):
        for _ in range(40):
            try:
                connection=socket.create_connection((bind,port),.2);connection.close();break
            except OSError:time.sleep(.1)
        else:raise RuntimeError('Permanent entry is not ready')

def migrate_entry():
    from xianniu_router.manager import Manager
    directory=Path('/etc/portalproxy-backups')/('entry-'+str(time.time_ns()))
    directory.mkdir(parents=True,mode=0o700)
    saved=directory/'portalproxy.config';shutil.copy2('/etc/config/portalproxy',saved);os.chmod(saved,0o600)
    was_game=option('portalproxy','main.enabled')=='1'
    manager=Manager()
    if manager.runtime().get('running'):manager.finish()
    run(['/etc/init.d/portalproxy','stop'])
    try:
        set_options(gateway_enabled=1,entry_backend_port=18880,starpass_enabled=0)
        ensure_entry()
        if was_game:
            run(['/usr/bin/lua','/usr/libexec/portalproxy/render.lua'])
            run(['/etc/init.d/portalproxy','start'])
    except BaseException:
        subprocess.run(['/etc/init.d/portalproxy-gateway','stop'],capture_output=True)
        shutil.copy2(saved,'/etc/config/portalproxy')
        if was_game:run(['/etc/init.d/portalproxy','start'])
        raise

def pause_accelerator():
    from xianniu_router.manager import Manager
    m=Manager();result=m.finish()
    if result.get('billing')=='paid' and m.config().get('account',{}).get('access_token'):
        if m.member().get('pause_state') not in (0,'0'):m.member_pause()
    return result

OWNER=Path('/etc/portalproxy/openclash-owner.json')
def mark_manual_owner():
    if not OWNER.exists():
        boot=subprocess.run(['/etc/init.d/openclash','enabled'],capture_output=True).returncode==0
        temp=OWNER.with_suffix('.tmp');temp.write_text(json.dumps({'boot_enabled':boot}));os.chmod(temp,0o600);temp.replace(OWNER)
    run(['/etc/init.d/openclash','disable'])
    run(['uci','set','openclash.config.enable=1']);run(['uci','commit','openclash'])
def release_manual_owner():
    if not OWNER.exists():return
    value=json.loads(OWNER.read_text())
    run(['uci','set','openclash.config.enable=0']);run(['uci','commit','openclash'])
    run(['/etc/init.d/openclash','enable' if value.get('boot_enabled') else 'disable'])
    OWNER.unlink()

def stop_openclash():
    obj=json.loads(run(['ubus','call','service','list','{"name":"openclash"}']).stdout or '{}')
    instances=obj.get('openclash',{}).get('instances',{})
    if 'starpass_manual' in instances:
        run(['ubus','call','service','delete','{"name":"openclash","instance":"starpass_manual"}'])
    elif any(x.get('running') for x in instances.values()):
        # The user explicitly asked to link the existing OpenClash switch.
        run(['uci','set','openclash.config.enable=0']);run(['uci','commit','openclash'])
        run(['/etc/init.d/openclash','stop'],90)
    for _ in range(80):
        if not service_running('openclash'):release_manual_owner();return
        time.sleep(.1)
    raise RuntimeError('OpenClash did not stop')

def start_openclash():
    if service_running('openclash'):
        obj=json.loads(run(['ubus','call','service','list','{"name":"openclash"}']).stdout or '{}')
        if 'starpass_manual' in obj.get('openclash',{}).get('instances',{}):mark_manual_owner()
        return
    source=option('openclash','config.config_path')
    if not source.startswith('/etc/openclash/config/') or not Path(source).is_file():raise ValueError('Choose an OpenClash configuration first')
    path='/etc/portalproxy/openclash-manual.yaml'
    secret=option('openclash','config.dashboard_password')
    run(['/usr/bin/ruby',str(Path(__file__).with_name('openclash_prepare.rb')),source,path,
        option('openclash','config.http_port','7890'),option('openclash','config.cn_port','9090'),
        option('portalproxy','main.local_dns'),option('portalproxy','main.listen_ip')],input=secret)
    run(['/etc/openclash/clash','-t','-d','/etc/openclash','-f',path],30)
    mark_manual_owner()
    instance={'command':['/etc/openclash/clash','-d','/etc/openclash','-f',path],
        'user':'root','group':'nogroup','env':{'SAFE_PATHS':'/etc/portalproxy:/etc/openclash:/usr/share/openclash:/etc/ssl'},
        'respawn':[3600,3,3],'term_timeout':3,'stderr':True}
    # The real OpenClash service name lets its existing LuCI detect the core.
    # Do not run its transparent-routing/DNS startup script.
    run(['ubus','call','service','set',json.dumps({'name':'openclash','script':'/etc/init.d/openclash','instances':{'starpass_manual':instance}})])
    port=int(option('openclash','config.http_port','7890'))
    for _ in range(80):
        try:
            s=socket.create_connection(('127.0.0.1',port),.2);s.close();return
        except OSError:time.sleep(.25)
    raise RuntimeError('OpenClash proxy did not become ready')

def action(name):
    if name=='sync':
        running=service_running('openclash')
        flag=option('portalproxy','main.starpass_enabled',None)
        if running is None or flag is None:return
        active=flag=='1'
        configured=option('openclash','config.enable')=='1'
        if active and configured and not running and OWNER.exists():
            start_openclash();return
        if running and configured and not active:
            set_options(enabled=0)
            run(['/etc/init.d/portalproxy','stop']);set_options(starpass_enabled=1)
        elif active and (not running or not configured):set_options(starpass_enabled=0)
        if not running and not configured:release_manual_owner()
        return
    ensure_entry()
    if name=='entry-enable':return
    if name=='pause-accelerator':return pause_accelerator()
    if name=='game-off':
        set_options(enabled=0)
        run(['/etc/init.d/portalproxy','stop']);return
    if name=='starpass-off':
        set_options(starpass_enabled=0)
        stop_openclash();return
    if name=='game-on':
        if option('portalproxy','main.core_mode','standalone')!='standalone':raise ValueError('Use StarPass mode for OpenClash')
        run(['/usr/bin/lua','/usr/libexec/portalproxy/render.lua','--check'])
        was_starpass=option('portalproxy','main.starpass_enabled')=='1'
        try:
            set_options(starpass_enabled=0);stop_openclash()
            run(['/usr/bin/lua','/usr/libexec/portalproxy/render.lua'])
            set_options(enabled=1)
            run(['/etc/init.d/portalproxy','enable']);run(['/etc/init.d/portalproxy','start'])
        except BaseException:
            set_options(enabled=0)
            if was_starpass:start_openclash();set_options(starpass_enabled=1)
            raise
        return
    if name=='starpass-on':
        was_game=option('portalproxy','main.enabled')=='1'
        set_options(enabled=0)
        run(['/etc/init.d/portalproxy','stop'])
        try:
            start_openclash();set_options(starpass_enabled=1)
        except BaseException:
            try:stop_openclash()
            finally:
                set_options(starpass_enabled=0,enabled=int(was_game))
                if was_game:run(['/etc/init.d/portalproxy','start'])
            raise
        return
    raise ValueError('Unsupported action')

if __name__=='__main__':
    os.umask(0o077)
    choices=('game-on','game-off','starpass-on','starpass-off','pause-accelerator','sync','entry-enable')
    if len(sys.argv)!=2 or sys.argv[1] not in choices:raise SystemExit(2)
    with open('/tmp/portalproxy-features.lock','a') as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:action(sys.argv[1])
        except Exception:
            # Never print provider paths, node credentials or API payloads.
            print('Feature operation failed; previous game state restored where possible.',file=sys.stderr);raise SystemExit(1)
