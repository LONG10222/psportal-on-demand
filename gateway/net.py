"""Bounded HTTPS to pinned public IPv4 destinations, using existing LAN DNS."""
import http.client,ipaddress,json,re,socket,ssl,sys
from urllib.parse import urlsplit
sys.path.insert(0,'/usr/lib/xianniu-router')
from xianniu_router.dns import resolve_real
from entry import option

class PinnedHTTPS(http.client.HTTPSConnection):
    def connect(self):
        address=self.host
        try:ipaddress.IPv4Address(address)
        except ValueError:address=resolve_real(self.host,option('portalproxy','main.local_dns'),timeout=5)
        if not ipaddress.ip_address(address).is_global:raise ValueError('Public destination required')
        raw=socket.create_connection((address,self.port),self.timeout)
        try:self.sock=self._context.wrap_socket(raw,server_hostname=self.host)
        except BaseException:raw.close();raise

def request(url,limit=1024*1024,headers=None,head=False,redirects=0,allowed=None):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.fragment:raise ValueError('HTTPS URL required')
    host=parsed.hostname or ''
    if len(url)>8192 or not re.fullmatch(r'[a-zA-Z0-9.-]+',host) or any(ord(c)<33 or ord(c)>126 for c in url):raise ValueError('Invalid URL')
    if allowed and host not in allowed:raise ValueError('Untrusted download host')
    connection=PinnedHTTPS(host,parsed.port or 443,timeout=15,context=ssl.create_default_context())
    try:
        connection.request('GET',parsed.path+('?' + parsed.query if parsed.query else ''),headers={'User-Agent':'StarPass-Router','Connection':'close',**(headers or {})})
        response=connection.getresponse()
        if response.status in (301,302,303,307,308) and redirects and allowed:
            location=response.getheader('Location','')
            return request(location,limit,headers,head,redirects-1,allowed)
        if response.status!=200:raise ValueError('HTTPS request failed')
        result=dict(response.getheaders())
        if head:return {k.lower():v for k,v in result.items()},b''
        length=response.getheader('Content-Length')
        if length and int(length)>limit:raise ValueError('Download too large')
        body=response.read(limit+1)
        if len(body)>limit or (length and len(body)!=int(length)):raise ValueError('Incomplete download')
        return {k.lower():v for k,v in result.items()},body
    finally:connection.close()
