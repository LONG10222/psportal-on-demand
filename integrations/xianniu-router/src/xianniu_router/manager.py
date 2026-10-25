"""Authenticated LuCI management; private credentials never enter RPC replies."""
from contextlib import contextmanager
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time

from .auth_api import authenticate,authorization_code
from .auth_web import create_qr,poll_qr
from .control import call_api,APIError
from .member_time import balances

PART_SIZE=24576


def search_key(value):
    return ''.join(c for c in str(value).casefold() if c.isalnum())


def fuzzy_match(term,text):
    cursor=iter(text)
    return all(any(c==wanted for c in cursor) for wanted in term)


def atomic_json(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(path.parent,0o700)
    temporary=path.parent/(path.name+'.'+secrets.token_hex(8)+'.tmp')
    try:
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(value,stream,ensure_ascii=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        os.chmod(path,0o600)
    finally:
        if temporary.exists():temporary.unlink()


class Manager:
    def __init__(self,private='/etc/xianniu-router',catalog='/usr/share/xianniu-router/catalog.json',
                 status='/var/run/xianniu-router.json'):
        self.private=Path(private);self.path=self.private/'session.json'
        self.catalog_path=Path(catalog);self.status_path=Path(status)

    @contextmanager
    def lock(self,name='manager.lock'):
        self.private.mkdir(parents=True,exist_ok=True,mode=0o700)
        os.chmod(self.private,0o700)
        descriptor=os.open(self.private/name,os.O_CREAT|os.O_RDWR,0o600)
        try:
            if os.name=='posix':
                import fcntl
                fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
            yield
        finally:os.close(descriptor)

    def config(self):
        try:return json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            try:identity=Path('/sys/class/net/br-lan/address').read_text().strip()
            except FileNotFoundError:identity=secrets.token_hex(16)
            return {'hardware':'N1-'+hashlib.sha256(identity.encode()).hexdigest()[:32],
                    'account':{},'auth':{'plain_second':True,'x':''},'node':{},
                    'game_id':797,'profile':{'area_id':933,'line_id':122,'isp_type':3},
                    'start_on_launch':True,'dns_server':'192.168.31.1','devices':[], 'interface':'br-lan'}

    def runtime(self):
        try:return json.loads(self.status_path.read_text())
        except (ValueError,FileNotFoundError):return {'running':False}

    def preferences(self):
        try:
            from .devices import device_preferences
            return device_preferences(json.loads((self.private/'preferences.json').read_text(encoding='utf-8')))
        except (ValueError,FileNotFoundError):return {'devices':{},'recent':[]}

    def catalog(self,query='',platform='',offset=0,limit=24):
        if not isinstance(query,str) or len(query)>64:raise ValueError('搜索内容过长')
        if platform not in ('','pc','console','switch','recent'):raise ValueError('游戏分类无效')
        offset=int(offset);limit=int(limit)
        if offset<0 or not 1<=limit<=48:raise ValueError('分页参数无效')
        games=json.loads(self.catalog_path.read_text(encoding='utf-8'))
        terms=[search_key(term) for term in query.split() if search_key(term)]
        recent=self.preferences().get('recent',[])
        found=[]
        for row in games:
            if query.strip().isdigit() and query.strip()!=str(row['id']):continue
            if platform=='recent' and row['id'] not in recent:continue
            if platform not in ('','recent') and row.get('platform','pc')!=platform:continue
            haystack=search_key(row['title']+' '+row.get('keywords',''))
            if terms and not all(term==str(row['id']) or fuzzy_match(term,haystack) for term in terms):continue
            found.append(row)
        found.sort(key=lambda row:(recent.index(row['id']) if row['id'] in recent else len(recent),
                                   row['id']!=797,not row.get('hot',False),row['id']))
        return {'games':found[offset:offset+limit],'total':len(found),'offset':offset,'limit':limit}

    def devices(self):
        from .devices import discover
        result=discover(self.config(),self.preferences())
        result.pop('local',None)
        result['active_device']=self.config().get('active_device','')
        result['mode']='http_proxy_tcp'
        return result

    def status(self):
        config=self.config();info=config.get('login_info',{})
        runtime=self.runtime();member=self.member_cached()
        saved=bool(config.get('account',{}).get('access_token'))
        required=bool(runtime.get('login_required') or member.get('login_required'))
        login_state=('login_required' if required else 'authenticated' if saved and info.get('at') and
                     info.get('method') in ('wechat','password') else 'saved_unverified' if saved else 'logged_out')
        return {'saved_login':saved,'login_state':login_state,
                'login_required':required,
                'login_method':info.get('method','imported'), 'login_at':info.get('at'),
                'nickname':info.get('nickname',''), 'game_id':config.get('game_id',797),
                'profile':config.get('profile',{}), 'runtime':runtime,
                'active_device':config.get('active_device',''),'active_device_mac':config.get('active_device_mac',''),
                'member':member,
                'login_methods':['wechat','password'], 'sms_login_supported':False}

    def lines(self,game_id,area_id):
        game_id=int(game_id);area_id=int(area_id)
        if game_id<1 or area_id<1:raise ValueError('请选择游戏和区服')
        rows=call_api(self.config(),'/client/accelerate/linelist',{'game_id':game_id,'area_id':0})
        if not isinstance(rows,list):raise ValueError('官方线路列表格式发生变化')
        result=[];inventory=[]
        for row in rows:
            if not isinstance(row,dict):continue
            areas=row.get('area_ids',[])
            if isinstance(areas,str):areas=re.findall(r'\d+',areas)
            area_values=[int(x) for x in areas if str(x).isdigit()] if isinstance(areas,list) else []
            compatible=not area_values or area_id in area_values
            try:identity=int(row['line_id'])
            except (KeyError,TypeError,ValueError):continue
            title=str(row.get('line_title') or row.get('line_exit_name') or identity)[:120]
            thin={'id':identity,'title':title,'exclusive':bool(row.get('is_exclusive'))}
            if compatible:result.append(thin)
            entries=[]
            for key in ('speed_ip','telecom_ip','unicom_ip','mobile_ip'):
                try:
                    address=ipaddress.IPv4Address(row.get(key,''))
                    if address.is_global and str(address) not in entries:entries.append(str(address))
                except (ValueError,TypeError):pass
            inventory.append({**thin,'compatible':compatible,'area_ids':area_values,
                'entry':str(row.get('line_in') or '')[:80],'exit':str(row.get('line_out') or '')[:80],
                'isp':str(row.get('isp') or '')[:80],'provider':str(row.get('provider') or '')[:80],
                'entry_type':str(row.get('line_in_type_title') or '')[:80],'entry_ips':entries})
        return {'lines':result,'all_lines':inventory,'total':len(inventory)}

    def service(self,action):
        if action not in ('start','stop','enable','disable'):raise ValueError('Invalid service operation')
        if action=='enable' and Path('/etc/config/portalproxy').exists():
            # Paid acceleration requires an explicit start, regardless of the visible workspace.
            action='disable'
        result=subprocess.run(['/etc/init.d/xianniu-router',action],capture_output=True,timeout=40)
        if result.returncode:raise RuntimeError('鲜牛服务操作未成功，请查看状态')

    def set_enabled(self,enabled):
        for args in (['uci','set','xianniu-router.main.enabled='+('1' if enabled else '0')],
                     ['uci','commit','xianniu-router']):
            subprocess.run(args,check=True,capture_output=True,timeout=8)

    def start(self):
        with self.lock():
            if not self.config().get('account',{}).get('access_token'):raise ValueError('请先登录鲜牛账号')
            if self.runtime().get('running'):return {'started':True,'already_running':True}
            resumed=self.prepare_member()
            self.set_enabled(True);self.service('enable');self.service('start')
            return {'started':True,'time_resumed':resumed}

    def stop(self):
        with self.lock():
            self.service('stop');self.set_enabled(False);self.service('disable')
            return {'stopped':True}

    def select(self,game_id,area_id,line_id):
        game_id,area_id,line_id=int(game_id),int(area_id),int(line_id)
        with self.lock():
            if self.runtime().get('running'):raise ValueError('请先停止加速，再切换游戏或线路')
            games=json.loads(self.catalog_path.read_text(encoding='utf-8'))
            game=next((r for r in games if r['id']==game_id),None)
            if not game or area_id not in {r['id'] for r in game['areas']}:raise ValueError('游戏或区服无效')
            if line_id not in {r['id'] for r in self.lines(game_id,area_id)['lines']}:raise ValueError('请选择当前区服的有效线路')
            config=self.config();config['game_id']=game_id
            config['profile']={**config.get('profile',{}),'area_id':area_id,'line_id':line_id}
            atomic_json(self.path,config)
            return {'saved':True}

    def launch(self,device,game_id,area_id,line_id):
        """Select one device/profile and switch this plugin's owned session."""
        from .devices import discover
        game_id,area_id,line_id=int(game_id),int(area_id),int(line_id)
        with self.lock():
            config=self.config()
            if not config.get('account',{}).get('access_token'):raise ValueError('请先登录鲜牛账号')
            inventory=discover(config,self.preferences())
            selected=next((r for r in inventory['devices'] if r['ip']==device),None)
            if selected is None:raise ValueError('请从发现的局域网设备中选择；离线设备可在高级设置添加')
            if inventory['host'] not in inventory['local']:raise ValueError('代理监听地址不是软路由现有地址，请检查高级设置')
            games=json.loads(self.catalog_path.read_text(encoding='utf-8'))
            game=next((r for r in games if r['id']==game_id),None)
            if not game or area_id not in {r['id'] for r in game['areas']}:raise ValueError('游戏或区服无效')
            if line_id not in {r['id'] for r in self.lines(game_id,area_id)['lines']}:raise ValueError('请选择当前区服的有效线路')
            running=self.runtime().get('running',False)
            same=(config.get('active_device')==device and config.get('game_id')==game_id and
                  config.get('profile',{}).get('area_id')==area_id and config.get('profile',{}).get('line_id')==line_id)
            if running and same:return {'started':True,'already_running':True}
            if running and self.billing(config.get('game_id'))=='paid' and self.billing(game_id)=='free':
                raise ValueError('请先停止当前付费加速并暂停计时，再选择免费项目')
            # Validate before stopping; never call an official stop for another
            # device/session outside this service's ownership.
            self.service('stop')
            if running and self.runtime().get('session_stop_ok') is False:
                raise ValueError('旧加速会话未确认停止，请稍后重试，避免会话冲突')
            resumed=self.prepare_member(game_id)
            config=self.config()
            config['game_id']=game_id;config['active_device']=device;config['active_device_mac']=selected.get('mac','');config['devices']=[device]
            config['profile']={**config.get('profile',{}),'area_id':area_id,'line_id':line_id}
            atomic_json(self.path,config)
            preferences=self.preferences()
            from .devices import mac_key
            identity=mac_key(selected.get('mac'))
            if identity:
                old=preferences.setdefault('devices',{}).get(identity,{})
                preferences['devices'][identity]={**old,'name':selected['name'],'mac':identity,'last_ip':device,
                    'game_id':game_id,'area_id':area_id,'line_id':line_id}
            preferences['recent']=([game_id]+[r for r in preferences.get('recent',[]) if r!=game_id])[:20]
            atomic_json(self.private/'preferences.json',preferences)
            # Only this plugin's UCI namespace is written. Device networking,
            # main-router DHCP and other proxy services stay untouched.
            commands=[['uci','-q','delete','xianniu-router.main.devices'],
                      ['uci','add_list','xianniu-router.main.devices='+device],
                      ['uci','set','xianniu-router.main.http_enabled=1'],
                      ['uci','set','xianniu-router.main.http_host='+inventory['host']],
                      ['uci','set','xianniu-router.main.enabled=1'],['uci','commit','xianniu-router']]
            for index,args in enumerate(commands):
                result=subprocess.run(args,capture_output=True,timeout=8)
                if result.returncode and index!=0:raise RuntimeError('插件配置保存未完成')
            self.service('enable');self.service('start')
            return {'started':True,'device':device,'game':game['title'],'switched':bool(running),'time_resumed':resumed}

    def set_device_note(self,mac,note):
        from .devices import discover,mac_key
        identity=mac_key(mac)
        if not identity:raise ValueError('设备 MAC 地址无效')
        if not isinstance(note,str) or len(note)>64 or any(ord(c)<32 or ord(c)==127 for c in note):
            raise ValueError('备注最多 64 个字符，不能包含控制字符')
        with self.lock():
            preferences=self.preferences()
            row=next((r for r in discover(self.config(),preferences)['devices'] if mac_key(r.get('mac'))==identity),None)
            old=preferences.setdefault('devices',{}).get(identity,{})
            if row is None and not old:raise ValueError('请先发现设备，再保存备注')
            preferences['devices'][identity]={**old,'mac':identity,'note':note.strip(),
                'last_ip':row['ip'] if row else old.get('last_ip','')}
            atomic_json(self.private/'preferences.json',preferences)
        return {'saved':True,'mac':identity,'note':note.strip()}

    def billing(self,game_id=None):
        identity=int(self.config().get('game_id',797) if game_id is None else game_id)
        games=json.loads(self.catalog_path.read_text(encoding='utf-8'))
        game=next((row for row in games if row.get('id')==identity),None)
        flag=game.get('is_free') if game else None
        if type(flag) is not bool:raise ValueError('官方目录缺少计费标记，请更新目录后再启动')
        return 'free' if flag else 'paid'

    def finish(self):
        with self.lock():
            was_running=self.runtime().get('running',False)
            kind=self.billing()
            self.service('stop');self.set_enabled(False);self.service('disable')
            if was_running and self.runtime().get('session_stop_ok') is not True:
                raise ValueError('官方停止尚未确认，暂未暂停会员计时')
            if not was_running or kind=='free':return {'stopped':True,'billing':kind,'time_paused':False}
            config=self.config()
            call_api(config,'/client/member/suspend',{'access_token':config['account']['access_token'],'sender':0})
            member=self._member()
            if member.get('pause_state') not in (0,'0'):raise ValueError('官方尚未确认暂停，请刷新会员状态')
            return {'stopped':True,'billing':kind,'time_paused':True}

    def prepare_member(self,game_id=None):
        if self.billing(game_id)=='free':return False
        member=self._member()
        if member.get('pause_state') not in (0,'0'):return False
        config=self.config()
        call_api(config,'/client/member/recovery',{'access_token':config['account']['access_token'],'sender':0})
        current=self._member()
        if current.get('pause_state') in (0,'0'):raise ValueError('官方会员计时仍处于暂停，请刷新会员状态后重试')
        return True

    def member_cached(self):
        try:
            value=json.loads((self.private/'member.json').read_text(encoding='utf-8'))
            return {**value,**balances(value),
                    'sample_age_seconds':max(0,int(time.time())-int(value.get('updated_at',time.time())))}
        except (ValueError,FileNotFoundError):return {}

    def member(self):
        with self.lock():return self._member()

    def _member(self):
        config=self.config();token=config.get('account',{}).get('access_token')
        if not token:raise ValueError('请先登录鲜牛账号')
        try:data=call_api(config,'/client/member/details',{'access_token':token})
        except APIError as error:
            if error.code in (400009,400010,400011,400024,400065):
                atomic_json(self.private/'member.json',{'login_required':True,'error_code':error.code,'updated_at':int(time.time())})
            raise
        if not isinstance(data,dict):raise ValueError('官方会员状态格式发生变化')
        public={'updated_at':int(time.time()),'sample_age_seconds':0}
        for key in ('pause_state','total_datetime','free_datetime','expired_datetime',
                    'notpause_expired_datetime','billing_type','package_title'):
            if isinstance(data.get(key),(str,int,float,bool)):public[key]=data[key]
        public.update(balances(public))
        atomic_json(self.private/'member.json',public)
        return public

    def member_pause(self):
        with self.lock():
            token=self.config().get('account',{}).get('access_token')
            if not token:raise ValueError('请先登录鲜牛账号')
            running=self.runtime().get('running',False)
            self.service('stop');self.set_enabled(False);self.service('disable')
            if running and self.runtime().get('session_stop_ok') is False:
                raise ValueError('加速会话未确认停止，暂未暂停会员计时')
            config=self.config()
            call_api(config,'/client/member/suspend',{'access_token':config['account']['access_token'],'sender':0})
            return self._member()

    def member_resume(self):
        with self.lock():
            token=self.config().get('account',{}).get('access_token')
            if not token:raise ValueError('请先登录鲜牛账号')
            call_api(self.config(),'/client/member/recovery',{'access_token':token,'sender':0})
            return self._member()

    def accept_login(self,account,method):
        token=account.get('access_token')
        if not isinstance(token,str) or not token:raise ValueError('官方登录信息不完整')
        self.service('stop')
        atomic_json(self.private/'login-response.json',
                    {key:value for key,value in account.items() if key not in ('password','smscode','smscode_key')})
        config=self.config();config['account']={'access_token':token}
        config['start_on_launch']=True
        config['login_info']={'method':method,'at':int(time.time()),
                              'nickname':str(account.get('nickname') or account.get('username') or '')[:80]}
        atomic_json(self.path,config)
        self.status_path.unlink(missing_ok=True)
        (self.private/'member.json').unlink(missing_ok=True)
        return {'logged_in':True,'nickname':config['login_info']['nickname']}

    def login_password(self,mobile,password):
        with self.lock():
            account=authenticate(self.config(),'password',{'mobile':mobile,'password':password})
            return self.accept_login(account,'password')

    def qr_paths(self,identity):
        if not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{32}',identity):raise ValueError('登录请求无效')
        return self.private/('wechat-'+identity+'.json'),self.private/('wechat-'+identity+'.png')

    def wechat_create(self):
        # New QR requests have unique files and do not alter the account.
        # Long-polling a previous code must never block refreshing its image.
        state,image=create_qr(self.config().get('dns_server','192.168.31.1'))
        identity=secrets.token_hex(16);state_path,image_path=self.qr_paths(identity)
        atomic_json(state_path,state)
        fd=os.open(image_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(image)
        return {'id':identity,'expires_at':state['expires_at'],'parts':(len(image)+PART_SIZE-1)//PART_SIZE,
                'mime':'image/png' if image.startswith(b'\x89PNG') else 'image/jpeg'}

    def wechat_image(self,identity,part):
        _,path=self.qr_paths(identity);part=int(part)
        data=path.read_bytes()
        if part<0 or part*PART_SIZE>=len(data):raise ValueError('二维码片段无效')
        return {'chunk':base64.b64encode(data[part*PART_SIZE:(part+1)*PART_SIZE]).decode('ascii')}

    def wechat_poll(self,identity):
        path,_=self.qr_paths(identity)
        with self.lock('poll-'+identity+'.lock'):
            state=json.loads(path.read_text())
            if state.get('status')=='complete':return {'status':'complete','logged_in':True}
            if state.get('status')=='failed':raise ValueError('该次官方授权未完成，请重新获取二维码')
            cached=self.private/('result-'+identity+'.json')
            if state.get('status')=='authorized' and cached.exists():
                result=json.loads(cached.read_text())
            else:
                result=poll_qr(state)
                atomic_json(path,state)
                if result['status']!='authorized':return {'status':result['status']}
                result.pop('callback_body',None)
                atomic_json(cached,result)
            try:
                code=authorization_code(result)
                with self.lock():
                    account=authenticate(self.config(),'other',{'code':code})
                    self.accept_login(account,'wechat')
                state['status']='complete';atomic_json(path,state)
                return {'status':'complete','logged_in':True}
            except BlockingIOError:
                # Callback is already cached; retry account exchange when the
                # current service operation releases its lock.
                raise
            except Exception as error:
                state['status']='failed';state['error_type']=type(error).__name__
                if hasattr(error,'code'):state['error_code']=error.code
                atomic_json(path,state)
                raise
