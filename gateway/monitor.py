#!/usr/bin/python3
"""Sanitized dashboard snapshots and explicit subscription-account refresh."""
import hashlib,json,os,re,subprocess,sys,time
from pathlib import Path
from entry import option
from net import request
CACHE=Path('/etc/portalproxy/subscription-usage.json')

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
    return {'now':int(time.time()),'subscriptions':rows,'entries':entries,'update':status()}

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
