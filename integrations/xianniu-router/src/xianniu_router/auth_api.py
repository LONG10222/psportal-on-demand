"""Official client login requests. Passwords are never persisted here."""
import hashlib
import json
import re
from urllib.parse import urlsplit,parse_qs

from .auth_web import OfficialHTTP
from .control import call_api
from .protocol import decode_api


def server_datetime(config):
    raw,_,_=OfficialHTTP(config.get('dns_server','192.168.31.1')).request('https://api1.xianniu.com/open/tools/datetime')
    try:value=json.loads(raw)
    except (ValueError,UnicodeError):value=decode_api(raw)
    if not isinstance(value,dict) or str(value.get('code')) not in ('0','200'):
        raise ValueError('Cannot obtain official server time')
    stamp=value.get('data',{}).get('datetime')
    if not isinstance(stamp,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}',stamp):
        raise ValueError('Unexpected official server time')
    return stamp


def common_fields(config):
    return {'hardware':config['hardware'],'os_type':0,'client_type':0,
            'client_version':'5.2.8.2','os_info':'PC_N1_iStoreOS','os_version':'Linux',
            'channel':'guanwang','datetime':server_datetime(config)}


def authenticate(config,method,value):
    fields=common_fields(config)
    if method=='password':
        mobile=value.get('mobile','');password=value.get('password','')
        if not isinstance(mobile,str) or not re.fullmatch(r'1\d{10}',mobile):
            raise ValueError('请输入有效的手机号')
        if not isinstance(password,str) or not 1<=len(password)<=128:
            raise ValueError('请输入密码')
        fields.update(mobile=mobile,mobile_code=86,
                      password=hashlib.md5(password.encode('utf-8')).hexdigest())
        path='/client/auth/login'
    elif method=='other':
        code=value.get('code','')
        if not isinstance(code,str) or not 4<=len(code)<=4096 or any(ord(c)<32 for c in code):
            raise ValueError('官方授权结果缺少登录凭据，请重新扫码')
        fields['code']=code
        path='/client/auth/other'
    elif method=='token':
        token=value.get('token','')
        if not isinstance(token,str) or not token or len(token)>8192:
            raise ValueError('没有可复用的官方登录信息')
        fields['token']=token
        path='/client/auth/login_token'
    else:
        raise ValueError('Unsupported official login method')
    result=call_api(config,path,fields)
    if not isinstance(result,dict) or not isinstance(result.get('access_token'),str) or not result['access_token']:
        raise ValueError('官方登录尚未完成或需要额外验证')
    return result


def authorization_code(result):
    url=result.get('final_url','')
    parsed=urlsplit(url)
    valid=((parsed.hostname=='user.xianniu.com' and parsed.path=='/auth2.html') or
           (parsed.hostname=='threelogin.xianniu.com' and parsed.path=='/pc/auth2.html'))
    if parsed.scheme!='https' or not valid or parsed.port not in (None,443) or parsed.username or parsed.password:
        raise ValueError('官方登录回调格式发生变化')
    values=parse_qs(parsed.query)
    code=values.get('code',[''])[0]
    if not code:
        raise ValueError('官方授权码为空或已使用，请重新扫码')
    return code


def restore_session(config):
    """Use the official client's saved-access-token login path once."""
    previous=config.get('account',{}).get('access_token')
    account=authenticate(config,'token',{'token':previous})
    path=config.get('_config_path')
    if path:
        from pathlib import Path
        from .manager import Manager,atomic_json
        manager=Manager(private=Path(path).parent)
        with manager.lock():
            current=manager.config()
            if current.get('account',{}).get('access_token')!=previous:
                raise RuntimeError('A newer account session already owns this configuration')
            current['account']={'access_token':account['access_token']}
            current.setdefault('login_info',{})['refreshed_at']=__import__('time').time()
            atomic_json(path,current)
            atomic_json(manager.private/'login-response.json',{k:v for k,v in account.items() if k not in ('password','smscode','smscode_key')})
    config['account']={'access_token':account['access_token']}
    return account
