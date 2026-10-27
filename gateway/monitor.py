#!/usr/bin/python3
"""Sanitized dashboard snapshots and explicit subscription-account refresh."""
import hashlib,ipaddress,json,os,re,subprocess,sys,time
from pathlib import Path
from entry import option
from net import request
CACHE=Path('/etc/portalproxy/subscription-usage.json')
NATIVE_CONFIG=Path('/etc/xianniu-router/session.json')
NATIVE_STATUS=Path('/var/run/xianniu-router.json')
NATIVE_PREFERENCES=Path('/etc/xianniu-router/preferences.json')
NATIVE_CATALOG=Path('/usr/share/xianniu-router/catalog.json')
PROC=Path('/proc')

def read_json(path,limit=262144):
    try:
        if path.stat().st_size>limit:return {}
        result=json.loads(path.read_text());return result if isinstance(result,dict) else {}
    except (OSError,ValueError):return {}
def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data));os.chmod(temp,0o600);temp.replace(path)
def sections(config,kind):
    p=subprocess.run(['ubus','-t','2','call','uci','get',json.dumps({'config':config,'type':kind})],capture_output=True,text=True,timeout=4)
    return list(json.loads(p.stdout).get('values',{}).values()) if p.returncode==0 else []
def sources():
    rows=[]
    selected=option('portalproxy','main.openclash_source')
    active=Path(option('openclash','config.config_path')).stem
    for s in sections('openclash','config_subscribe')[:64]:
        address=s.get('address','')
        if s.get('enabled')=='0' or not isinstance(address,str) or not address.startswith('https://'):continue
        name=str(s.get('name','OpenClash'))[:80]
        name=''.join(c for c in name if c.isprintable())
        # URLs and credentials are never part of dashboard rows or cache keys.
        rows.append({'id':hashlib.sha256(address.encode()).hexdigest(),'title':name,
            'game':option('portalproxy','main.source_mode')=='openclash' and (s.get('.name')==selected or not selected and not rows),
            'starpass':not active or name==active,'url':address,'agent':s.get('sub_ua') or 'clash.meta'})
    if option('portalproxy','main.source_mode','manual')=='manual':
        address=option('portalproxy','main.subscription_url')
        if address:
            rows.append({'id':hashlib.sha256(address.encode()).hexdigest(),'title':'独立订阅','game':True,'starpass':False,
                'url':address,'agent':option('portalproxy','main.subscription_user_agent','clash.meta')})
    return rows

def userinfo(value):
    result={}
    if not isinstance(value,str) or len(value)>2048:return result
    for part in value.split(';'):
        pair=part.strip().split('=',1)
        if len(pair)!=2:continue
        key,value=(v.strip().lower() for v in pair)
        if key in ('upload','download','total','expire') and re.fullmatch(r'\d{1,16}',value) and int(value)<=9007199254740991:
            result[key]=int(value)
    return result

def refresh():
    import fcntl
    with open('/tmp/portalproxy-subscription.lock','a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'ok':False,'error':'刷新正在进行'}
        cache=read_json(CACHE);now=int(time.time())
        for row in sources():
            old=cache.get(row['id'],{})
            if now-old.get('attempted_at',0)<30:continue
            try:
                headers,_=request(row['url'],headers={'User-Agent':row['agent']},head=True)
                info=userinfo(headers.get('subscription-userinfo'))
                cache[row['id']]={'info':info,'updated_at':now,'attempted_at':now,'state':'ok' if info else 'unavailable'}
            except Exception:
                cache[row['id']]={**old,'attempted_at':now,'state':'error'}
        current={r['id'] for r in sources()};cache={k:v for k,v in cache.items() if k in current}
        save(CACHE,cache)
        return {'ok':True}

def clean_title(value):
    return ''.join(c for c in str(value) if c.isprintable())[:120] if isinstance(value,str) else ''

def accelerator_snapshot():
    """Read local service evidence only; never probe a node or refresh an account."""
    config=read_json(NATIVE_CONFIG)
    path=NATIVE_STATUS;runtime=read_json(path)
    try:
        proc=subprocess.run(['ubus','-t','2','call','service','list','{"name":"xianniu-router"}'],capture_output=True,text=True,timeout=3)
        if proc.returncode:raise ValueError('Service unavailable')
        instances=json.loads(proc.stdout).get('xianniu-router',{}).get('instances',{})
        process=next((v for v in instances.values() if v.get('running')),None)
        known=True
    except (OSError,ValueError,subprocess.TimeoutExpired,AttributeError):process=None;known=False
    running=bool(process)
    try:sample_at=path.stat().st_mtime;recent=-5<=time.time()-sample_at<=15
    except OSError:sample_at=0;recent=False
    fresh=known and (not running or recent and runtime.get('running') is True)
    selected=runtime if running and fresh else config
    profile=selected.get('profile',{});profile=profile if isinstance(profile,dict) else {}
    game_id=selected.get('game_id');area_id=profile.get('area_id')
    game_title=area_title=''
    try:
        catalog=NATIVE_CATALOG
        if catalog.stat().st_size>16*1024*1024:raise ValueError('Catalog too large')
        games=json.loads(catalog.read_text())
        if not isinstance(games,list) or len(games)>8192:raise ValueError('Invalid catalog')
        game=next((g for g in games if isinstance(g,dict) and g.get('id')==game_id),{})
        game_title=clean_title(game.get('title',''))
        areas=game.get('areas',[])
        if isinstance(areas,list):area_title=next((clean_title(a.get('title','')) for a in areas[:256] if isinstance(a,dict) and a.get('id')==area_id),'')
    except (OSError,ValueError):pass
    address=config.get('active_device','')
    try:address=str(ipaddress.IPv4Address(address))
    except (ValueError,TypeError):address=''
    preferences=read_json(NATIVE_PREFERENCES)
    notes=preferences.get('devices',{});mac=config.get('active_device_mac','');mac=mac.lower() if isinstance(mac,str) else ''
    note=notes.get(mac,{}) if isinstance(notes,dict) else {}
    device_name=clean_title(note.get('note','')) if isinstance(note,dict) else ''
    counters=runtime.get('counters',{}) if running and fresh else {}
    if not isinstance(counters,dict):counters={}
    safe={k:v for k in ('sent','received','tcp_connections','tcp_errors') if type(v:=counters.get(k)) is int and 0<=v<=9007199254740991}
    pid=process.get('pid') if process else None
    session=''
    if type(pid) is int and pid>0:
        try:session=str(pid)+':'+(PROC/str(pid)/'stat').read_text().rsplit(')',1)[1].split()[19]
        except (OSError,IndexError):session=str(pid)
    return {'running':running,'fresh':fresh,'healthy':running and fresh and runtime.get('refresh_ok') is True,
        'session':session,'sample_at':sample_at,'counters':safe,'game':game_title,'area':area_title,'device':address,'device_name':device_name}

def snapshot():
    rows=[];cache=read_json(CACHE)
    for row in sources():
        cached=cache.get(row['id'],{})
        rows.append({k:row[k] for k in ('title','game','starpass')} | {k:cached[k] for k in ('info','updated_at','state') if k in cached})
    entries={}
    for kind in ('shared','accelerator'):
        value=read_json(Path('/tmp/portalproxy/entry-'+kind+'.json'))
        stamp=value.get('updated_at',0)
        fresh=isinstance(stamp,(int,float)) and -5<=time.time()-stamp<=5
        entries[kind]={'fresh':fresh,'route':value.get('route','direct'),'traffic':value.get('traffic',{}) if fresh else {}}
    from updater import status
    return {'now':int(time.time()),'subscriptions':rows,'entries':entries,'accelerator':accelerator_snapshot(),'update':status()}

if __name__=='__main__':
    try:
        command=sys.argv[1] if len(sys.argv)==2 else ''
        if command=='status':result=snapshot()
        elif command=='subscriptions-refresh':result=refresh()
        elif command=='start-refresh':
            subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'subscriptions-refresh'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            result={'ok':True}
        else:raise ValueError('Unknown operation')
        print(json.dumps(result,ensure_ascii=False))
    except Exception:print(json.dumps({'ok':False,'error':'无法读取本地状态，请检查服务'}))
