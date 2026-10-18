-- Read-only Mihomo control API. No shell, DNS, service starts, mutations, or
-- delay tests. All socket operations are nonblocking and bounded.
local n = require 'nixio'
local fs = require 'nixio.fs'
local json = require 'luci.jsonc'
local M = {}
local MAX_HEADER, MAX_BODY, MAX_WIRE = 16384, 524288, 1064960
local MAX_STEPS = 512
local IN, OUT = n.poll_flags('in'), n.poll_flags('out')
local function private(st,kind)
    return st and st.type==kind and st.uid==0 and type(st.modestr)=='string'
        and #st.modestr==9 and st.modestr:sub(4)=='------'
end
function M.private_path(path,kind)
    return type(path)=='string' and private(fs.lstat(path),kind)
end
local function auth_header(path)
    if type(path)~='string' or not M.private_path(path:match('^(.*)/[^/]+$'),'dir')
        or not M.private_path(path,'reg') then return nil,'unsafe API header file' end
    local st=fs.lstat(path)
    if not st or st.size>512 then return nil,'invalid API header' end
    local value=fs.readfile(path,513)
    if not value or #value>512 then return nil,'invalid API header' end
    value=value:gsub('\n$','')
    if not value:match('^Authorization: Bearer [A-Za-z0-9._~+/=%-]+$') then return nil,'invalid API header' end
    return value
end
function M.encode_name(name)
    if type(name)~='string' or #name==0 or #name>256 then return nil end
    return (name:gsub('[^A-Za-z0-9%-%._~]',function(c) return string.format('%%%02X',c:byte()) end))
end
local function allowed_path(path)
    if path=='/proxies' then return true end
    local name=type(path)=='string' and path:match('^/proxies/([A-Za-z0-9%%._~%-]+)$')
    if not name or #name>768 or name:gsub('%%%x%x',''):find('%%') then return false end
    local decoded=name:gsub('%%(%x%x)',function(v) return string.char(tonumber(v,16)) end)
    -- Encoded separators must not become the /delay endpoint in a router
    -- that decodes before matching routes. Listing the map still supports
    -- nodes whose names contain separators.
    return decoded~='.' and decoded~='..' and not decoded:find('[/%?%%#\\%c]')
end
local function pending(eof) return nil,eof and 'truncated API response' or 'incomplete' end
-- Separate pure parser permits offline framing/status regression tests.
function M.parse_response(raw,eof)
    if type(raw)~='string' or #raw>MAX_WIRE then return nil,'API response too large' end
    local split=raw:find('\r\n\r\n',1,true)
    if not split then
        if #raw>MAX_HEADER then return nil,'API headers too large' end
        return pending(eof)
    end
    if split>MAX_HEADER then return nil,'API headers too large' end
    local headers,body=raw:sub(1,split-1),raw:sub(split+4)
    local at=headers:find('\r\n',1,true)
    local status=at and headers:sub(1,at-1) or headers
    if status:find('%c') or not status:match('^HTTP/1%.[01] 200 [^\r\n]*$') then return nil,'API HTTP status is not 200' end
    local fields,lines={},0
    for line in (at and (headers:sub(at+2)..'\r\n') or ''):gmatch('(.-)\r\n') do
        lines=lines+1
        local key,value=line:match("^([!#$%%&'*+.^_`|~A-Za-z0-9%-]+):[ \t]*(.-)[ \t]*$")
        if lines>64 or not key or value:find('[\r\n%z\1-\8\11\12\14-\31\127]') then return nil,'invalid API headers' end
        key=key:lower()
        if fields[key] and (key=='content-length' or key=='transfer-encoding' or key=='content-encoding') then return nil,'duplicate API framing header' end
        fields[key]=value
    end
    local length,encoding=fields['content-length'],fields['transfer-encoding']
    if fields['content-encoding'] and fields['content-encoding']:lower()~='identity' then return nil,'unsupported API content encoding' end
    if length and encoding then return nil,'ambiguous API framing' end
    if length then
        if not length:match('^%d+$') or #length>8 then return nil,'invalid API content length' end
        length=tonumber(length)
        if length>MAX_BODY then return nil,'API response too large' end
        if #body<length then return pending(eof) end
        if #body~=length then return nil,'excess API response bytes' end
        return body
    elseif encoding then
        if encoding:lower()~='chunked' then return nil,'unsupported API transfer encoding' end
        local chunks,pos,total={},1,0
        for _=1,4096 do
            local stop=body:find('\r\n',pos,true)
            if not stop then return pending(eof) end
            local size=body:sub(pos,stop-1)
            if #size>8 or not size:match('^%x+$') then return nil,'invalid API chunk size' end
            size=tonumber(size,16); pos=stop+2
            if size==0 then
                if #body<pos+1 then return pending(eof) end
                -- Mihomo sends no trailers: reject rather than merging them.
                if body:sub(pos)~='\r\n' then return nil,'invalid API chunk terminator' end
                return table.concat(chunks)
            end
            total=total+size
            if total>MAX_BODY then return nil,'API response too large' end
            if #body<pos+size+1 then return pending(eof) end
            if body:sub(pos+size,pos+size+1)~='\r\n' then return nil,'invalid API chunk boundary' end
            chunks[#chunks+1]=body:sub(pos,pos+size-1); pos=pos+size+2
        end
        return nil,'too many API chunks'
    else
        if #body>MAX_BODY then return nil,'API response too large' end
        if not eof then return nil,'incomplete' end
        return body
    end
end
local function retry(err)
    return type(err)=='number' and (err==n.const.EAGAIN or err==n.const.EWOULDBLOCK or err==n.const.EINTR or err==n.const.EINPROGRESS)
end
local function budget(opts)
    local timeout=opts and tonumber(opts.timeout_ms) or 1500
    if not timeout or timeout~=timeout or timeout<1 or timeout>2000 then timeout=1500 end
    -- Monotonic uptime has whole-second resolution. The independent step cap
    -- also bounds continually readable/fragmented responses or a frozen clock.
    return {deadline=n.sysinfo().uptime+math.ceil(timeout/1000),steps=0}
end
local function wait_socket(socket,event,b)
    b.steps=b.steps+1
    if b.steps>MAX_STEPS or n.sysinfo().uptime>=b.deadline then return nil,'API timeout' end
    local p={{fd=socket,events=event}}
    local count,err=n.poll(p,10)
    if not count then
        if err==n.const.EINTR then return false end
        return nil,'API poll failed'
    end
    return count>0
end
local function connect(socket,port,b)
    if not socket:setblocking(false) then return nil,'cannot set API socket nonblocking' end
    local ok,err=socket:connect('127.0.0.1',port)
    if ok then return true end
    if not retry(err) then return nil,'API unavailable' end
    while true do
        local ready,why=wait_socket(socket,OUT,b)
        if ready==nil then return nil,why end
        if ready then
            if socket:getopt('socket','error')~=0 then return nil,'API connection failed' end
            return true
        end
    end
end
local function valid_port(port)
    return type(port)=='number' and port==math.floor(port) and port>=1 and port<=65535
end
-- Loopback backend readiness probe: bounded connect, no request bytes.
function M.probe(port,opts)
    if not valid_port(port) then return nil,'invalid loopback port' end
    local socket=n.socket('inet','stream'); if not socket then return nil,'socket unavailable' end
    local ok,err=connect(socket,port,budget(opts)); socket:close(); return ok,err
end
function M.get(cfg,path,opts)
    if type(cfg)~='table' or not valid_port(cfg.api_port) or not allowed_path(path) then return nil,'invalid API request' end
    local auth,why=auth_header(cfg.api_header); if not auth then return nil,why end
    local socket=n.socket('inet','stream'); if not socket then return nil,'socket unavailable' end
    local b=budget(opts)
    local function finish(value,err) socket:close(); return value,err end
    local ok,err=connect(socket,cfg.api_port,b); if not ok then return finish(nil,err) end
    local request='GET '..path..' HTTP/1.1\r\nHost: 127.0.0.1:'..cfg.api_port..'\r\n'..auth..'\r\nAccept: application/json\r\nConnection: close\r\n\r\n'
    local offset=1
    while offset<=#request do
        local ready,reason=wait_socket(socket,OUT,b)
        if ready==nil then return finish(nil,reason) end
        if ready then
            local sent,code=socket:send(request:sub(offset))
            if sent and sent>0 then offset=offset+sent
            elseif sent==0 or not retry(code) then return finish(nil,'API send failed') end
        end
    end
    local response=''
    while true do
        local ready,reason=wait_socket(socket,IN,b)
        if ready==nil then return finish(nil,reason) end
        if ready then
            local data,code=socket:recv(8192)
            if data then
                response=response..data
                local body,parse_error=M.parse_response(response,data=='')
                if body then
                    if not body:match('^%s*{') then return finish(nil,'invalid API JSON object') end
                    local parsed,value=pcall(json.parse,body)
                    if not parsed or type(value)~='table' then return finish(nil,'invalid API JSON object') end
                    return finish(value)
                elseif parse_error~='incomplete' then return finish(nil,parse_error) end
            elseif not retry(code) then return finish(nil,'API receive failed') end
        end
    end
end
return M
