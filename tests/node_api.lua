-- In-memory fixtures only: no real sockets, files, services, or subscriptions.
local directory=arg[0]:match('^(.*)/') or '.'
local count=0
local function check(v,msg) assert(v,msg); count=count+1 end
local function copy(t)
    if type(t)~='table' then return t end
    local out={}; for k,v in pairs(t) do out[k]=copy(v) end; return out
end
local function load_module(name,deps)
    local env=setmetatable({require=function(k) return assert(deps[k],k) end},{__index=_G})
    local f
    if setfenv then f=assert(loadfile(directory..'/../src/'..name..'.lua')); setfenv(f,env)
    else f=assert(loadfile(directory..'/../src/'..name..'.lua','t',env)) end
    return f()
end
local function fixture()
    local w={time=100,files={},stats={},polls=0,sockets=0,requests={},closed=0,serial=0,objects={}}
    local cfg={run_dir='/mock/run',api_header='/mock/data/api-header',api_port=18681,health_url='https://health.example/204'}
    local function put(path,value,kind,mode,uid)
        w.files[path]=value; w.stats[path]={type=kind or 'reg',modestr=mode or 'rw-------',uid=uid or 0,size=#value}
    end
    put('/mock/run','','dir','rwx------'); put('/mock/data','','dir','rwx------')
    put(cfg.api_header,'Authorization: Bearer test-only-secret\n')
    local fs={lstat=function(path) return w.stats[path] end,
        readfile=function(path,limit) local v=w.files[path]; return v and v:sub(1,limit) end,
        remove=function(path) w.files[path]=nil; w.stats[path]=nil; return true end,
        rename=function(a,b)
            if w.fail_rename then return nil end
            w.files[b]=w.files[a]; w.stats[b]=w.stats[a]; w.files[a]=nil; w.stats[a]=nil; return true
        end}
    local json={parse=function(v) if w.parse_throw then error('mock bad JSON') end; return copy(w.objects[v]) end,
        stringify=function(v) w.serial=w.serial+1; local key='{"snapshot":'..w.serial..'}'; w.objects[key]=copy(v); return key end}
    local n={const={EAGAIN=11,EWOULDBLOCK=11,EINTR=4,EINPROGRESS=115},
        poll_flags=function(flag) return flag=='in' and 1 or 2 end,
        sysinfo=function() return {uptime=math.floor(w.time)} end,
        getuid=function() return w.uid or 0 end,getpid=function() return 42 end,
        open_flags=function(...) return table.concat({...},',') end}
    n.open=function(path,flags,mode)
        check(flags=='wronly,creat,excl' and mode=='600','cache created exclusive and 0600')
        if w.files[path] or w.fail_open then return nil end
        put(path,'')
        return {write=function(_,value)
            if w.fail_write then return nil end
            local part=value:sub(1,w.write_size or #value)
            w.files[path]=w.files[path]..part; w.stats[path].size=#w.files[path]; return #part
        end,close=function() return not w.fail_close end}
    end
    n.poll=function(_,timeout)
        check(timeout<=10,'bounded polling interval'); w.polls=w.polls+1
        if not w.freeze_time then w.time=w.time+timeout/1000 end
        if w.poll_error then return nil,5 end
        return w.stall and 0 or 1
    end
    n.socket=function(domain,kind)
        check(domain=='inet' and kind=='stream','IPv4 TCP only'); w.sockets=w.sockets+1
        local sock={nonblock=false,request='',part=0}
        function sock:setblocking(value) check(value==false,'socket is nonblocking'); self.nonblock=true; return not w.blocking_error end
        function sock:connect(host,port)
            check(self.nonblock,'nonblocking before connect')
            check(host=='127.0.0.1' and (port==cfg.api_port or port==18680),'loopback configured ports only')
            if w.connect_error then return nil,w.connect_error end; return true
        end
        function sock:getopt(level,opt) check(level=='socket' and opt=='error','connect checked via SO_ERROR'); return w.so_error or 0 end
        function sock:send(value)
            check(self.nonblock,'send cannot block')
            if w.send_zero then return 0 end
            if w.send_error then return nil,w.send_error end
            local part=value:sub(1,w.send_size or #value)
            self.request=self.request..part; w.requests[w.sockets]=self.request; return #part
        end
        function sock:recv(size)
            check(self.nonblock and size==8192,'bounded nonblocking recv')
            if w.recv_error then return nil,w.recv_error end
            self.part=self.part+1; return w.response and w.response[self.part] or ''
        end
        function sock:close() w.closed=w.closed+1; return true end
        return sock
    end
    local api=load_module('core_api',{nixio=n,['nixio.fs']=fs,['luci.jsonc']=json})
    local status=load_module('node_status',{nixio=n,['nixio.fs']=fs,['luci.jsonc']=json,core_api=api})
    local function response(value)
        local body=json.stringify(value)
        w.response={'HTTP/1.1 200 OK\r\nContent-Length: '..#body..'\r\n\r\n'..body}; return body
    end
    return w,cfg,api,status,put,response
end
local w,cfg,api,status,put,response=fixture()
local function framed(body,headers,statusline)
    return (statusline or 'HTTP/1.1 200 OK')..'\r\n'..(headers or 'Content-Length: '..#body)..'\r\n\r\n'..body
end
check(api.parse_response(framed('{}'),true)=='{}','valid length response')
check(api.parse_response(framed('2\r\n{}\r\n0\r\n\r\n','Transfer-Encoding: chunked'),false)=='{}','valid chunked response')
check(api.parse_response('HTTP/1.0 200 OK\r\n\r\n{}',true)=='{}','valid EOF response without headers')
local _,err=api.parse_response(framed('{','Content-Length: 2'),false)
check(err=='incomplete','incomplete length before EOF')
for _,raw in ipairs({
    framed('{}',nil,'HTTP/1.1 401 Unauthorized'),framed('{}',nil,'HTTP/1.1 500 Failure'),
    framed('{}',nil,'HTTP/1.1 302 Redirect'),framed('{}',nil,'HTTP/1.1 2000 BAD'),
    framed('{}','Content-Length: 2\r\nContent-Length: 2'),
    framed('{}','Content-Length: 2\r\nTransfer-Encoding: chunked'),
    framed('{}','Content-Length: -2'),framed('{}','Content-Length: 2x'),
    framed('{}','Transfer-Encoding: gzip'),framed('{}','Content-Encoding: gzip'),
    framed('{}',' Content-Length: 2'),framed('{}','X-Bad: hello\nInjected: yes'),
    framed('{}','Content-Length: 524289'),framed('{}','Content-Length: 1'),
    framed('{}','Content-Length: 3'),framed('2\r\n{}XX0\r\n\r\n','Transfer-Encoding: chunked'),
    framed('2junk\r\n{}\r\n0\r\n\r\n','Transfer-Encoding: chunked'),
    framed('2\r\n{}\r\n0\r\nX: y\r\n\r\n','Transfer-Encoding: chunked'),
    framed('2\r\n{}\r\n0\r\n','Transfer-Encoding: chunked'),
    framed('2\r\n{}\r\n0\r\n\r\nextra','Transfer-Encoding: chunked'),
    framed('{}','X-Large: '..string.rep('x',16384)),string.rep('x',1064961)
}) do check(not api.parse_response(raw,true),'malformed/non-success response rejected') end
check(api.encode_name('HK / 日本')=='HK%20%2F%20%E6%97%A5%E6%9C%AC','proxy paths percent-encode names')
response({ok=true}); w.send_size=11; w.connect_error=115
check(api.get(cfg,'/proxies').ok,'partial sends and async connect succeed')
check(w.closed==1,'successful request closes socket')
check(w.requests[1]:find('Authorization: Bearer test-only-secret\r\n',1,true),'authorization included')
check(w.requests[1]:find('GET /proxies HTTP/1.1',1,true)==1,'GET only')
local before=w.sockets
for _,path in ipairs({'http://example.com/proxies','/proxies/a/delay','/configs','/proxies/x?url=a','/proxies/x\r\nX: y','/proxies/%GG','/proxies/a%2Fdelay','/proxies/a%252Fdelay','/proxies/%2e%2e'}) do
    check(not api.get(cfg,path),'only allowlisted API paths')
end
check(w.sockets==before,'invalid requests never connect')
for _,alter in ipairs({function() w.stats[cfg.api_header].uid=1000 end,
    function() w.stats[cfg.api_header].modestr='rw-r--r--' end,
    function() w.stats[cfg.api_header].type='lnk' end,
    function() w.stats['/mock/data'].modestr='rwxrwxrwx' end,
    function() put(cfg.api_header,'Authorization: Bearer ok\nInjected: value\n') end,
    function() put(cfg.api_header,'X-Test: no-bearer\n') end}) do
    w,cfg,api,status,put,response=fixture(); alter()
    check(not api.get(cfg,'/proxies'),'unsafe authentication rejected'); check(w.sockets==0,'unsafe auth rejected before socket')
end
for _,failure in ipairs({'stall','send_zero','blocking_error','poll_error','parse_throw'}) do
    w,cfg,api,status,put,response=fixture(); response({ok=true}); w[failure]=true
    check(not api.get(cfg,'/proxies'),'bounded failure '..failure)
    check(w.closed==1 and w.polls<=512,'failure closes bounded socket '..failure)
end
w,cfg,api,status,put,response=fixture(); w.stall=true; w.freeze_time=true
check(not api.get(cfg,'/proxies'),'stalled clock still bounded'); check(w.polls==512,'step cap enforced')
w,cfg,api,status,put,response=fixture(); w.connect_error=115; w.so_error=111
check(not api.get(cfg,'/proxies'),'async connection error rejected'); check(w.closed==1,'connect error closes socket')
w,cfg,api,status,put,response=fixture(); response({ok=true}); w.recv_error=11
check(not api.get(cfg,'/proxies'),'repeated EAGAIN bounded'); check(w.closed==1,'EAGAIN timeout closes socket')
w,cfg,api,status,put,response=fixture()
check(api.probe(18680),'bounded loopback backend probe'); check(next(w.requests)==nil,'probe sends no bytes')
local function healthy(kind,ms)
    return {type=kind or 'Shadowsocks',server='MUST-NOT-LEAK',password='MUST-NOT-LEAK',extra={[cfg.health_url]={alive=true,history={{delay=ms or 25}}}}}
end
local function proxies()
    return {PORTAL={type='Selector',now='AUTO',all={'AUTO'}},AUTO={type='Fallback',now='HK test',all={'HK test','JP test'}},
        ['HK test']=healthy(),['JP test']=healthy('Trojan',42),DIRECT=healthy('Direct'),REJECT=healthy('Reject')}
end
local p=proxies(); local name,ms,path=status.resolve(p,cfg.health_url)
check(name=='HK test' and ms==25 and #path==3,'nested selection resolves actual node')
for _,bad in ipairs({'Direct','Compatible','Reject','RejectDrop','Pass','DNS'}) do
    p=proxies(); p['HK test']=healthy(bad); check(not status.resolve(p,cfg.health_url),'forbidden terminal type '..bad)
end
for _,bad in ipairs({'DIRECT','REJECT','COMPATIBLE','PASS','DNS'}) do
    p=proxies(); p.AUTO.now=bad; p.AUTO.all={bad}; p[bad]=healthy('Shadowsocks')
    check(not status.resolve(p,cfg.health_url),'forbidden terminal name '..bad)
end
for _,modify in ipairs({
    function(t) t.AUTO.now='PORTAL';t.AUTO.all={'PORTAL'} end,
    function(t) t.AUTO.now=nil end,
    function(t) t.AUTO.now='missing';t.AUTO.all={'missing'} end,
    function(t) t.AUTO.all={'other'} end,
    function(t) t['HK test'].extra[cfg.health_url].alive=false end,
    function(t) t['HK test'].extra[cfg.health_url].alive='true' end,
    function(t) t['HK test'].extra[cfg.health_url].history={{delay=25},{delay=0}} end,
    function(t) t['HK test'].extra[cfg.health_url].history={{delay='25'}} end,
    function(t) t['HK test'].extra={['https://wrong.example/']={alive=true,history={{delay=25}}}} end,
    function(t) t['HK test'].type='Fallback' end,
    function(t) t['HK test'].type=nil end,
    function(t) t['HK test'].all={} end
}) do p=proxies(); modify(p); check(not status.resolve(p,cfg.health_url),'invalid nested route rejected') end
p={PORTAL={type='Selector',now='g1'}}
for i=1,20 do p['g'..i]={type='Selector',now='g'..(i+1)} end
p.g21=healthy(); check(not status.resolve(p,cfg.health_url),'depth bound enforced')
p=proxies(); p['danger\27[31m']=healthy(); p['C1\194\155bad']=healthy(); p['spoof\226\128\174']=healthy()
response({proxies=p}); local snap=assert(status.collect(cfg))
check(snap.ready and snap.current.name=='HK test' and #snap.nodes==2,'collection excludes groups reserved and unsafe names')
check(snap.nodes[1].server==nil and snap.nodes[1].password==nil and snap.extra==nil,'snapshot allowlist excludes provider secrets')
check(status.write(cfg,snap),'cache write returns true')
local sockets=w.sockets; local read=assert(status.read(cfg))
check(read.current.name=='HK test' and #read.nodes==2,'cache round trip'); check(w.sockets==sockets,'cache read never opens sockets')
check(w.stats['/mock/run/nodes.json'].modestr=='rw-------','cache remains private')
local original=copy(snap)
for _,mutate in ipairs({function(t) t.nodes[1].name='bad\nname' end,
    function(t) t.current.name='bad\27name' end,
    function(t) t.current.path[2]='bad\tgroup' end,
    function(t) t.nodes[1].delay=0 end,
    function(t) t.updated_at=math.huge end}) do
    snap=copy(original); mutate(snap); local key='bad-cache'; w.objects[key]=snap; put('/mock/run/nodes.json',key)
    check(not status.read(cfg),'unsafe or inconsistent cached data rejected')
end
snap=copy(original); snap.nodes[1].server='MUST-NOT-LEAK'; snap.subscription='MUST-NOT-LEAK'; snap.current.password='MUST-NOT-LEAK'
w.objects.clean=snap; put('/mock/run/nodes.json','clean'); read=assert(status.read(cfg))
check(read.subscription==nil and read.nodes[1].server==nil and read.current.password==nil,'read reconstructs allowlisted fields')
for _,mode in ipairs({'fixed','preferred','auto'}) do
    cfg.selection_mode=mode;cfg.preferred_node='JP test'; response({proxies=proxies()});snap=assert(status.collect(cfg))
    check(snap.ready==(mode~='fixed'),'fixed mode actual-name equality '..mode)
    check(#snap.nodes==2,'all provider nodes available in every mode')
end
cfg.selection_mode='fixed';cfg.preferred_node='renamed';response({proxies=proxies()});snap=assert(status.collect(cfg))
check(not snap.ready and snap.preferred_missing,'missing fixed preference fails closed')
cfg.preferred_node='HK test';response({proxies=proxies()});snap=assert(status.collect(cfg)); check(snap.ready,'fixed exact terminal succeeds')
for _,failure in ipairs({'fail_open','fail_write','fail_close','fail_rename'}) do
    w[failure]=true; check(not status.write(cfg,snap),'cache failure visible '..failure); w[failure]=false
end
w.stats['/mock/run'].modestr='rwxrwxrwx';check(not status.write(cfg,snap),'unsafe cache directory rejected')
check(w.sockets>=sockets,'no hidden cache-related service or listener operation')
print('Passed '..count..' node API/status assertions (all sockets, files and services mocked)')
