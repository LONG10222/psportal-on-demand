-- Pure helpers plus mocked transaction tests. No network, curl, daemon, UCI,
-- router or installer is used.
local directory=arg[0]:match('^(.*)/') or '.'
package.path=directory..'/../src/?.lua;'..package.path
local s=require 'subscription'
local count=0
local function check(value,message) assert(value,message); count=count+1 end
local function rejects(fn,message)
    local ok,err=pcall(fn)
    check(not ok,message)
    check(not tostring(err):find('private-token',1,true),message..' does not reveal token')
end
local function record(ip,family) return {family=family or 'inet',address=ip} end
local url='https://subscription.example.com/provider?token=private-token'
local options={subscription_url=url}
local target=s.validate_url(url)
check(target.host=='subscription.example.com' and target.port==443 and not target.is_ipv4,'DNS URL')
check(target.url==url,'opaque query retained')
check(s.validate_url('https://SUBSCRIPTION.Example.COM:8443/a').url==
    'https://subscription.example.com:8443/a','canonical lowercase DNS URL')
check(s.validate_url('https://1.1.1.1/').is_ipv4,'public literal')
check(s.validate_url('https://sub.example.com').port==443,'no path')
check(s.validate_url('https://sub.example.com?token=a%23b%2Fc%25').host=='sub.example.com','encoded path delimiters')
check(s.validate_url('https://xn--bcher-kva.example.com/a').host=='xn--bcher-kva.example.com','ASCII punycode name')
for _,bad in ipairs({
    'http://subscription.example.com/', 'ftp://subscription.example.com/', 'HTTPS://subscription.example.com/',
    'https://user:private-token@subscription.example.com/', 'https://subscription.example.com/#private-token',
    'https://subscription.example.com/ private-token', 'https://subscription.example.com/\nprivate-token',
    'https://subscription.example.com/\rprivate-token', 'https://subscription.example.com/\0private-token',
    'https://subscription.example.com/\\private-token', 'https://subscription.example.com/"private-token',
    'https://subscription.example.com/<private-token>', 'https://subscription.example.com/%',
    'https://subscription.example.com/%0', 'https://subscription.example.com/%GG',
    'https://subscription.example.com:0/', 'https://subscription.example.com:65536/',
    'https://subscription.example.com:0443/', 'https://subscription.example.com:bad/',
    'https://subscription.example.com:/', 'https://subscription.example.com:443:80/',
    'https://[::1]/', 'https://[2606:4700:4700::1111]/', 'https://::1/',
    'https://localhost/', 'https://service.localhost/', 'https://service.local/', 'https://router.lan/',
    'https://router.home.arpa/', 'https://service.internal/', 'https://router/',
    'https://subscription.example.com./', 'https://.example.com/', 'https://sub..example.com/',
    'https://-sub.example.com/', 'https://sub-.example.com/', 'https://sub_name.example.com/',
    'https://127.1/', 'https://2130706433/', 'https://0177.0.0.1/', 'https://0x7f000001/',
    'https://0x7f.0.0.1/', 'https://127.000.0.1/', 'https://256.1.1.1/',
    'https://%31%32%37.0.0.1/', 'https://example.com%2f@127.0.0.1/',
    'https://subscription.example.com/REPLACE_ME', 'https://'..string.rep('a',64)..'.example.com/',
    'https://'..string.rep('a',63)..'.'..string.rep('b',63)..'.'..string.rep('c',63)..'.'..string.rep('d',63)..'/',
    'https://subscription.example.com/'..string.rep('x',8192)
}) do rejects(function() s.validate_url(bad) end,'reject unsafe URL') end
for _,bad in ipairs({'0.0.0.0','0.1.2.3','10.0.0.1','100.64.0.1','100.127.255.254','127.0.0.1',
    '169.254.169.254','172.16.0.1','172.31.255.254','192.0.0.1','192.0.2.1','192.88.99.1',
    '192.168.1.1','198.18.0.1','198.19.255.254','198.51.100.1','203.0.113.1','224.0.0.1',
    '239.1.1.1','240.0.0.1','255.255.255.255','001.1.1.1','1.2.3','::ffff:8.8.8.8','8.8.8.8.'}) do
    check(not s.public_ipv4(bad),'non-public/noncanonical address')
    rejects(function() s.validate_url('https://'..bad..'/') end,'reject non-public literal URL')
    rejects(function() s.validate_addresses({record(bad)}) end,'reject unsafe DNS address')
    rejects(function() s.validate_addresses({record('1.1.1.1'),record(bad)}) end,'reject mixed DNS answers')
    rejects(function() s.validate_addresses({record(bad),record('1.1.1.1')}) end,'reject reversed mixed DNS answers')
end
for _,ip in ipairs({'1.1.1.1','8.8.8.8','9.9.9.9','100.63.255.255','100.128.0.1','172.15.255.255','172.32.0.1'}) do
    check(s.public_ipv4(ip),'public address accepted')
end
check(s.validate_addresses({record('1.1.1.1'),record('8.8.8.8')})=='1.1.1.1','pin first checked public result')
for _,records in ipairs({{}, {record('::1','inet6')}, {record('2606:4700:4700::1111','inet6')},
    {record('1.1.1.1'),record('::ffff:127.0.0.1','inet6')}, {record('1.1.1.1','unknown')},
    {record('1.1.1.1'),{}}, {'1.1.1.1'}}) do
    rejects(function() s.validate_addresses(records) end,'reject malformed/IPv6 DNS result')
end
local too_many={}; for i=1,129 do too_many[i]=record('1.1.1.1') end
rejects(function() s.validate_addresses(too_many) end,'DNS answer bound')
rejects(function() s.validate_addresses(nil) end,'nil DNS result')
rejects(function() s.validate_url(nil) end,'nil URL')

local cfg=s.curl_config(target,'1.1.1.1','client "quoted" \\ agent')
for _,line in ipairs({'proto = "=https"','proto-redir = "=https"','proxy = ""','noproxy = "*"',
    'no-location','max-redirs = 0','no-insecure','no-netrc','globoff','ipv4','http1.1','tlsv1.2',
    'silent','fail','connect-timeout = 10','max-time = 30','max-filesize = 5242880',
    'resolve = "subscription.example.com:443:1.1.1.1"','write-out = "%{http_code}"'}) do
    check(('\n'..cfg):find('\n'..line..'\n',1,true)~=nil,'required curl option '..line)
end
check(cfg:find('user-agent = "client \\"quoted\\" \\\\ agent"',1,true)~=nil,'curl quotes and backslashes escaped')
for _,bad in ipairs({'bad\nurl = "https://127.0.0.1/"','bad\ragent','bad\0agent',string.rep('x',256),'é'}) do
    rejects(function() s.curl_config(target,'1.1.1.1',bad) end,'reject curl configuration injection')
end
rejects(function() s.curl_config(target,'127.0.0.1','client') end,'reject private pin')
rejects(function() s.curl_config({url=url,host='different.example.com',port=443},'1.1.1.1') end,'reject target mismatch')
rejects(function() s.curl_config(s.validate_url('https://1.1.1.1/'),'8.8.8.8') end,'reject literal pin mismatch')

local content='proxies:\n  - name: Mock HK\n    type: http\n    server: proxy.example.com\n    port: 443\n'
for chunk_size=1,#content+3 do
    local stream=s.new_stream(); local output=''; local wire=content..'200'
    for pos=1,#wire,chunk_size do output=output..stream:push(wire:sub(pos,pos+chunk_size-1)) end
    check(stream:finish()==#content and output==content,'chunk-boundary-safe status suffix')
end
for _,status in ipairs({'000','204','206','301','302','307','308','400','401','403','404','500','abc','20'}) do
    rejects(function() local stream=s.new_stream(); stream:push(content..status); stream:finish() end,'reject non-200 status')
end
rejects(function() local stream=s.new_stream(); stream:push('200'); stream:finish() end,'reject empty body')
local maximum=s.new_stream()
check(#maximum:push(string.rep('x',s.MAX_BYTES)..'200')==s.MAX_BYTES and maximum:finish()==s.MAX_BYTES,
    'exact 5 MiB allowed')
rejects(function() s.new_stream():push(string.rep('x',s.MAX_BYTES+1)..'200') end,'oversized chunk rejected before write')

local function transaction(settings)
    settings=settings or {}
    local old,scratch,commits,fetched,resolved='old complete provider','',0,0,0
    local ok,result=pcall(s.update,settings.options or options,{
        resolve=function(host)
            resolved=resolved+1
            check(host=='subscription.example.com','resolver receives host only')
            if settings.resolve_error then error('mock DNS failure') end
            return settings.records or {record('1.1.1.1'),record('8.8.8.8')}
        end,
        fetch=function(configuration,receive)
            fetched=fetched+1
            check(configuration:find('resolve = "',1,true)~=nil,'fetch always pinned')
            for _,chunk in ipairs(settings.chunks or {content,'200'}) do receive(chunk) end
            return not settings.fetch_fail
        end,
        write=function(chunk)
            if settings.write_fail then return false end
            scratch=scratch..chunk
            check(#scratch<=s.MAX_BYTES,'spool bound')
            return true
        end,
        commit=function(size)
            if settings.commit_fail then return false end
            check(size==#scratch,'commit size checked')
            commits=commits+1; old=scratch; return true
        end
    })
    return {ok=ok,result=result,cache=old,scratch=scratch,commits=commits,fetched=fetched,resolved=resolved}
end
local good=transaction()
check(good.ok and good.cache==content and good.commits==1,'successful atomic publish')
local literal=transaction({options={subscription_url='https://1.1.1.1/'}})
check(literal.ok and literal.resolved==0,'public literal skips DNS')
for _,failure in ipairs({{resolve_error=true},{records={record('1.1.1.1'),record('192.168.1.1')}},
    {records={record('::1','inet6')}},{fetch_fail=true},{write_fail=true},{commit_fail=true},
    {chunks={'200'}},{chunks={content,'302'}},{chunks={content,'500'}},
    {chunks={string.rep('x',s.MAX_BYTES),'xxxx','200'}},
    {options={subscription_url='http://subscription.example.com/private-token'}}}) do
    local failed=transaction(failure)
    check(not failed.ok and failed.cache=='old complete provider' and failed.commits==0,
        'failure leaves old cache untouched')
end
local invalid_dns=transaction({records={record('1.1.1.1'),record('127.0.0.1')}})
check(invalid_dns.fetched==0,'mixed DNS rejected before network fetch')
assert(loadfile(directory..'/../src/update-subscription.lua'))
print('Passed '..count..' subscription security assertions')
