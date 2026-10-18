local directory = arg[0]:match('^(.*)/') or '.'
package.path = directory .. '/../src/?.lua;' .. package.path
local p = require 'protocol'
local config = require 'config'
local count = 0
local function check(value,message) assert(value,message); count=count+1 end
local function rejects(fn,message) local ok=pcall(fn); check(not ok,message) end
check(config.to_yaml({},function() return '{"url":"https:\\/\\/example.com"}' end)=='{"url":"https://example.com"}','JSON slash escapes must be YAML compatible')
for _,ip in ipairs({'10.20.0.1','172.16.0.1','172.31.255.254','192.168.50.1','127.0.0.1','169.254.1.1','100.64.0.1','100.127.255.254','::1','fd12::1','fe80::1'}) do check(p.local_ip(ip),'local '..ip) end
for _,ip in ipairs({'172.15.0.1','172.32.0.1','100.63.0.1','100.128.0.1','203.0.113.10','2001:db8::1','example.com','fc-example.com'}) do check(not p.local_ip(ip),'public '..ip) end
for _,ip in ipairs({'999.1.2.3','1.2.3','01.2.3.4','1.2.3.4.example','1.2.3.-1',''}) do check(not p.ipv4(ip),'invalid IP '..ip) end
local r=p.parse_request('CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n')
check(r and r.host=='example.com' and r.port==443 and r.method=='CONNECT','CONNECT parsing')
r=p.parse_request('GET http://example.com?mode=test HTTP/1.1\r\n\r\n')
check(r and r.path=='/?mode=test','query without slash')
r=p.parse_request('GET http://example.com/a#fragment HTTP/1.1\r\n\r\n')
check(r and r.path=='/a','fragment stripping')
for _,line in ipairs({'GET / HTTP/1.1','CONNECT user@host:443 HTTP/1.1','CONNECT host:0 HTTP/1.1','CONNECT host:65536 HTTP/1.1','CONNECT host:abc HTTP/1.1','GET https://example.com/ HTTP/1.1','GET http://999.1.2.3/ HTTP/1.1','CONNECT :443 HTTP/1.1','CONNECT [::1 HTTP/1.1'}) do check(not p.parse_request(line..'\r\n\r\n'),'reject '..line) end
local header='POST http://192.168.50.1/path HTTP/1.1\r\nHost: 192.168.50.1\r\nProxy-Authorization: secret\r\nProxy-Connection: keep-alive\r\nConnection: keep-alive\r\nContent-Length: 4\r\n\r\n'
r=p.parse_request(header)
local forwarded=p.local_request(header,r,'body')
check(forwarded:find('POST /path HTTP/1.1',1,true)==1,'origin form rewrite')
check(not forwarded:lower():find('proxy%-authorization:'),'drop proxy credentials')
check(not forwarded:lower():find('keep%-alive'),'force local close')
check(forwarded:sub(-4)=='body','preserve body')
local options={listen_ip='192.168.50.2',client_ip='192.168.50.30',local_dns='192.168.50.1',subscription_url='https://subscription.example.com/clash?token=unit-test-placeholder'}
local core,policy=config.render(options,string.rep('a',64))
check(core['allow-lan']==false and core['bind-address']=='127.0.0.1','backend is loopback-only')
check(core['tun'].enable==false and core['tproxy-port']==0 and core['redir-port']==0,'no transparent interception')
check(policy.allowed_ip==options.client_ip and policy.idle_seconds==60,'one client and default idle timeout')
check(policy.port~=core.port and policy.api_port~=core.port,'separate listener/backend/API ports')
check(core['proxy-groups'][1].type=='fallback','fallback group')
check(core['proxy-groups'][1].filter:find('Hong',1,true)<core['proxy-groups'][1].filter:find('Japan',1,true),'HK before Japan')
check(core['proxy-groups'][1].filter:sub(-2)=='.*','other regions remain available')
check(core['proxy-groups'][1].filter:find('\\bHK\\b',1,true)~=nil,'word-boundary regex survives serialization')
check(core['proxy-groups'][1]['empty-fallback']=='REJECT','empty provider fails closed')
check(core['proxy-providers'].SUBSCRIPTION.url==options.subscription_url,'only supplied subscription')
local dns_arrays={core.dns['default-nameserver'],core.dns['proxy-server-nameserver'],core.dns['direct-nameserver'],core.dns['nameserver-policy']['subscription.example.com']}
for i,a in ipairs(dns_arrays) do
    check(a[1]==options.local_dns,'DNS bootstrap value')
    for j=1,i-1 do check(a~=dns_arrays[j],'DNS tables must not alias in json-c') end
end
local function changed(key,value) local o={}; for k,v in pairs(options) do o[k]=v end; o[key]=value; return o end
rejects(function() config.validate(changed('client_ip','')) end,'missing client')
rejects(function() config.validate(changed('client_ip',options.listen_ip)) end,'client cannot be router')
rejects(function() config.validate(changed('listen_ip','0.0.0.0')) end,'no wildcard listener')
rejects(function() config.validate(changed('listen_port','18680')) end,'port collision')
rejects(function() config.validate(changed('subscription_url','http://subscription.example.com/')) end,'HTTPS subscription required')
rejects(function() config.validate(changed('subscription_url','https://subscription.example.com:bad/')) end,'invalid subscription port')
rejects(function() config.validate(changed('subscription_url','https://user:pass@subscription.example.com/')) end,'subscription userinfo')
rejects(function() config.validate(changed('subscription_url','https://subscription.example.com/REPLACE_ME')) end,'placeholder rejected')
rejects(function() config.validate(changed('subscription_user_agent','header\r\ninjection')) end,'header injection rejected')
rejects(function() config.validate(changed('bootstrap_dns','not-an-address')) end,'invalid DNS rejected')
rejects(function() config.validate(changed('idle_seconds','0')) end,'idle range')
print('Passed '..count..' protocol/config assertions')
