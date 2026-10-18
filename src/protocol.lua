local M = {}

function M.ipv4(ip)
    if type(ip) ~= 'string' then return false end
    local a,b,c,d = ip:match('^(%d+)%.(%d+)%.(%d+)%.(%d+)$')
    if not a then return false end
    for _,v in ipairs({a,b,c,d}) do
        if #v > 1 and v:sub(1,1) == '0' then return false end
        if tonumber(v) > 255 then return false end
    end
    return true
end

function M.local_ip(ip)
    if M.ipv4(ip) then
        local a,b = ip:match('^(%d+)%.(%d+)%.')
        a,b = tonumber(a),tonumber(b)
        return a == 10 or a == 127 or (a == 172 and b >= 16 and b <= 31) or
            (a == 192 and b == 168) or (a == 169 and b == 254) or
            (a == 100 and b >= 64 and b <= 127)
    end
    if type(ip) ~= 'string' or not ip:match('^[%x:%.]+$') or not ip:find(':',1,true) then return false end
    local x = ip:lower()
    return x == '::1' or x:match('^f[cd]') ~= nil or x:match('^fe[89ab]') ~= nil
end

function M.parse_request(header)
    local line = header:match('^([^\r\n]+)')
    if not line then return nil end
    local method,target,version = line:match('^(%u+)%s+(%S+)%s+(HTTP/1%.[01])$')
    if not method then return nil end
    local authority,path
    if method == 'CONNECT' then authority = target else
        local scheme,rest = target:match('^(https?)://(.+)$')
        if scheme ~= 'http' then return nil end
        authority,path = rest:match('^([^/%?#]+)(.*)$')
        if not authority then return nil end
        path = path:gsub('#.*$','')
        if path == '' then path = '/' elseif path:sub(1,1) == '?' then path = '/' .. path end
    end
    if not authority or authority:find('@',1,true) then return nil end
    local host,port = authority:match('^%[([^%]]+)%]:(%d+)$')
    if not host then host,port = authority:match('^([^:]+):(%d+)$') end
    if not host then
        if authority:find(':',1,true) or authority:find('[%[%]]') then return nil end
        host = authority
    end
    host = host:lower():gsub('%.$','')
    port = tonumber(port) or (method == 'CONNECT' and 443 or 80)
    if #host == 0 or #host > 253 or port < 1 or port > 65535 then return nil end
    if not host:match('^[%w%.:%-]+$') then return nil end
    if host:match('^[%d%.]+$') and not M.ipv4(host) then return nil end
    return {method=method, host=host, port=port, path=path, version=version}
end

function M.local_request(header,request,body)
    local lines = {request.method .. ' ' .. request.path .. ' ' .. request.version}
    local first = true
    for line in header:gmatch('([^\r\n]+)') do
        local lower = line:lower()
        if first then first = false
        elseif not lower:match('^proxy%-connection:') and not lower:match('^connection:') and
               not lower:match('^proxy%-authorization:') then lines[#lines+1] = line end
    end
    lines[#lines+1] = 'Connection: close'
    return table.concat(lines,'\r\n') .. '\r\n\r\n' .. (body or '')
end

return M
