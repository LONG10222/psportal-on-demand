-- Pure subscription policy and transaction helpers. Requiring this module
-- performs no I/O. Runtime networking lives only in update-subscription.lua.
local protocol = require 'protocol'
local M = {MAX_BYTES=5*1024*1024, DNS_SECONDS=10, TRANSFER_SECONDS=35}

function M.public_ipv4(ip)
    return protocol.ipv4(ip) and protocol.destination(ip)=='external'
end

local function dns_name(host)
    if #host>253 or not host:find('.',1,true) or host:find('..',1,true) or
        host:sub(1,1)=='.' or host:sub(-1)=='.' then return false end
    local numeric=true
    for label in host:gmatch('[^.]+') do
        if #label>63 or not label:match('^[a-z0-9][a-z0-9%-]*$') or label:sub(-1)=='-' then return false end
        if not label:match('^%d+$') and not label:match('^0x%x+$') then numeric=false end
    end
    if numeric then return false end
    for _,suffix in ipairs({'localhost','local','localdomain','lan','home','home.arpa','internal',
        'invalid','test','onion','in-addr.arpa','ip6.arpa'}) do
        if host==suffix or host:sub(-#suffix-1)=='.'..suffix then return false end
    end
    return true
end

function M.validate_url(url)
    assert(type(url)=='string' and #url>0 and #url<=8192 and not url:find('REPLACE_ME',1,true),
        'Set a real subscription_url locally')
    -- Restrict to ASCII URI characters. In particular, backslashes, raw control
    -- characters, fragments and encoded authority delimiters cannot reach curl.
    assert(not url:find('[^a-zA-Z0-9%-%._~!$&\'()*+,;=:@/?%%]'),
        'subscription_url contains unsupported characters')
    assert(not url:gsub('%%%x%x',''):find('%%'), 'Invalid subscription URL escape')
    local authority,tail=url:match('^https://([^/?]+)(.*)$')
    assert(authority and not authority:find('@',1,true),
        'subscription_url must use HTTPS without userinfo or fragments')
    local host,port=authority:match('^([^:]+):(%d+)$')
    if not host then
        assert(not authority:find(':',1,true), 'Invalid subscription port or IPv6 host')
        host=authority
    end
    local number=port and tonumber(port) or 443
    assert(number and number>=1 and number<=65535 and (not port or tostring(number)==port),
        'Invalid subscription port')
    host=host:lower()
    local is_ipv4=protocol.ipv4(host)
    assert((is_ipv4 and M.public_ipv4(host)) or (not is_ipv4 and dns_name(host)),
        'subscription_url requires a public IPv4 address or public DNS name')
    return {host=host,port=number,is_ipv4=is_ipv4,
        url='https://'..host..(port and ':'..port or '')..tail}
end

function M.validate_user_agent(value)
    value=value or 'clash.meta'
    assert(type(value)=='string' and #value>0 and #value<256 and not value:find('[^ -~]'),
        'Invalid subscription_user_agent')
    return value
end

-- Validate the entire IPv4 lookup result, not merely the first usable answer.
-- Unexpected IPv6 records fail closed; runtime requests only the inet family.
function M.validate_addresses(records)
    assert(type(records)=='table' and #records>0 and #records<=128,
        'Subscription DNS lookup failed or returned too many addresses')
    local selected
    for _,record in ipairs(records) do
        assert(type(record)=='table' and record.family=='inet' and M.public_ipv4(record.address),
            'Subscription DNS must return only public IPv4 addresses')
        selected=selected or record.address
    end
    return selected
end

local function quote(value)
    assert(type(value)=='string' and not value:find('[%c]'), 'Invalid curl configuration value')
    return '"'..value:gsub('\\','\\\\'):gsub('"','\\"')..'"'
end
M.quote_config=quote

function M.curl_config(target,ip,user_agent)
    -- Revalidate callers' structured input so this helper cannot accidentally
    -- become an unpinned URL/config injection route.
    local checked=M.validate_url(target.url)
    assert(checked.host==target.host and checked.port==target.port and M.public_ipv4(ip),
        'Invalid subscription destination')
    assert(not checked.is_ipv4 or checked.host==ip, 'Invalid literal subscription destination')
    user_agent=M.validate_user_agent(user_agent)
    return table.concat({
        'url = '..quote(checked.url),
        'resolve = '..quote(checked.host..':'..checked.port..':'..ip),
        'user-agent = '..quote(user_agent),
        'proto = "=https"','proto-redir = "=https"','proxy = ""','noproxy = "*"',
        'no-location','max-redirs = 0','no-insecure','no-netrc','globoff','ipv4',
        'http1.1','tlsv1.2','silent','fail','connect-timeout = 10','max-time = 30',
        'max-filesize = '..M.MAX_BYTES,'output = "-"','write-out = "%{http_code}"',''
    },'\n')
end

-- curl appends exactly three HTTP-status bytes to stdout. Hold those bytes back
-- while streaming the body; the spool never exceeds MAX_BYTES, including when
-- old curl versions cannot enforce --max-filesize on chunked responses.
function M.new_stream()
    local state={tail='',size=0}
    function state:push(chunk)
        assert(type(chunk)=='string', 'Subscription stream read failed')
        local combined=self.tail..chunk
        local body=combined:sub(1,math.max(0,#combined-3))
        assert(self.size+#body<=M.MAX_BYTES, 'Subscription exceeds 5 MiB')
        self.tail=combined:sub(math.max(1,#combined-2))
        self.size=self.size+#body
        return body
    end
    function state:finish()
        -- A redirect, partial response, error page or empty success is never
        -- published. No content/YAML claims are made by this transport check.
        assert(self.tail=='200', 'Subscription server did not return HTTP 200')
        assert(self.size>0, 'Subscription response is empty')
        return self.size
    end
    return state
end

-- The runtime adapter owns cleanup and atomic rename. The commit callback is
-- unreachable until every policy, curl-exit, HTTP-status and size check passes.
function M.update(options,ops)
    local target=M.validate_url(options.subscription_url)
    local agent=M.validate_user_agent(options.subscription_user_agent)
    local records=target.is_ipv4 and {{family='inet',address=target.host}} or ops.resolve(target.host)
    local ip=M.validate_addresses(records)
    local stream=M.new_stream()
    assert(ops.fetch(M.curl_config(target,ip,agent),function(chunk)
        local body=stream:push(chunk)
        if #body>0 then assert(ops.write(body), 'Cannot write subscription cache') end
    end), 'Subscription HTTPS transfer failed')
    local size=stream:finish()
    assert(ops.commit(size), 'Cannot replace subscription cache')
    return size
end

return M
