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

-- Parse addresses without asking libc/DNS to interpret ambiguous numeric forms.
-- Return eight 16-bit words, including for a canonical dotted IPv4 tail.
local function ipv6_words(ip)
    if type(ip) ~= 'string' or not ip:match('^[%x:%.]+$') or not ip:find(':',1,true) then return nil end
    if ip:find('.',1,true) then
        local prefix,tail=ip:match('^(.*:)([^:]+)$')
        if not prefix or not M.ipv4(tail) then return nil end
        local a,b,c,d=tail:match('^(%d+)%.(%d+)%.(%d+)%.(%d+)$')
        ip=prefix..string.format('%x:%x',tonumber(a)*256+tonumber(b),tonumber(c)*256+tonumber(d))
    end
    local at=ip:find('::',1,true)
    if at and ip:find('::',at+2,true) then return nil end
    local function words(part)
        local out={}
        if part=='' then return out end
        if part:sub(1,1)==':' or part:sub(-1)==':' then return nil end
        for word in part:gmatch('[^:]+') do
            if #word>4 or not word:match('^%x+$') then return nil end
            out[#out+1]=tonumber(word,16)
        end
        return out
    end
    local left=words(at and ip:sub(1,at-1) or ip)
    local right=words(at and ip:sub(at+2) or '')
    if not left or not right then return nil end
    local size=#left+#right
    if (at and size>=8) or (not at and size~=8) then return nil end
    if at then for _=1,8-size do left[#left+1]=0 end end
    for _,v in ipairs(right) do left[#left+1]=v end
    return left
end

function M.ipv6(ip) return ipv6_words(ip)~=nil end

local function numeric_host(host)
    -- inet_aton-style integers, octal, hexadecimal and shortened IPv4 must never
    -- become DNS names or be handed to a different parser in the backend.
    if host:match('^[%d%.]+$') then return true end
    for label in host:gmatch('[^.]+') do
        if not label:match('^%d+$') and not label:match('^0x%x+$') then return false end
    end
    return true
end

local function valid_name(host)
    if #host==0 or #host>253 or host:find('..',1,true) or host:sub(1,1)=='.' or host:sub(-1)=='.' then return false end
    for label in host:gmatch('[^.]+') do
        if #label>63 or not label:match('^[a-z0-9][a-z0-9%-]*$') or label:sub(-1)=='-' then return false end
    end
    return not numeric_host(host)
end

-- This is a destination policy, not a general-purpose global-address registry.
-- Only RFC1918/ULA can bypass the backend. Unknown and special-use IPv6 space
-- is denied conservatively, including mapped/translated IPv4 and 6to4/Teredo.
function M.destination(host)
    if type(host)~='string' then return 'deny' end
    host=host:lower()
    if not host:find(':',1,true) then host=host:gsub('%.$','') end
    if M.ipv4(host) then
        local a,b,c=host:match('^(%d+)%.(%d+)%.(%d+)%.')
        a,b,c=tonumber(a),tonumber(b),tonumber(c)
        if a==10 or (a==172 and b>=16 and b<=31) or (a==192 and b==168) then return 'local' end
        if a==0 or a==127 or a>=224 or (a==100 and b>=64 and b<=127) or
            (a==169 and b==254) or (a==192 and b==0 and (c==0 or c==2)) or
            (a==192 and b==88 and c==99) or (a==198 and (b==18 or b==19)) or
            (a==198 and b==51 and c==100) or (a==203 and b==0 and c==113) then return 'deny' end
        return 'external'
    end
    if host:find(':',1,true) then
        local w=ipv6_words(host)
        if not w then return 'deny' end
        if w[1]>=0xfc00 and w[1]<=0xfdff then return 'local' end
        if w[1]<0x2000 or w[1]>=0x4000 or (w[1]==0x2001 and w[2]<0x0200) or
            (w[1]==0x2001 and w[2]==0x0db8) or w[1]==0x2002 or
            (w[1]==0x3fff and w[2]<0x1000) then return 'deny' end
        return 'external'
    end
    if not valid_name(host) or host=='localhost' or host:match('%.localhost$') then return 'deny' end
    return 'name'
end

function M.local_ip(ip) return (M.ipv4(ip) or M.ipv6(ip)) and M.destination(ip)=='local' end

-- Approved LAN connections are made by the launcher, never the backend. Reject
-- LAN as well as special addresses here, with resolution enabled: a public
-- name must not gain a DIRECT route if the backend sees a different DNS answer.
function M.backend_reject_rules()
    local rules={'DOMAIN-SUFFIX,localhost,REJECT'}
    for _,cidr in ipairs({'0.0.0.0/8','10.0.0.0/8','100.64.0.0/10','127.0.0.0/8',
        '169.254.0.0/16','172.16.0.0/12','192.0.0.0/24','192.0.2.0/24',
        '192.88.99.0/24','192.168.0.0/16','198.18.0.0/15','198.51.100.0/24',
        '203.0.113.0/24','224.0.0.0/4','240.0.0.0/4'}) do
        rules[#rules+1]='IP-CIDR,'..cidr..',REJECT'
    end
    for _,cidr in ipairs({'::/3','4000::/2','8000::/1','2001::/23',
        '2001:db8::/32','2002::/16','3fff::/20'}) do
        rules[#rules+1]='IP-CIDR6,'..cidr..',REJECT'
    end
    return rules
end

function M.parse_request(header)
    if type(header)~='string' then return nil end
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
    local host,port
    if authority:sub(1,1)=='[' then
        host,port=authority:match('^%[([^%]]+)%]:(%d+)$')
        if not host then host=authority:match('^%[([^%]]+)%]$') end
        if not host or not M.ipv6(host) then return nil end
    else
        host,port=authority:match('^([^:]+):(%d+)$')
        if not host then
            if authority:find(':',1,true) or authority:find('[%[%]]') then return nil end
            host=authority
        end
    end
    host = host:lower():gsub('%.$','')
    port = tonumber(port) or (method == 'CONNECT' and 443 or 80)
    if #host == 0 or #host > 253 or port < 1 or port > 65535 then return nil end
    if not M.ipv4(host) and not M.ipv6(host) and not valid_name(host) then return nil end
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

-- Add the existing upstream credential only to a fixed loopback connection.
-- Strip any client-supplied proxy authentication, never duplicate credentials.
function M.authenticated_request(request,authorization)
    assert(type(authorization)=='string' and authorization:match('^Proxy%-Authorization: Basic [A-Za-z0-9+/=]+$'))
    local split=assert(request:find('\r\n\r\n',1,true))
    local lines={}
    for line in request:sub(1,split-1):gmatch('[^\r\n]+') do
        local lower=line:lower()
        if not lower:match('^proxy%-authorization:') and not lower:match('^proxy%-connection:')
            and not lower:match('^connection:') then lines[#lines+1]=line end
    end
    lines[#lines+1]=authorization
    if not request:match('^CONNECT ') then lines[#lines+1]='Connection: close' end
    return table.concat(lines,'\r\n')..'\r\n\r\n'..request:sub(split+4)
end

return M
