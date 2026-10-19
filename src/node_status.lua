-- Sanitized node snapshots. Cached reads never contact procd, the listener,
-- or the core, and cannot renew the listener's external-idle deadline.
local n = require 'nixio'
local fs = require 'nixio.fs'
local json = require 'luci.jsonc'
local api = require 'core_api'
local M = {}
local MAX_NODES, MAX_DEPTH, MAX_CACHE = 2048, 16, 1048576
local groups={selector=true,urltest=true,fallback=true,loadbalance=true,relay=true}
local forbidden={direct=true,reject=true,rejectdrop=true,pass=true,compatible=true,dns=true}
local function tag(value) return type(value)=='string' and value:lower():gsub('[%s%-%_]','') or '' end
local function safe_name(value)
    return type(value)=='string' and #value>0 and #value<=256
        and not value:find('[%z\1-\31\127]') and not value:find('\194[\128-\159]')
        and not value:find('\226\128[\168-\174]') and not value:find('\226\129[\166-\169]')
end
local function delay(value)
    return type(value)=='number' and value>0 and value<=600000 and value==math.floor(value) and value or nil
end
local function terminal(name,p)
    return safe_name(name) and type(p)=='table' and safe_name(p.type)
        and not forbidden[tag(name)] and not forbidden[tag(p.type)]
        and not groups[tag(p.type)] and p.now==nil and p.all==nil
end
local function health(p,url)
    local h=type(p.extra)=='table' and p.extra[url]
    if type(h)~='table' or h.alive~=true or type(h.history)~='table' or #h.history<1 then return nil end
    local last=h.history[#h.history]
    return type(last)=='table' and delay(last.delay) or nil
end
function M.resolve(proxies,health_url,root)
    if type(proxies)~='table' or type(health_url)~='string' then return nil,'invalid proxy state' end
    local name,seen,path=root or 'PORTAL',{},{}
    for _=1,MAX_DEPTH do
        if not safe_name(name) or forbidden[tag(name)] then return nil,'forbidden or invalid selected node' end
        if seen[name] then return nil,'proxy selection cycle' end
        seen[name]=true; path[#path+1]=name
        local p=proxies[name]
        if type(p)~='table' or forbidden[tag(p.type)] then return nil,'selected node unavailable' end
        if terminal(name,p) then
            local value=health(p,health_url)
            if not value then return nil,'selected node has no successful health result' end
            return name,value,path
        end
        if not safe_name(p.now) then return nil,'selected group is unresolved' end
        if p.all~=nil then
            if type(p.all)~='table' or #p.all>MAX_NODES then return nil,'invalid selected group' end
            local found=false
            for _,member in ipairs(p.all) do if member==p.now then found=true; break end end
            if not found then return nil,'selected node is absent from group' end
        end
        name=p.now
    end
    return nil,'proxy selection depth exceeded'
end
function M.collect(cfg,opts)
    if cfg.core_mode=='openclash' then
        local runtime,why=api.get(cfg,'/configs',opts)
        if not runtime then return nil,why end
        local mode,reason=require('openclash').runtime(runtime,cfg)
        local reachable = mode and api.probe(cfg.backend_port,opts)
        if mode and not reachable then reason='OpenClash proxy port is unavailable' end
        local snapshot={version=1,core_mode='openclash',updated_at=os.time(),ready=mode~=nil and reachable==true,
            route_policy=mode,nodes={},groups={},reason=reason,nodes_available=false}
        if not snapshot.ready then return snapshot end
        local state=api.get(cfg,'/proxies',opts)
        -- Node display is optional; a large/unsupported proxy map cannot block
        -- an authenticated, runtime-matched and reachable external endpoint.
        if not state or type(state.proxies)~='table' then return snapshot end
        local count=0
        for name,p in pairs(state.proxies) do
            count=count+1
            if count>MAX_NODES then snapshot.nodes={}; snapshot.groups={}; return snapshot end
            if safe_name(name) and type(p)=='table' then
                if groups[tag(p.type)] then
                    snapshot.groups[#snapshot.groups+1]={name=name,type=p.type,
                        selected=safe_name(p.now) and p.now or nil}
                elseif terminal(name,p) then
                    -- No chosen health URL or per-request route is implied.
                    snapshot.nodes[#snapshot.nodes+1]={name=name}
                end
            end
        end
        snapshot.nodes_available=true
        table.sort(snapshot.nodes,function(a,b) return a.name<b.name end)
        table.sort(snapshot.groups,function(a,b) return a.name<b.name end)
        return snapshot
    end
    local state,err=api.get(cfg,'/proxies',opts)
    if not state then return nil,err end
    if type(state.proxies)~='table' then return nil,'invalid API proxy map' end
    local name,value,path=M.resolve(state.proxies,cfg.health_url)
    local snapshot={version=1,updated_at=os.time(),ready=name~=nil,nodes={}}
    if name then snapshot.current={name=name,delay=value,path=path} else snapshot.reason=value end
    if name and cfg.selection_mode=='fixed' and name~=cfg.preferred_node then
        snapshot.ready=false; snapshot.reason='fixed preferred node is not selected'
    end
    local count=0
    for node,p in pairs(state.proxies) do
        count=count+1
        if count>MAX_NODES then return nil,'too many API proxies' end
        if terminal(node,p) then
            local latest=health(p,cfg.health_url)
            snapshot.nodes[#snapshot.nodes+1]={name=node,delay=latest,alive=latest~=nil,selected=node==name}
        end
    end
    table.sort(snapshot.nodes,function(a,b) return a.name<b.name end)
    if cfg.selection_mode=='fixed' and safe_name(cfg.preferred_node) and not terminal(cfg.preferred_node,state.proxies[cfg.preferred_node]) then snapshot.preferred_missing=true end
    return snapshot
end
local function cache_path(cfg) return type(cfg)=='table' and type(cfg.run_dir)=='string' and cfg.run_dir..'/nodes.json' or nil end
-- Rebuild from a field allowlist even for root-private cached files. No raw
-- provider/API objects or terminal control characters reach CLI consumers.
local function clean(value)
    if type(value)~='table' or value.version~=1 or type(value.nodes)~='table' or #value.nodes>MAX_NODES
        or type(value.updated_at)~='number' or value.updated_at<0 or value.updated_at~=math.floor(value.updated_at)
        or value.updated_at>4102444800 then return nil,'invalid node cache' end
    local result={version=1,updated_at=value.updated_at,ready=false,nodes={}}
    local seen={}
    for _,node in ipairs(value.nodes) do
        if type(node)~='table' or not safe_name(node.name) or forbidden[tag(node.name)] or seen[node.name] then return nil,'invalid cached node' end
        seen[node.name]=true
        local ms=node.alive==true and delay(node.delay) or nil
        result.nodes[#result.nodes+1]={name=node.name,delay=ms,alive=ms~=nil,selected=false}
    end
    if value.core_mode=='openclash' then
        if type(value.groups)~='table' or #value.groups>MAX_NODES then return nil,'invalid linked groups' end
        result.core_mode='openclash'; result.groups={}; result.nodes_available=value.nodes_available==true
        local group_seen={}
        for _,group in ipairs(value.groups) do
            if type(group)~='table' or not safe_name(group.name) or group_seen[group.name]
                or not safe_name(group.type) or not groups[tag(group.type)]
                or (group.selected~=nil and not safe_name(group.selected)) then return nil,'invalid linked group' end
            group_seen[group.name]=true
            result.groups[#result.groups+1]={name=group.name,type=group.type,selected=group.selected}
        end
        if value.route_policy=='rule' or value.route_policy=='global' or value.route_policy=='direct' then
            result.route_policy=value.route_policy; result.ready=value.ready==true
        end
        if safe_name(value.reason) then result.reason=value.reason end
        -- Never retain a single "actual node" or health claim in linked mode.
        for _,node in ipairs(result.nodes) do node.alive=nil; node.delay=nil; node.selected=nil end
        return result
    end
    local current=value.current
    if current~=nil then
        if type(current)~='table' or not safe_name(current.name) or not seen[current.name] or not delay(current.delay)
            or type(current.path)~='table' or #current.path<1 or #current.path>MAX_DEPTH then return nil,'invalid cached selection' end
        local path={}
        for _,part in ipairs(current.path) do
            if not safe_name(part) or forbidden[tag(part)] then return nil,'invalid cached selection path' end
            path[#path+1]=part
        end
        if path[1]~='PORTAL' or path[#path]~=current.name then return nil,'invalid cached selection path' end
        result.current={name=current.name,delay=current.delay,path=path}
        for _,node in ipairs(result.nodes) do
            node.selected=node.name==current.name
            if node.selected and (not node.alive or node.delay~=current.delay) then return nil,'inconsistent cached selection' end
        end
        result.ready=value.ready==true
    end
    if safe_name(value.reason) then result.reason=value.reason end
    if value.preferred_missing==true then result.preferred_missing=true end
    return result
end
function M.read(cfg)
    local path=cache_path(cfg)
    if not path or not api.private_path(cfg.run_dir,'dir') or not api.private_path(path,'reg') then return nil,'no private node cache' end
    local st=fs.lstat(path)
    if not st or st.size>MAX_CACHE then return nil,'node cache too large' end
    local value=fs.readfile(path,MAX_CACHE+1)
    if not value or #value>MAX_CACHE then return nil,'cannot read node cache' end
    local ok,decoded=pcall(json.parse,value)
    if not ok then return nil,'invalid node cache' end
    local cleaned,err=clean(decoded)
    if cleaned and (cleaned.core_mode=='openclash')~=(cfg.core_mode=='openclash') then return nil,'cache belongs to previous mode' end
    return cleaned,err
end
function M.write(cfg,snapshot)
    local path=cache_path(cfg)
    if not path or not api.private_path(cfg.run_dir,'dir') or n.getuid()~=0 then return nil,'no private node cache directory' end
    local checked,err=clean(snapshot); if not checked then return nil,err end
    local encoded=json.stringify(checked)
    if type(encoded)~='string' or #encoded>MAX_CACHE then return nil,'node cache too large' end
    -- Exclusive create avoids symlinks; 0600 applies before bytes are written.
    local temporary=path..'.new.'..n.getpid()
    local f=n.open(temporary,n.open_flags('wronly','creat','excl'),'600')
    if not f then return nil,'cannot create private node cache' end
    local offset=1
    while offset<=#encoded do
        local count=f:write(encoded:sub(offset))
        if not count or count<=0 then f:close(); fs.remove(temporary); return nil,'cannot write node cache' end
        offset=offset+count
    end
    local closed=f:close()
    if not closed or not fs.rename(temporary,path) then fs.remove(temporary); return nil,'cannot publish node cache' end
    return true
end
return M
