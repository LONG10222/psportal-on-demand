"""Official WeChat QR flow with normal user authorization and bounded parsing."""
import base64
import html
import http.client
from http.cookies import SimpleCookie
import ipaddress
import json
import re
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit, urlencode

from xianniu_router.dns import resolve_real

HOSTS = {'api1.xianniu.com', 'webapi.xianniu.com', 'webapi.xianniu.cc',
         'wap.xianniu.com', 'user.xianniu.com', 'threelogin.xianniu.com',
         'open.weixin.qq.com', 'long.open.weixin.qq.com', 'lp.open.weixin.qq.com'}


class AuthenticationRedirectError(ValueError):
    def __init__(self,url):
        self.url=url
        super().__init__('Unsupported official authentication URL')


class OfficialHTTP:
    def __init__(self, resolver, cookies=None):
        self.resolver = resolver
        self.cookies = cookies if cookies is not None else []
        self.history = []

    def request(self, url, timeout=12, stop_at_login=False):
        for _ in range(5):
            target = urlsplit(url)
            self.history.append(url)
            if (target.scheme != 'https' or target.hostname not in HOSTS or
                    target.port not in (None,443) or target.username or target.password):
                raise AuthenticationRedirectError(url)
            address = resolve_real(target.hostname, self.resolver)
            if not ipaddress.IPv4Address(address).is_global:
                raise ValueError('Non-public authentication address')
            connection = http.client.HTTPSConnection(target.hostname, timeout=timeout)
            try:
                raw = socket.create_connection((address,443),timeout=timeout)
                try:
                    connection.sock = ssl.create_default_context().wrap_socket(raw,server_hostname=target.hostname)
                except BaseException:
                    raw.close()
                    raise
                headers = {'User-Agent':'Mozilla/5.0', 'Accept':'*/*'}
                cookies = [row['name']+'='+row['value'] for row in self.cookies
                           if target.hostname == row['domain'] or target.hostname.endswith('.'+row['domain'])]
                if cookies:
                    headers['Cookie'] = '; '.join(cookies)
                path = target.path or '/'
                if target.query:
                    path += '?'+target.query
                connection.request('GET',path,headers=headers)
                response = connection.getresponse()
                data = response.read(1048577)
                if len(data)>1048576:
                    raise ValueError('Oversized authentication response')
                for key,value in response.getheaders():
                    if key.lower() != 'set-cookie':
                        continue
                    jar = SimpleCookie()
                    try:jar.load(value)
                    except Exception:continue
                    for name,morsel in jar.items():
                        domain = (morsel['domain'] or target.hostname).lstrip('.').lower()
                        if target.hostname != domain and not target.hostname.endswith('.'+domain):
                            continue
                        self.cookies[:] = [r for r in self.cookies if (r['domain'],r['name']) != (domain,name)]
                        self.cookies.append({'domain':domain,'name':name,'value':morsel.value})
                if response.status in (301,302,303,307,308):
                    location = response.getheader('Location')
                    if not location:
                        raise ValueError('Missing official redirect')
                    url = urljoin(url,location)
                    landing=urlsplit(url)
                    if stop_at_login and landing.scheme=='https' and landing.port in (None,443) and not landing.username and not landing.password and (
                            (landing.hostname=='threelogin.xianniu.com' and landing.path=='/pc/auth2.html') or
                            (landing.hostname=='user.xianniu.com' and landing.path=='/auth2.html')):
                        self.history.append(url)
                        return b'', 'text/html', url
                    continue
                if response.status != 200:
                    raise RuntimeError('Official authentication HTTP request failed')
                return data, response.getheader('Content-Type',''), url
            finally:
                connection.close()
        raise ValueError('Too many official authentication redirects')


def parse_qr_page(body):
    text = body.decode('utf-8',errors='replace')
    uuid = re.search(r'/connect/qrcode/([A-Za-z0-9_-]{8,100})',text)
    callback = re.search(r'var\s+t\s*=\s*"(https://webapi\.xianniu\.com/auth/weixinweb/callback\?[^"\s]+)"',text)
    state = re.search(r'wx_code\s*\+\s*"&state=([^"\s]+)"',text)
    if not uuid or not callback or not state:
        raise ValueError('Official QR page layout changed')
    return {'uuid':uuid[1], 'callback':html.unescape(callback[1]), 'state':state[1],
            'poll_host':'lp.open.weixin.qq.com' if re.search(r'usenewdomain\s*=\s*[\x27"]1[\x27"]',text) else 'long.open.weixin.qq.com'}


def create_qr(resolver):
    client = OfficialHTTP(resolver)
    # Keep the official login session cookie on the callback's own host.
    page,_,_ = client.request('https://webapi.xianniu.com/auth/weixinweb?client_type=0')
    state = parse_qr_page(page)
    image,content_type,_ = client.request('https://open.weixin.qq.com/connect/qrcode/'+state['uuid'])
    if not image.startswith(b'\x89PNG\r\n\x1a\n') and not image.startswith(b'\xff\xd8\xff'):
        raise ValueError('Unexpected official QR image format')
    state.update(created_at=int(time.time()),expires_at=int(time.time())+240,cookies=client.cookies,
                 resolver=resolver,status='waiting')
    return state,image


def poll_qr(state):
    if time.time()>=state['expires_at']:
        state['status']='expired'
        return {'status':'expired'}
    client=OfficialHTTP(state['resolver'],state.get('cookies',[]))
    try:
        data,_,_=client.request('https://'+state['poll_host']+'/connect/l/qrconnect?'+urlencode({'uuid':state['uuid']}),timeout=3)
    except (TimeoutError,socket.timeout):
        return {'status':state.get('status','waiting')}
    text=data.decode('utf-8',errors='replace')
    match=re.search(r'wx_errcode\s*=\s*(\d+)',text)
    if not match:
        raise ValueError('Unexpected WeChat authorization response')
    code=int(match[1])
    if code==405:
        wx_code=re.search(r"wx_code\s*=\s*[\x27\"]([A-Za-z0-9_-]{4,256})[\x27\"]",text)
        if not wx_code:
            raise ValueError('Missing authorized WeChat code')
        url=state['callback']+'&'+urlencode({'code':wx_code[1],'state':state['state']})
        try:
            payload,content_type,final_url=client.request(url,stop_at_login=True)
        except AuthenticationRedirectError as error:
            # Retain an unrecognized callback URI as data, never fetch it or
            # repeat the already-authorized OAuth callback to recover it.
            payload,content_type,final_url=b'','application/octet-stream',error.url
        state['status']='authorized'
        state['cookies']=client.cookies
        return {'status':'authorized','callback_body':payload,'content_type':content_type,
                'final_url':final_url,'redirect_chain':client.history}
    state['status']={404:'scanned',402:'expired',403:'cancelled',408:'waiting'}.get(code,'waiting')
    state['cookies']=client.cookies
    return {'status':state['status']}
