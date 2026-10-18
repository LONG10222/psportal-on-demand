local n = require 'nixio'
local fs = require 'nixio.fs'
local json = require 'luci.jsonc'
local util = require 'luci.util'
local sys = require 'luci.sys'
local directory = arg[0]:match('^(.*)/') or '.'
package.path = directory .. '/?.lua;' .. package.path
local protocol = require 'protocol'
local policy_path = assert(arg[1], 'policy required')
local cfg = assert(json.parse(assert(fs.readfile(policy_path))), 'Invalid policy')
n.umask('077')
n.signal(n.const.SIGTERM, 'dfl')
n.signal(n.const.SIGINT, 'dfl')
n.signal(n.const.SIGHUP, 'dfl')
n.signal(n.const.SIGPIPE, 'ign')
local IN, OUT, ERR, HUP = n.poll_flags('in'), n.poll_flags('out'), n.poll_flags('err'), n.poll_flags('hup')
local band = n.bit.band
local sessions, cache = {}, {}
local core_on, last_external, last_save = false, 0, 0
local counters = {external_requests=0, local_requests=0, denied_clients=0, starts=0, idle_stops=0}
local function now() return n.sysinfo().uptime end
local function log(msg)
    local f = io.open(cfg.run_dir .. '/events.log', 'a')
    if f then f:write(os.date('!%Y-%m-%dT%H:%M:%SZ'), ' ', msg, '\n'); f:close() end
end
local function core_pid()
    local t = util.ubus('service', 'list', {name=cfg.core_name}) or {}
    local i = t[cfg.core_name] and t[cfg.core_name].instances
    return i and i.main and i.main.running and i.main.pid or nil
end
local function save(reason)
    local ext, lan = 0, 0
    for _,s in ipairs(sessions) do
        if not s.dead and s.kind == 'external' then ext=ext+1 end
        if not s.dead and s.kind == 'local' then lan=lan+1 end
    end
    local t = {launcher_pid=n.getpid(), core_running=core_on and core_pid()~=nil,
        core_pid=core_on and core_pid() or nil, idle_timeout=cfg.idle_seconds,
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
local function stop_core(reason)
    for _,s in ipairs(sessions) do if s.kind=='external' then close_session(s) end end
    sys.call(cfg.core_service..' stop >/dev/null 2>&1')
    core_on=false
    if reason=='idle' then counters.idle_stops=counters.idle_stops+1 end
    log('core_off reason='..reason..' external_idle_seconds='..tostring(last_external>0 and now()-last_external or 0))
    save(reason)
end
local function api_get(path)
    local f=io.open(cfg.api_header,'r'); if not f then return nil end
    local auth=f:read('*l'); f:close()
    local s=n.socket('inet','stream')
    if not s:connect('127.0.0.1',cfg.api_port) then s:close(); return nil end
    s:send('GET '..path..' HTTP/1.1\r\nHost: localhost\r\n'..auth..'\r\nConnection: close\r\n\r\n')
    s:setblocking(false)
    local response=''
    for _=1,12 do
        local polls={{fd=s,events=IN}}; local count=n.poll(polls,100)
        if count and count>0 then
            local data=s:recv(8192)
            if data=='' then break end
            if data then response=response..data end
        end
        if #response>65536 then break end
    end
    s:close()
    local split=response:find('\r\n\r\n',1,true); if not split then return nil end
    local headers,body=response:sub(1,split-1),response:sub(split+4)
    if headers:lower():find('transfer-encoding: chunked',1,true) then
        local chunks={}; local p=1
        while true do
            local at=body:find('\r\n',p,true); if not at then return nil end
            local size=tonumber(body:sub(p,at-1):match('^%x+'),16); if not size then return nil end
            if size==0 then break end
            p=at+2; if #body<p+size-1 then return nil end
            chunks[#chunks+1]=body:sub(p,p+size-1); p=p+size+2
        end
        body=table.concat(chunks)
    end
    return json.parse(body)
end
local function route_ready()
    local g=api_get('/proxies/PORTAL'); if not g or not g.now then return false end
    local encoded=g.now:gsub('[^%w%-%._~]',function(c) return string.format('%%%02X',c:byte()) end)
    local p=api_get('/proxies/'..encoded)
    local h=p and p.extra and p.extra[cfg.health_url]
    return h and h.alive and h.history and #h.history>0 and h.history[#h.history].delay>0
end
local function wake_core()
    local cold=not core_pid()
    if cold then
        if sys.call(cfg.core_service..' start >/dev/null 2>&1')~=0 then return nil end
        counters.starts=counters.starts+1
        log('core_start external_request')
    end
    core_on=true
    last_external=now()
    local deadline=now()+(cfg.wakeup_timeout or 12)
    while now()<=deadline do
        local s=n.socket('inet','stream')
        if s:connect('127.0.0.1',cfg.backend_port) then
            if not cold or route_ready() then s:setblocking(false); save('active'); return s end
        end
        s:close(); n.nanosleep(0,100000000)
    end
    save('core_start_failed')
    return nil
end
local local_ip = protocol.local_ip
local function word(v) return string.char(math.floor(v/256)%256,v%256) end
local function u16(s,p) local a,b=s:byte(p,p+1); if not b then return nil end; return a*256+b end
local function skip_name(s,p)
    for _=1,128 do
        local l=s:byte(p); if not l then return nil end
        if l==0 then return p+1 end
        if l>=192 then return p+2 end
        if l>63 then return nil end
        p=p+1+l
    end
end
local function resolve_private(host)
    local hit=cache[host]; if hit and hit.until_at>now() then return hit.ip end
    if not host:match('^[%w%.%-]+$') or #host>253 then return nil end
    local q=''
    for label in host:gmatch('[^.]+') do if #label>63 then return nil end; q=q..string.char(#label)..label end
    local id=math.random(1,65535)
    local packet=word(id)..word(256)..word(1)..word(0)..word(0)..word(0)..q..'\0'..word(1)..word(1)
    local s=n.socket('inet','dgram'); s:setblocking(false)
    s:sendto(packet,cfg.local_dns,53)
    local fds={{fd=s,events=IN}}; local count=n.poll(fds,200)
    local data,peer,port
    if count and count>0 then data,peer,port=s:recvfrom(4096) end
    s:close()
    local chosen=nil
    if data and peer==cfg.local_dns and port==53 and u16(data,1)==id then
        local p=13
        for _=1,(u16(data,5) or 0) do p=skip_name(data,p); if not p then break end; p=p+4 end
        if p then
            local has_public=false
            for _=1,math.min(u16(data,7) or 0,64) do
                p=skip_name(data,p); if not p then break end
                local typ,len=u16(data,p),u16(data,p+8); if not len then break end
                p=p+10
                if typ==1 and len==4 and #data>=p+3 then
                    local ip=table.concat({data:byte(p,p+3)},'.')
                    if local_ip(ip) then chosen=chosen or ip else has_public=true end
                end
                p=p+len
            end
            if has_public then chosen=nil end
        end
    end
    local size=0; for _ in pairs(cache) do size=size+1 end
    if size>256 then cache={} end
    cache[host]={ip=chosen,until_at=now()+60}
    return chosen
end
local parse_request = protocol.parse_request
local function error_reply(s,code)
    if s.u then s.u:close(); s.u=nil end
    s.connecting=false; s.header=nil
    s.reply='HTTP/1.1 '..code..'\r\nConnection: close\r\nContent-Length: 0\r\n\r\n'
    s.c2u=''; s.u2c=s.reply; s.close_after_write=true; s.c_eof=true; s.u_eof=true
end
local function start_request(s)
    local a,b=s.header:find('\r\n\r\n',1,true); if not a then return end
    local header,rest=s.header:sub(1,b),s.header:sub(b+1)
    local r=parse_request(header)
    if not r then error_reply(s,'400 Bad Request'); return end
    local ip
    local literal=r.host:match('^%d+%.%d+%.%d+%.%d+$') or r.host:find(':',1,true)
    if literal then if local_ip(r.host) then ip=r.host end else ip=resolve_private(r.host) end
    local local_name=not r.host:find('.',1,true) or r.host:match('%.lan$') or r.host:match('%.local$')
    if local_name and not literal and not ip then error_reply(s,'502 Bad Gateway'); return end
    if ip then
        s.kind='local'; counters.local_requests=counters.local_requests+1
        s.u=n.socket(ip:find(':',1,true) and 'inet6' or 'inet','stream'); s.u:setblocking(false)
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
        last_external=now(); s.u=wake_core()
        if not s.u then error_reply(s,'503 Service Unavailable'); return end
        s.c2u=header..rest
    end
    s.header=nil
    save('request')
end
local function activity(s,count) if s.kind=='external' and count and count>0 then last_external=now() end end
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
    sys.call(cfg.core_service..' stop >/dev/null 2>&1')
    core_on=false
    local server=assert(n.bind(cfg.bind,cfg.port,'inet','stream'))
    assert(server:listen(32)); assert(server:setblocking(false))
    log('listener_ready core_off'); save('waiting')
    local loop_count=0
    while true do
        if core_on and now()-last_external>=cfg.idle_seconds then stop_core('idle') end
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
        if now()-last_save>=5 then save(core_on and 'active' or 'waiting') end
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
