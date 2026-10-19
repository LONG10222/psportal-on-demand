local n = require 'nixio'
local fs = require 'nixio.fs'
local json = require 'luci.jsonc'
local util = require 'luci.util'
local sys = require 'luci.sys'
local directory = arg[0]:match('^(.*)/') or '.'
package.path = directory .. '/?.lua;' .. package.path
local protocol = require 'protocol'
local lifecycle = require 'lifecycle'
local dns = require 'dns'
local ownership = require 'startup_owner'
local core_api = require 'core_api'
local node_status = require 'node_status'
local policy_path = assert(arg[1], 'policy required')
local cfg = assert(json.parse(assert(fs.readfile(policy_path))), 'Invalid policy')
local linked = cfg.core_mode == 'openclash'
n.umask('077')
n.signal(n.const.SIGTERM, 'dfl')
n.signal(n.const.SIGINT, 'dfl')
n.signal(n.const.SIGHUP, 'dfl')
n.signal(n.const.SIGPIPE, 'ign')
local IN, OUT, ERR, HUP = n.poll_flags('in'), n.poll_flags('out'), n.poll_flags('err'), n.poll_flags('hup')
local band = n.bit.band
local sessions, cache = {}, {}
local core_on, last_external, last_save = false, 0, 0
local life = lifecycle.new(cfg.wakeup_timeout or 12, cfg.idle_seconds)
local startup_pid, startup_killed, startup_generation, generation, server
local counters = {external_requests=0, local_requests=0, denied_clients=0, starts=0, idle_stops=0}
local function now() return n.sysinfo().uptime end
local function log(msg)
    local f = io.open(cfg.run_dir .. '/events.log', 'a')
    if f then f:write(os.date('!%Y-%m-%dT%H:%M:%SZ'), ' ', msg, '\n'); f:close() end
end
local function core_pid()
    local t = util.ubus('service', 'list', {name=cfg.core_name}) or {}
    local i = t[cfg.core_name] and t[cfg.core_name].instances
    if linked and type(i)=='table' then
        for _,instance in pairs(i) do
            if type(instance)=='table' and instance.running then return instance.pid end
        end
        return nil
    end
    return i and i.main and i.main.running and i.main.pid or nil
end
local function save(reason)
    local ext, lan = 0, 0
    for _,s in ipairs(sessions) do
        if not s.dead and s.kind == 'external' then ext=ext+1 end
        if not s.dead and s.kind == 'local' then lan=lan+1 end
    end
    local t = {launcher_pid=n.getpid(), core_mode=linked and 'openclash' or 'standalone',
        session_active=core_on, core_managed=not linked,core_running=(linked or core_on) and core_pid()~=nil,
        core_pid=(linked or core_on) and core_pid() or nil, core_starting=startup_pid~=nil, idle_timeout=cfg.idle_seconds,
        idle_seconds=core_on and math.max(0,now()-last_external) or 0,
        external_connections=ext, local_connections=lan, reason=reason,
        counters=counters, allowed_ip=cfg.allowed_ip, port=cfg.port}
    local f=assert(io.open(cfg.run_dir..'/status.json.new','w')); f:write(json.stringify(t)); f:close()
    assert(os.rename(cfg.run_dir..'/status.json.new',cfg.run_dir..'/status.json'))
    last_save=now()
end
local function close_session(s)
    if s.dead then return end
    s.dead=true
    if s.c then s.c:close() end
    if s.u then s.u:close() end
end
local function kill_startup()
    if not startup_pid then return end
    -- The readiness worker owns a process group, including its service shell.
    n.kill(-startup_pid,n.const.SIGKILL)
    n.kill(startup_pid,n.const.SIGKILL)
    startup_killed=true
end
local function stop_core(reason)
    kill_startup()
    for _,s in ipairs(sessions) do if s.kind=='external' then close_session(s) end end
    if not linked then sys.call(cfg.core_service..' stop >/dev/null 2>&1') end
    core_on=false
    lifecycle.complete(life,now(),false)
    if reason=='idle' then counters.idle_stops=counters.idle_stops+1 end
    log((linked and 'linked_sessions_closed reason=' or 'core_off reason=')..reason..' external_idle_seconds='..tostring(last_external>0 and now()-last_external or 0))
    save(reason)
end
local function route_ready(owner)
    local snapshot=node_status.collect(cfg)
    if not snapshot or not ownership.valid(cfg,owner) then return false end
    -- Readiness children alone refresh automatically. Cached CLI reads and
    -- explicit controller reads never renew the listener's external idle timer.
    if not node_status.write(cfg,snapshot) and not linked then return false end
    return snapshot.ready and ownership.valid(cfg,owner)
end
-- This function runs only in the readiness child. It may block on procd/API.
local function await_core(owner)
    if not ownership.valid(cfg,owner) then return false end
    local cold=not core_pid()
    if not linked and cold and sys.call(cfg.core_service..' start >/dev/null 2>&1')~=0 then return false end
    local deadline=now()+(cfg.wakeup_timeout or 12)
    while now()<deadline do
        if not ownership.valid(cfg,owner) then return false end
        local connected=core_api.probe(cfg.backend_port,{timeout_ms=500})
        if connected and route_ready(owner) then return ownership.valid(cfg,owner) end
        n.nanosleep(0,100000000)
    end
    return false
end
local function launch_startup()
    local owner=generation
    if not ownership.valid(cfg,owner) then return false end
    local pid=n.fork()
    if not pid then return false end
    if pid==0 then
        if not n.setsid() or not ownership.register(cfg,owner) then os.exit(1) end
        -- Never keep listener/client descriptors alive in a worker.
        if server then server:close() end
        for _,s in ipairs(sessions) do
            if s.c then s.c:close() end
            if s.u then s.u:close() end
        end
        local ok,ready=pcall(await_core,owner)
        os.exit(ok and ready and 0 or 1)
    end
    startup_pid=pid; startup_killed=false; startup_generation=owner
    counters.starts=counters.starts+1
    log(linked and 'linked_readiness external_request' or 'core_start external_request')
    return true
end
local function word(v) return string.char(math.floor(v/256)%256,v%256) end
local function resolve_private(host)
    local hit=cache[host]; if hit and hit.until_at>now() then return hit.ip,hit.denied end
    if not host:match('^[%w%.%-]+$') or #host>253 then return nil end
    local q=''
    for label in host:gmatch('[^.]+') do if #label>63 then return nil end; q=q..string.char(#label)..label end
    local id=math.random(1,65535)
    local question=q..'\0'..word(1)..word(1)
    local packet=word(id)..word(256)..word(1)..word(0)..word(0)..word(0)..question
    local s=n.socket('inet','dgram'); if not s then return nil end
    s:setblocking(false)
    s:sendto(packet,cfg.local_dns,53)
    local fds={{fd=s,events=IN}}; local count=n.poll(fds,200)
    local data,peer,port
    if count and count>0 then data,peer,port=s:recvfrom(4096) end
    s:close()
    local chosen,denied=nil,false
    if data and peer==cfg.local_dns and port==53 then
        chosen,denied=dns.parse_response(data,id,question,linked and host:find('.',1,true)~=nil and not host:match('%.lan$') and not host:match('%.local$'))
    end
    local size=0; for _ in pairs(cache) do size=size+1 end
    if size>256 then cache={} end
    cache[host]={ip=chosen,denied=denied,until_at=now()+60}
    return chosen,denied
end
local parse_request = protocol.parse_request
local function error_reply(s,code)
    if s.kind=='external' and s.connecting and not startup_pid then lifecycle.complete(life,now(),false) end
    if s.u then s.u:close(); s.u=nil end
    s.connecting=false; s.waiting=false; s.header=nil
    s.reply='HTTP/1.1 '..code..'\r\nConnection: close\r\nContent-Length: 0\r\n\r\n'
    s.c2u=''; s.u2c=s.reply; s.close_after_write=true; s.c_eof=true; s.u_eof=true
end
local function connect_backend(s)
    s.waiting=false
    s.u=n.socket('inet','stream')
    if not s.u then error_reply(s,'503 Service Unavailable'); return end
    s.u:setblocking(false)
    local ok,err=s.u:connect('127.0.0.1',cfg.backend_port)
    if not ok and err~=n.const.EINPROGRESS and err~=n.const.EAGAIN then
        lifecycle.complete(life,now(),false)
        error_reply(s,'503 Service Unavailable'); return
    end
    s.connecting=not ok; s.connect_deadline=now()+5
    last_external=now(); lifecycle.active(life,last_external)
end
local function advance_startup()
    if not startup_pid then return end
    if lifecycle.expired(life,now()) and not startup_killed then
        kill_startup()
        for _,s in ipairs(sessions) do if s.waiting and not s.dead then error_reply(s,'503 Service Unavailable') end end
    end
    local pid,status,code=n.waitpid(startup_pid,'nohang')
    if pid==0 then return end
    if not pid and status==n.const.EINTR then return end
    -- ECHILD or another wait failure is terminal, never strand pending clients.
    local ready=pid and not startup_killed and status=='exited' and code==0
    if pid and status=='signaled' and not startup_killed then
        -- Retire a surviving service shell when the readiness leader died.
        n.kill(-startup_pid,n.const.SIGKILL)
    end
    ownership.clear(cfg,startup_generation,startup_pid)
    startup_pid=nil; startup_killed=false; startup_generation=nil
    lifecycle.complete(life,now(),ready)
    core_on=true -- Even a failed start may have left a core running: idle cleanup still applies.
    last_external=now()
    for _,s in ipairs(sessions) do
        if s.waiting and not s.dead then
            if ready then connect_backend(s) else error_reply(s,'503 Service Unavailable') end
        end
    end
    save(ready and 'active' or 'core_start_failed')
end
local function start_request(s)
    local a,b=s.header:find('\r\n\r\n',1,true); if not a then return end
    local header,rest=s.header:sub(1,b),s.header:sub(b+1)
    local r=parse_request(header)
    if not r then error_reply(s,'400 Bad Request'); return end
    local ip,denied
    local route=protocol.destination(r.host)
    if route=='deny' then error_reply(s,'403 Forbidden'); return end
    local literal=route~='name'
    if route=='local' then ip=r.host
    elseif not literal then ip,denied=resolve_private(r.host) end
    if denied then error_reply(s,'403 Forbidden'); return end
    local local_name=not r.host:find('.',1,true) or r.host:match('%.lan$') or r.host:match('%.local$')
    if local_name and not literal and not ip then error_reply(s,'502 Bad Gateway'); return end
    if ip then
        s.kind='local'; counters.local_requests=counters.local_requests+1
        s.u=n.socket(ip:find(':',1,true) and 'inet6' or 'inet','stream')
        if not s.u then error_reply(s,'502 Bad Gateway'); return end
        s.u:setblocking(false)
        local ok,err=s.u:connect(ip,r.port)
        if not ok and err~=n.const.EINPROGRESS and err~=n.const.EAGAIN then error_reply(s,'502 Bad Gateway'); return end
        s.connecting=not ok; s.connect_deadline=now()+5
        if r.method=='CONNECT' then
            s.c2u=rest; s.connect_reply=true
            if not s.connecting then s.u2c='HTTP/1.1 200 Connection Established\r\n\r\n'; s.connect_reply=false end
        else
            s.c2u=protocol.local_request(header,r,rest)
        end
    else
        s.kind='external'; counters.external_requests=counters.external_requests+1
        s.c2u=header..rest
        if startup_killed then error_reply(s,'503 Service Unavailable'); return end
        local action=startup_pid and 'wait' or lifecycle.request(life,now())
        if action=='ready' then connect_backend(s) else
            s.waiting=true
            if action=='start' and not launch_startup() then
                lifecycle.complete(life,now(),false); error_reply(s,'503 Service Unavailable')
            end
        end
    end
    s.header=nil
    save('request')
end
local function activity(s,count) if s.kind=='external' and count and count>0 then last_external=now(); lifecycle.active(life,last_external) end end
local function write_side(s,side)
    local sock=side=='c' and s.c or s.u
    local key=side=='c' and 'u2c' or 'c2u'
    if not sock or #s[key]==0 then return end
    local sent,err=sock:send(s[key])
    if sent then s[key]=s[key]:sub(sent+1); activity(s,sent)
    elseif err~=n.const.EAGAIN and err~=n.const.EWOULDBLOCK then close_session(s) end
end
local function read_side(s,side)
    local sock=side=='c' and s.c or s.u
    local data,err=sock:recv(8192)
    if data and #data>0 then
        activity(s,#data)
        if side=='c' and s.header then
            s.header=s.header..data
            if #s.header>32768 then error_reply(s,'431 Request Header Fields Too Large') else start_request(s) end
        elseif side=='c' then s.c2u=s.c2u..data else s.u2c=s.u2c..data end
    elseif data=='' then s[side..'_eof']=true
    elseif err~=n.const.EAGAIN and err~=n.const.EWOULDBLOCK then close_session(s) end
end
local function main()
    ownership.cancel(cfg)
    if not linked then sys.call(cfg.core_service..' stop >/dev/null 2>&1') end
    core_on=false
    generation=assert(ownership.begin(cfg),'Cannot establish startup ownership')
    server=assert(n.bind(cfg.bind,cfg.port,'inet','stream'))
    assert(server:listen(32)); assert(server:setblocking(false))
    log(linked and 'listener_ready external_core_unmanaged' or 'listener_ready core_off'); save('waiting')
    local loop_count=0
    while true do
        advance_startup()
        local pending=false
        for _,s in ipairs(sessions) do
            if not s.dead and s.kind=='external' and (s.waiting or s.connecting) then pending=true; break end
        end
        if core_on and not startup_pid and lifecycle.should_stop(life,now(),pending) then stop_core('idle') end
        local fds={{fd=server,events=IN,listener=true}}
        local alive={}
        for _,s in ipairs(sessions) do
            if not s.dead then
                if s.header and now()-s.accepted>10 then close_session(s)
                elseif s.connecting and now()>s.connect_deadline then error_reply(s,'504 Gateway Timeout') end
                if not s.dead then
                    if s.c_eof and #s.c2u==0 and s.u and not s.u_shutdown then s.u:shutdown('wr'); s.u_shutdown=true end
                    if s.u_eof and #s.u2c==0 and not s.c_shutdown then s.c:shutdown('wr'); s.c_shutdown=true end
                    if (s.close_after_write and #s.u2c==0) or (s.c_eof and s.u_eof and #s.c2u==0 and #s.u2c==0) then close_session(s) end
                end
                if not s.dead then
                    alive[#alive+1]=s
                    local ce=0
                    if not s.c_eof and #s.c2u<262144 then ce=ce+IN end
                    if #s.u2c>0 then ce=ce+OUT end
                    if ce>0 then fds[#fds+1]={fd=s.c,events=ce,s=s,side='c'} end
                    if s.u then
                        local ue=0
                        if s.connecting then ue=OUT else
                            if not s.u_eof and #s.u2c<262144 then ue=ue+IN end
                            if #s.c2u>0 then ue=ue+OUT end
                        end
                        if ue>0 then fds[#fds+1]={fd=s.u,events=ue,s=s,side='u'} end
                    end
                end
            end
        end
        sessions=alive
        local ready=n.poll(fds,250)
        if ready and ready>0 then
            for _,p in ipairs(fds) do
                local ev=p.revents or 0
                if p.listener and band(ev,IN)~=0 then
                    for _=1,32 do
                        local c,ip=server:accept(); if not c then break end
                        if ip~=cfg.allowed_ip or #sessions>=32 then
                            counters.denied_clients=counters.denied_clients+1; c:close()
                        else
                            c:setblocking(false)
                            sessions[#sessions+1]={c=c,header='',accepted=now(),c2u='',u2c='',c_eof=false,u_eof=false}
                        end
                    end
                elseif p.s and not p.s.dead then
                    local s=p.s
                    if p.side=='u' and s.connecting and ev~=0 then
                        local err=s.u:getopt('socket','error')
                        if err~=0 then error_reply(s,'502 Bad Gateway') else
                            s.connecting=false
                            if s.connect_reply then s.u2c='HTTP/1.1 200 Connection Established\r\n\r\n'..s.u2c; s.connect_reply=false end
                        end
                    else
                        if band(ev,IN)~=0 then read_side(s,p.side) end
                        if not s.dead and band(ev,OUT)~=0 then write_side(s,p.side) end
                        if not s.dead and band(ev,ERR)~=0 then close_session(s)
                        elseif not s.dead and band(ev,HUP)~=0 and band(ev,IN)==0 then s[p.side..'_eof']=true end
                    end
                end
            end
        end
        if now()-last_save>=5 then save(startup_pid and 'starting' or (core_on and 'active' or 'waiting')) end
        loop_count=loop_count+1
        if loop_count%240==0 then
            for _,name in ipairs({'events.log'}) do
                local path=cfg.run_dir..'/'..name; local st=fs.stat(path)
                if st and st.size>1048576 then fs.rename(path,path..'.1') end
            end
        end
    end
end
local ok,err=xpcall(main,debug.traceback)
if not ok then log('launcher_failure '..tostring(err)); stop_core('launcher_failure'); os.exit(1) end
