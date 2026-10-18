-- Full listener regression tests. No real processes, sockets, service commands,
-- clocks, signals, or output files are used. Only the Lua source is read.
-- Run explicitly after authorizing tests: lua5.1 tests/lifecycle.lua
-- Also compatible with Lua 5.2+ / texlua. No production test seam is required.
local directory = arg[0]:match('^(.*)/') or '.'
local source = directory .. '/../src/'
local assertions, scenarios = 0, 0
local function check(value, message)
    assert(value, message)
    assertions = assertions + 1
end
local function equal(actual, expected, message)
    check(actual == expected, message .. ' (expected ' .. tostring(expected) .. ', got ' .. tostring(actual) .. ')')
end
local function copy(value)
    if type(value) ~= 'table' then return value end
    local out = {}; for k,v in pairs(value) do out[k] = copy(v) end; return out
end
local function word(n) return string.char(math.floor(n/256)%256,n%256) end
local function band(a,b)
    local result, bit = 0, 1
    while a > 0 or b > 0 do
        if a % 2 == 1 and b % 2 == 1 then result = result + bit end
        a, b, bit = math.floor(a/2), math.floor(b/2), bit*2
    end
    return result
end
local function load_sandboxed(path, environment)
    local chunk, err
    if setfenv then
        chunk, err = loadfile(path)
        if chunk then setfenv(chunk, environment) end
    else chunk, err = loadfile(path, 't', environment) end
    return assert(chunk, err)
end
local external_header = 'POST http://8.8.8.8/upload HTTP/1.1\r\nHost: 8.8.8.8\r\nContent-Length: %d\r\n\r\n'
local function external(body)
    body = body or ''; return external_header:format(#body) .. body
end
local local_request = 'GET http://192.168.50.9/hello HTTP/1.1\r\nHost: 192.168.50.9\r\n\r\n'
local response = 'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK'

local function run(spec)
    scenarios = scenarios + 1
    local w = {time=0, clients={}, sockets={}, jobs={}, connections={}, stops={}, kills={},
        statuses={}, events={}, fork_attempts=0, core_running=false, scenario=spec.name}
    local cfg = {run_dir='/mock/run', api_header='/mock/api-header', core_service='/mock/core',
        core_name='mock-core', api_port=19091, backend_port=18680, bind='192.168.50.2',
        port=18679, allowed_ip='192.168.50.30', local_dns='192.168.50.1',
        health_url='https://example.invalid/health', idle_seconds=spec.idle or 10,
        wakeup_timeout=spec.timeout or 60,selection_mode=spec.selection_mode or 'auto',preferred_node=spec.preferred_node or ''}
    local constants = {EAGAIN=11, EWOULDBLOCK=11, EINPROGRESS=115, ECONNREFUSED=111,
        EINTR=4, ECHILD=10, ESRCH=3, SIGTERM=15, SIGINT=2, SIGHUP=1, SIGPIPE=13, SIGKILL=9}
    local function event(kind, detail)
        w.events[#w.events+1] = {time=w.time, kind=kind, detail=detail}
    end
    local methods = {}
    local function socket(kind, options)
        local s = setmetatable({kind=kind, spec=options or {}, sent='', read_at=1,
            received=0, closed=false, shutdowns={}}, {__index=methods})
        w.sockets[#w.sockets+1] = s
        return s
    end
    function methods:setblocking() return true end
    function methods:listen() return true end
    function methods:close() self.closed=true; self.closed_at=w.time; return true end
    function methods:shutdown(direction) self.shutdowns[direction]=true; return true end
    function methods:accept()
        for _,c in ipairs(w.clients) do
            if not c.accepted and c.spec.at <= w.time then
                c.accepted=true; c.accepted_at=w.time; return c, cfg.allowed_ip
            end
        end
        return nil, constants.EAGAIN
    end
    function methods:connect(ip, port)
        self.ip, self.port, self.connected_at = ip, port, w.time
        self.kind = port == cfg.api_port and 'api' or (port == cfg.backend_port and 'backend' or 'local')
        local index=0
        for _,s in ipairs(w.connections) do if s.kind==self.kind then index=index+1 end end
        self.spec = copy((spec[self.kind .. '_connections'] or {})[index+1] or {})
        self.send_after = w.time + (self.spec.send_delay or 0)
        self.connect_after = w.time + (self.spec.connect_delay or 0)
        w.connections[#w.connections+1] = self
        if self.spec.connect_error then return nil, self.spec.connect_error end
        if self.spec.connect_delay then return nil, constants.EINPROGRESS end
        return true
    end
    function methods:getopt(level, option)
        assert(level=='socket' and option=='error', 'unexpected socket option')
        return self.spec.socket_error or 0
    end
    function methods:send(data)
        assert(not self.closed, 'send on closed fake socket')
        if self.spec.send_error then return nil, self.spec.send_error end
        if self.send_after and w.time < self.send_after then return nil, constants.EAGAIN end
        if self.spec.never_writable then return nil, constants.EAGAIN end
        local amount = math.min(#data, self.spec.send_limit or #data)
        self.sent = self.sent .. data:sub(1,amount)
        self.first_sent_at = self.first_sent_at or w.time; self.last_sent_at = w.time
        event('send', self.kind)
        return amount
    end
    local function readable(s)
        if s.kind=='dns' then return s.dns_response~=nil and not s.dns_returned end
        if s.kind=='client' then
            return s.read_at <= #s.spec.data or (s.spec.eof and not s.eof_returned)
        end
        if #s.sent >= (s.spec.expected_bytes or 1) and not s.spec.no_response then
            return not s.eof_returned
        end
        return false
    end
    function methods:recv(limit)
        assert(not self.closed, 'recv on closed fake socket')
        if self.spec.recv_error then return nil, self.spec.recv_error end
        if not readable(self) then return nil, constants.EAGAIN end
        local data = self.kind=='client' and self.spec.data or (self.spec.response or response)
        if self.kind=='api' then
            assert(self.sent:find('GET /proxies HTTP/1.1',1,true)==1,'child uses only read-only proxy map endpoint')
            local body='{"mock-proxies":true}'
            data='HTTP/1.1 200 OK\r\nContent-Length: '..#body..'\r\n\r\n'..body
        end
        if self.read_at > #data then self.eof_returned=true; return '' end
        local result = data:sub(self.read_at, self.read_at+limit-1)
        self.read_at=self.read_at+#result; self.received=self.received+#result
        if self.kind=='client' and #w.jobs>0 and not w.jobs[1].reaped then
            self.read_before_startup=self.received
        end
        return result
    end
    function methods:sendto(packet, ip, port)
        equal(ip,cfg.local_dns,'DNS uses configured resolver')
        equal(port,53,'DNS uses expected port')
        w.dns_queries=(w.dns_queries or 0)+1
        local answers={}
        for _,answer in ipairs(assert(spec.dns,'unexpected DNS query')) do
            local bytes={}; for octet in answer:gmatch('%d+') do bytes[#bytes+1]=tonumber(octet) end
            answers[#answers+1]='\192\12'..word(1)..word(1)..word(0)..word(60)..word(4)..string.char((unpack or table.unpack)(bytes))
        end
        self.dns_response=packet:sub(1,2)..word(33152)..word(1)..word(#answers)..word(0)..word(0)..packet:sub(13)..table.concat(answers)
        return #packet
    end
    function methods:recvfrom()
        self.dns_returned=true; return self.dns_response,cfg.local_dns,53
    end
    for _,client in ipairs(spec.clients) do w.clients[#w.clients+1]=socket('client',copy(client)) end
    local listener=socket('listener')
    local STOP, CHILD_EXIT={}, {}
    local n = {const=constants, bit={band=band}}
    function n.umask() return true end
    function n.signal() return true end
    function n.getuid() return 0 end
    function n.getpid() return w.child_started_at and 901 or 900 end
    function n.getppid() return spec.parent_lost_at and w.time>=spec.parent_lost_at and 1 or 900 end
    function n.setsid() w.session_created=true; return not spec.setsid_failure end
    function n.nanosleep(seconds, nanoseconds)
        w.time=w.time+seconds+nanoseconds/1000000000
        assert(w.time<=spec.until_time,'mock child exceeded its execution budget')
        return true
    end
    function n.sysinfo() return {uptime=w.time} end
    function n.poll_flags(flag) return assert(({['in']=1,out=2,err=4,hup=8})[flag]) end
    function n.bind() return listener end
    function n.socket(_,kind)
        assert(kind=='stream' or kind=='dgram', 'unexpected socket kind')
        w.allocations=(w.allocations or 0)+1
        if spec.fail_socket_at==w.allocations then return nil, 24 end
        return socket(kind=='dgram' and 'dns' or 'unconnected')
    end
    function n.fork()
        w.fork_attempts=w.fork_attempts+1
        if spec.child then
            w.child_started_at=w.time
            if spec.child_existing_core then w.core_running=true end
            return 0
        end
        local job_spec=assert((spec.jobs or {})[w.fork_attempts], 'unexpected startup attempt')
        if job_spec.fork_error then return nil, constants.EAGAIN end
        local job={pid=1000+w.fork_attempts, spec=job_spec, began=w.time,
            ready_at=w.time+(job_spec.delay or 0)}
        w.jobs[#w.jobs+1]=job; w.core_running=job_spec.leaves_core~=false
        event('fork',job.pid); return job.pid
    end
    function n.kill(pid, signal)
        equal(signal,constants.SIGKILL,'startup timeout must kill the worker')
        for _,job in ipairs(w.jobs) do
            if job.pid==math.abs(pid) then
                job.killed_at=w.time; w.kills[#w.kills+1]={pid=pid,time=w.time}
                event('kill',pid); return true
            end
        end
        error('killed an unknown mock worker')
    end
    function n.waitpid(pid, mode)
        equal(mode,'nohang','listener must reap without blocking')
        for _,job in ipairs(w.jobs) do
            if job.pid==pid then
                assert(not job.reaped,'worker reaped twice')
                if job.spec.wait_interrupt_at and not job.interrupted and w.time>=job.began+job.spec.wait_interrupt_at then
                    job.interrupted=true; return nil,constants.EINTR
                end
                if job.spec.wait_error and w.time>=job.began+(job.spec.error_delay or 0) then
                    job.reaped=true; job.reaped_at=w.time
                    return nil, job.spec.wait_error
                end
                if job.killed_at then
                    if w.time < job.killed_at+(job.spec.reap_delay or 0) then return 0 end
                    job.reaped=true; job.reaped_at=w.time; event('reap',pid)
                    return pid,'signaled',constants.SIGKILL
                end
                if w.time<job.ready_at then return 0 end
                job.reaped=true; job.reaped_at=w.time; event('reap',pid)
                if job.spec.signal then return pid,'signaled',job.spec.signal end
                return pid,'exited',job.spec.success==false and 1 or 0
            end
        end
        error('waited on an unknown mock worker')
    end
    function n.poll(fds, milliseconds)
        w.time=w.time+milliseconds/1000
        if w.time > spec.until_time then error(STOP,0) end
        local ready=0
        for _,p in ipairs(fds) do
            p.revents=0
            if p.fd.kind=='listener' then
                for _,c in ipairs(w.clients) do
                    if not c.accepted and c.spec.at<=w.time then p.revents=1; break end
                end
            elseif not p.fd.closed then
                if band(p.events,1)~=0 and readable(p.fd) then p.revents=p.revents+1 end
                if band(p.events,2)~=0 and (not p.fd.connect_after or w.time>=p.fd.connect_after) then
                    p.revents=p.revents+2
                end
            end
            if p.revents~=0 then ready=ready+1 end
        end
        return ready
    end
    local memory_files={[cfg.api_header]='Authorization: Bearer fake-test-only\n'}
    function n.open_flags(...) return table.concat({...},',') end
    function n.open(path,flags,mode)
        equal(flags,'wronly,creat,excl','cache uses exclusive creation')
        equal(mode,'600','cache mode is private before writing')
        if memory_files[path] then return nil end
        memory_files[path]=''
        return {write=function(_,data) memory_files[path]=memory_files[path]..data; return #data end,close=function() return true end}
    end
    local function process_stat(pid,group)
        local fields={'S','1',tostring(group)}
        for i=4,19 do fields[i]='0' end
        fields[20]=tostring(pid)..'00'
        return pid..' (mock lua) '..table.concat(fields,' ')..'\n'
    end
    local fs = {
        readfile=function(path,limit)
            if path=='mock-policy' then return 'mock-json' end
            if path=='/proc/900/stat' then
                if w.child_started_at and spec.parent_lost_at and w.time>=spec.parent_lost_at then return nil end
                return process_stat(900,900)
            end
            if path=='/proc/901/stat' and w.child_started_at then return process_stat(901,w.session_created and 901 or 900) end
            local value=memory_files[path]; return value and (limit and value:sub(1,limit) or value)
        end,
        lstat=function(path)
            if path=='/mock' or path==cfg.run_dir then return {type='dir',uid=0,modestr='rwx------',size=0} end
            if memory_files[path] then return {type='reg',uid=0,modestr='rw-------',size=#memory_files[path]} end
        end,
        stat=function(path) return memory_files[path] and {size=#memory_files[path]} or nil end,
        writefile=function(path,data) memory_files[path]=data; return true end,
        remove=function(path) memory_files[path]=nil; return true end,
        rename=function(a,b) memory_files[b]=memory_files[a]; memory_files[a]=nil; return true end}
    local sys = {call=function(command)
        if command==cfg.core_service..' start >/dev/null 2>&1' then
            assert(spec.child,'blocking service start ran in parent listener')
            w.starts=(w.starts or 0)+1; w.core_running=true; return spec.service_start_error or 0
        end
        assert(command==cfg.core_service..' stop >/dev/null 2>&1',
            'blocking service start ran in listener instead of startup child')
        w.stops[#w.stops+1]=w.time; w.core_running=false; event('stop'); return 0
    end}
    local json = {parse=function(value)
            if value=='{"mock-proxies":true}' then
                w.health_queries=(w.health_queries or 0)+1
                local terminal={type=spec.child_type or 'Shadowsocks',extra={[cfg.health_url]={alive=spec.child_healthy~=false,history={{delay=spec.child_delay or 1}}}}}
                return {proxies=spec.child_proxies or {PORTAL={type='Selector',now='AUTO',all={'AUTO'}},
                    AUTO={type='Fallback',now='mock-route',all={'mock-route'}},['mock-route']=terminal}}
            end
            equal(value,'mock-json','parse mock policy'); return cfg
        end,
        stringify=function(value)
            if value.version==1 then w.node_snapshot=copy(value); return '{"mock-cache":true}' end
            w.statuses[#w.statuses+1]=copy(value); return 'mock-status'
        end}
    local util = {ubus=function(_,_,_) return {[cfg.core_name]={instances={main={running=w.core_running,pid=2000}}}} end}
    local environment = {assert=assert,error=error,ipairs=ipairs,pairs=pairs,next=next,pcall=pcall,
        select=select,tonumber=tonumber,tostring=tostring,type=type,math=math,string=string,
        table=table,unpack=unpack or table.unpack,debug={traceback=debug.traceback},
        arg={[0]=source..'ondemand.lua',[1]='mock-policy'},package={path=''}}
    environment._G=environment
    environment.xpcall=function(fn, handler)
        local ok,err=xpcall(fn,function(e) if e==STOP or e==CHILD_EXIT then return e end; return handler(e) end)
        if not ok and (err==STOP or err==CHILD_EXIT) then return true end
        return ok,err
    end
    environment.io={open=function(path,mode)
        if path==cfg.api_header and mode=='r' then
            return {read=function() return 'Authorization: Bearer fake-test-only' end,close=function() return true end}
        end
        assert(path:sub(1,9)=='/mock/run','unexpected mock file: '..path)
        assert(mode=='a' or mode=='w','unexpected mock file mode')
        return {write=function(_,...) return true end,close=function() return true end}
    end}
    environment.os={time=function() return 1700000000+math.floor(w.time) end,date=function() return 'mock-time' end,rename=function() return true end,
        exit=function(code)
            if spec.child and w.child_started_at then w.child_exit=code; error(CHILD_EXIT,0) end
            error(spec.name..': launcher unexpectedly exited with '..tostring(code),0)
        end}
    local modules={nixio=n,['nixio.fs']=fs,['luci.jsonc']=json,['luci.util']=util,['luci.sys']=sys}
    environment.require=function(name)
        if modules[name] then return modules[name] end
        assert(name=='protocol' or name=='lifecycle' or name=='dns' or name=='startup_owner' or name=='core_api' or name=='node_status','unmocked module: '..name)
        modules[name]=load_sandboxed(source..name..'.lua',environment)(); return modules[name]
    end
    load_sandboxed(source..'ondemand.lua',environment)()
    w.listener=listener
    equal(w.stops[1],0,spec.name..': listener initially stops core')
    return w
end

local body=string.rep('pending-body-',32768)
local request=external(body)
local slow=run{name='slow startup, LAN concurrency, buffering, idle',timeout=60,idle=10,until_time=90,
    jobs={{delay=45}},clients={{at=0,data=request},{at=2,data=local_request,eof=true}},
    backend_connections={{send_delay=5,expected_bytes=#request}}}
equal(slow.fork_attempts,1,'concurrent traffic must not duplicate startup')
equal(#slow.connections,2,'LAN and backend both connected')
local lan, backend
for _,s in ipairs(slow.connections) do if s.kind=='local' then lan=s else backend=s end end
check(lan.first_sent_at<5,'LAN forwards while startup is still waiting')
check(slow.clients[2].first_sent_at<5,'LAN response arrives during slow startup')
equal(slow.clients[2].sent,response,'complete LAN response is relayed')
check(backend.connected_at>=45,'backend is not connected before readiness completes')
check(slow.clients[1].read_before_startup<=262144+8192,'waiting input applies bounded backpressure')
check(slow.clients[1].read_before_startup<#request,'large pending request is not consumed without bound')
equal(backend.sent,request,'pending first request and body are preserved exactly')
equal(slow.clients[1].sent,response,'first external response survives slow startup and send delay')
equal(#slow.stops,2,'core stops once after first request finishes')
check(slow.stops[2]>=backend.last_sent_at+10,'startup duration does not consume request idle budget')
check(slow.stops[2]>backend.connected_at+5,'first write gets a fresh idle budget after readiness')

local retry=run{name='startup failure then retry',until_time=20,jobs={{delay=1,success=false},{delay=1}},
    clients={{at=0,data=external()},{at=4,data=external()}}}
check(retry.clients[1].sent:find('503 Service Unavailable',1,true)~=nil,'failed startup responds 503')
equal(retry.fork_attempts,2,'next request retries a failed startup')
equal(retry.clients[2].sent,response,'retry succeeds')
check(retry.jobs[1].reaped and retry.jobs[2].reaped,'both startup workers reaped')

local timeout=run{name='timeout, delayed reap, then retry',timeout=2,until_time=20,
    jobs={{delay=100,reap_delay=3},{delay=0.5}},
    clients={{at=0,data=external()},{at=3,data=external()},{at=7,data=external()},{at=1,data=local_request}}}
equal(#timeout.kills,2,'timed-out worker group and PID are each killed once')
check(timeout.kills[1].pid<0 and timeout.kills[2].pid>0,'timeout cancels process group and worker')
check(timeout.kills[1].time>=2,'startup timeout deadline honored')
check(timeout.clients[1].sent:find('503 Service Unavailable',1,true)~=nil,'waiting client fails on timeout')
check(timeout.clients[2].sent:find('503 Service Unavailable',1,true)~=nil,'new client fails while killed worker is unreaped')
equal(timeout.clients[3].sent,response,'request can retry after timed-out worker is reaped')
equal(timeout.clients[4].sent,response,'LAN stays available during timed-out startup')
equal(timeout.fork_attempts,2,'no replacement worker starts before reap')
check(timeout.jobs[2].began>=timeout.jobs[1].reaped_at,'retry follows worker reap')

local signaled=run{name='unexpected worker signal retires descendants',until_time=20,
    jobs={{delay=1,signal=15},{delay=0.5}},clients={{at=0,data=external()},{at=4,data=external()}}}
check(signaled.clients[1].sent:find('503 Service Unavailable',1,true)~=nil,'signaled startup fails pending request')
equal(#signaled.kills,1,'signaled worker descendant group is canceled once')
check(signaled.kills[1].pid<0,'after reap only owned group is signaled, not a possibly reused direct PID')
equal(signaled.fork_attempts,2,'signaled worker permits a later retry')
equal(signaled.clients[2].sent,response,'retry after signaled worker succeeds')

local missing=run{name='waitpid ECHILD is terminal',until_time=18,
    jobs={{delay=100,wait_error=10,error_delay=1},{delay=0.5}},
    clients={{at=0,data=external()},{at=4,data=external()}}}
check(missing.clients[1].sent:find('503 Service Unavailable',1,true)~=nil,'waitpid failure does not strand first request')
equal(missing.clients[2].sent,response,'waitpid failure does not wedge future retries')

local interrupted=run{name='waitpid EINTR is retried',until_time=16,
    jobs={{delay=1,wait_interrupt_at=0.25}},clients={{at=0,data=external()}}}
equal(interrupted.fork_attempts,1,'interrupted wait does not duplicate startup')
check(interrupted.jobs[1].interrupted and interrupted.jobs[1].reaped,'interrupted wait eventually reaps worker')
equal(interrupted.clients[1].sent,response,'interrupted wait preserves pending request')

local fork=run{name='fork failure then retry',until_time=18,
    jobs={{fork_error=true},{delay=0.5}},clients={{at=0,data=external()},{at=3,data=external()}}}
check(fork.clients[1].sent:find('503 Service Unavailable',1,true)~=nil,'fork failure responds 503')
equal(fork.clients[2].sent,response,'fork failure allows retry')

local connect=run{name='backend refusal still cleans core',until_time=18,jobs={{delay=0.5}},
    backend_connections={{connect_error=111}},clients={{at=0,data=external()}}}
check(connect.clients[1].sent:find('503 Service Unavailable',1,true)~=nil,'backend refusal responds 503')
equal(#connect.stops,2,'backend refusal retains ownership for idle cleanup')

local partial=run{name='partial sends preserve bytes',until_time=18,jobs={{delay=0.5}},
    backend_connections={{send_limit=19,expected_bytes=#external('payload')}},
    clients={{at=0,data=external('payload'),send_limit=13}}}
equal(partial.connections[1].sent,external('payload'),'partial backend writes preserve request bytes')
equal(partial.clients[1].sent,response,'partial client writes preserve response bytes')

local stalled=run{name='stalled buffer eventually idles',until_time=20,jobs={{delay=0.5}},
    backend_connections={{never_writable=true}},clients={{at=0,data=external()}}}
equal(stalled.connections[1].sent,'','blocked backend accepts no bytes')
equal(#stalled.stops,2,'buffered bytes cannot defeat idle cleanup forever')
check(stalled.clients[1].closed,'idle cleanup closes stalled external client')

local access=run{name='denied destinations and private direct',until_time=8,jobs={},dns={'127.0.0.1'},
    clients={{at=0,data='GET http://127.0.0.1/ HTTP/1.1\r\n\r\n'},
        {at=1,data='GET http://blocked.example/ HTTP/1.1\r\n\r\n'},
        {at=2,data=local_request},{at=3,data='GET http://blocked.example/ HTTP/1.1\r\n\r\n'}}}
equal(access.fork_attempts,0,'denied and LAN requests never start backend')
equal(#access.connections,1,'only approved private destination is connected')
equal(access.connections[1].ip,'192.168.50.9','private literal connects directly')
for _,i in ipairs({1,2,4}) do check(access.clients[i].sent:find('403 Forbidden',1,true)~=nil,'denied destination returns403') end
equal(access.dns_queries,1,'DNS denial is cached')
equal(access.clients[3].sent,response,'denied requests do not interrupt LAN traffic')

local private_dns=run{name='private DNS is pinned to address',until_time=5,jobs={},dns={'192.168.50.9'},
    clients={{at=0,data='GET http://printer.lan/hello HTTP/1.1\r\nHost: printer.lan\r\n\r\n'}}}
equal(private_dns.fork_attempts,0,'approved private DNS never wakes backend')
equal(private_dns.connections[1].ip,'192.168.50.9','private DNS connection pins approved numeric address')
check(private_dns.connections[1].sent:find('GET /hello HTTP/1.1',1,true)==1,'private DNS request uses origin form')
equal(private_dns.clients[1].sent,response,'private DNS response is relayed')

local async_failure=run{name='asynchronous backend refusal retries readiness',until_time=20,
    jobs={{delay=0.5},{delay=0.5}},backend_connections={{connect_delay=0.25,socket_error=111},{}},
    clients={{at=0,data=external()},{at=4,data=external()}}}
check(async_failure.clients[1].sent:find('502 Bad Gateway',1,true)~=nil,'asynchronous backend refusal returns502')
equal(async_failure.fork_attempts,2,'asynchronous backend refusal invalidates readiness for next request')
equal(async_failure.clients[2].sent,response,'retry after asynchronous backend refusal succeeds')

local connect_timeout=run{name='backend connect timeout retries readiness',until_time=25,
    jobs={{delay=0.5},{delay=0.5}},backend_connections={{connect_delay=100},{}},
    clients={{at=0,data=external()},{at=8,data=external()}}}
check(connect_timeout.clients[1].sent:find('504 Gateway Timeout',1,true)~=nil,'backend connection timeout returns504')
equal(connect_timeout.fork_attempts,2,'backend connect timeout invalidates readiness for next request')
equal(connect_timeout.clients[2].sent,response,'retry after backend connect timeout succeeds')

local invalidation=run{name='old connection cannot erase active startup deadline',timeout=10,until_time=26,
    jobs={{delay=0.5},{delay=100}},
    backend_connections={{connect_delay=1,socket_error=111},{connect_delay=100}},
    clients={{at=0,data=external()},{at=1,data=external()},{at=3,data=external()},{at=7,data=external()}}}
check(invalidation.clients[1].sent:find('502 Bad Gateway',1,true)~=nil,'first old connection fails before restart')
check(invalidation.clients[2].sent:find('504 Gateway Timeout',1,true)~=nil,'second old connection times out during restart')
equal(invalidation.fork_attempts,2,'old connection failure cannot create duplicate startup workers')
check(invalidation.clients[3].sent:find('503 Service Unavailable',1,true)~=nil,'restart pending client fails at preserved startup deadline')
check(invalidation.clients[4].sent:find('503 Service Unavailable',1,true)~=nil,'new request shares same bounded startup')
equal(#invalidation.kills,2,'active restart worker group and PID still get timeout cancellation')
check(invalidation.kills[1].time>=invalidation.jobs[2].began+10 and
    invalidation.kills[1].time<=invalidation.jobs[2].began+10.25,'old connection cannot erase restart deadline')

local allocation=run{name='LAN socket allocation failure is contained',until_time=6,jobs={},fail_socket_at=1,
    clients={{at=0,data=local_request},{at=2,data=local_request}}}
check(allocation.clients[1].sent:find('502 Bad Gateway',1,true)~=nil,'LAN allocation failure returns502')
equal(allocation.clients[2].sent,response,'listener survives LAN allocation failure')
equal(allocation.fork_attempts,0,'LAN allocation failure never starts backend')

local child=run{name='real child readiness and descriptor cleanup',child=true,until_time=10,
    clients={{at=0,data=local_request},{at=2,data=external()}}}
equal(child.child_exit,0,'healthy child exits successfully')
equal(child.starts,1,'cold child requests exactly one service start')
check(child.session_created,'child creates its own process group')
check(child.listener.closed,'child closes inherited listener')
check(child.clients[1].closed and child.clients[2].closed,'child closes all inherited clients')
check(child.connections[1].closed,'child closes inherited LAN upstream')
check((child.health_queries or 0)>0,'child checks selected route health')
check(child.node_snapshot and child.node_snapshot.current.name=='mock-route','readiness child publishes actual node snapshot')
equal(#child.node_snapshot.current.path,3,'readiness walks nested groups')

local orphan=run{name='child checks parent before service start',child=true,parent_lost_at=0,until_time=5,
    clients={{at=0,data=external()}}}
equal(orphan.child_exit,1,'orphaned child fails readiness')
equal(orphan.starts,nil,'orphaned child never starts service')

local existing=run{name='existing core still requires healthy route',child=true,child_existing_core=true,
    child_healthy=false,timeout=2,until_time=10,clients={{at=0,data=external()}}}
equal(existing.child_exit,1,'unhealthy existing core cannot satisfy readiness')
equal(existing.starts,nil,'existing core is not redundantly started')
check((existing.health_queries or 0)>0,'existing core route health is checked')
check(existing.node_snapshot and not existing.node_snapshot.ready and #existing.node_snapshot.nodes==1,'unhealthy first wake caches node names without releasing readiness')
check(existing.time>=existing.child_started_at+2,'unhealthy child actually exhausts readiness timeout')

local lost=run{name='old child exits without stopping successor core',child=true,parent_lost_at=1.5,
    child_healthy=false,timeout=5,until_time=10,clients={{at=0,data=external()}}}
equal(lost.child_exit,1,'child fails after parent disappears')
equal(lost.starts,1,'child started service before parent disappeared')
equal(#lost.stops,1,'orphaned worker cannot stop a successor core')

for _,kind in ipairs({'Direct','Compatible','Reject','Pass','DNS'}) do
    local rejected=run{name='child rejects reserved terminal type '..kind,child=true,child_type=kind,timeout=1,until_time=5,
        clients={{at=0,data=external()}}}
    equal(rejected.child_exit,1,'special terminal never satisfies readiness: '..kind)
    check(rejected.node_snapshot and not rejected.node_snapshot.ready,'failed readiness caches only unready state')
end
local wrong_fixed=run{name='fixed mode rejects different healthy terminal',child=true,selection_mode='fixed',preferred_node='another-node',
    timeout=1,until_time=5,clients={{at=0,data=external()}}}
equal(wrong_fixed.child_exit,1,'fixed actual-name mismatch fails closed')
check(wrong_fixed.node_snapshot and not wrong_fixed.node_snapshot.ready,'wrong fixed route cache is marked unready')
check(#wrong_fixed.node_snapshot.nodes==1,'missing fixed preference still caches replacement choices')
local fixed=run{name='fixed mode resolves exact healthy terminal',child=true,selection_mode='fixed',preferred_node='mock-route',
    timeout=1,until_time=5,clients={{at=0,data=external()}}}
equal(fixed.child_exit,0,'exact fixed actual node passes readiness')
local latest_failed=run{name='zero latest delay is not ready',child=true,child_delay=0,timeout=1,until_time=5,
    clients={{at=0,data=external()}}}
equal(latest_failed.child_exit,1,'zero latest delay fails closed')

print('Passed '..assertions..' listener assertions across '..scenarios..' mocked scenarios')
