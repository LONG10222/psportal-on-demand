-- Read-only OpenClash adapter. Never exports credentials, copies subscriptions,
-- changes routes/groups, runs a delay test, or owns the external service.
local M = {}
local function port(value)
    local p = tonumber(value)
    return p and p == math.floor(p) and p >= 1 and p <= 65535 and p or nil
end
local function get(uci,key)
    local value = uci:get('openclash','@overwrite[0]',key)
    if value == nil then value = uci:get('openclash','config',key) end
    return value
end
local function cursor() return require('uci').cursor() end
function M.discover(uci)
    uci = uci or cursor()
    assert(uci:get('openclash','config','enable') == '1', 'Enable OpenClash in its own interface first')
    local http = port(get(uci,'http_port'))
    local mixed = port(get(uci,'mixed_port'))
    local api = port(get(uci,'cn_port'))
    assert(http or mixed, 'OpenClash needs a configured HTTP or mixed port')
    assert(api, 'OpenClash needs a configured local controller port')
    local backend = http or mixed
    assert(backend ~= api, 'OpenClash proxy and controller ports must differ')
    return {backend_port=backend, api_port=api, proxy_kind=http and 'http' or 'mixed'}
end
function M.auth(cfg,uci)
    uci = uci or cursor()
    local ok, endpoint = pcall(M.discover,uci)
    if not ok or endpoint.api_port ~= cfg.api_port or endpoint.backend_port ~= cfg.backend_port then
        return nil,'OpenClash endpoints changed; apply settings again'
    end
    local secret = get(uci,'dashboard_password') or ''
    if type(secret) ~= 'string' or #secret > 256 or secret:find('%c') or secret:match('^%s') or secret:match('%s$') then
        return nil,'unsupported OpenClash controller authentication'
    end
    -- Empty upstream secret is allowed only on the hard-coded loopback socket.
    return secret == '' and '' or 'Authorization: Bearer '..secret
end
local function base64(value)
    local alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
    local result={}
    for i=1,#value,3 do
        local a,b,c=value:byte(i,i+2)
        local word=a*65536+(b or 0)*256+(c or 0)
        result[#result+1]=alphabet:sub(math.floor(word/262144)%64+1,math.floor(word/262144)%64+1)
            ..alphabet:sub(math.floor(word/4096)%64+1,math.floor(word/4096)%64+1)
            ..(b and alphabet:sub(math.floor(word/64)%64+1,math.floor(word/64)%64+1) or '=')
            ..(c and alphabet:sub(word%64+1,word%64+1) or '=')
    end
    return table.concat(result)
end
-- Read only already-enabled OpenClash HTTP credentials into listener memory.
-- No second saved password, config copy, cache, logging, or external mutation.
function M.proxy_authorization(uci)
    uci=uci or cursor()
    if type(uci.foreach)~='function' then return nil end
    local candidates={}
    uci:foreach('openclash','authentication',function(section)
        local user,password=section.username,section.password
        if section.enabled=='1' and type(user)=='string' and #user>0 and #user<=256
            and not user:find('[:%c]') and type(password)=='string' and #password>0
            and #password<=1024 and not password:find('%c') then
            candidates[#candidates+1]={name=user,header='Proxy-Authorization: Basic '..base64(user..':'..password)}
        end
    end)
    table.sort(candidates,function(a,b) return a.name<b.name end)
    if candidates[1] then return candidates[1].header,candidates[1].name end
end
function M.runtime(config,cfg)
    if type(config) ~= 'table' then return nil,'invalid OpenClash runtime state' end
    if config.mode ~= 'rule' and config.mode ~= 'global' and config.mode ~= 'direct' then
        return nil,'unknown OpenClash routing mode'
    end
    local key = cfg.proxy_kind == 'mixed' and 'mixed-port' or 'port'
    if config[key] ~= cfg.backend_port then return nil,'OpenClash runtime port differs; apply settings again' end
    -- /configs reports usernames only. Match the in-memory UCI credential;
    -- never treat its controller Bearer token as an HTTP proxy password.
    local auth = config.authentication
    if auth ~= nil and type(auth) ~= 'table' then return nil,'invalid OpenClash proxy authentication state' end
    if auth and next(auth) ~= nil then
        local exempt = false
        for _,prefix in ipairs(type(config['skip-auth-prefixes']) == 'table' and config['skip-auth-prefixes'] or {}) do
            if prefix == '127.0.0.1/32' or prefix == '127.0.0.0/8' or prefix == '127.0.0.1/8' then exempt = true end
        end
        if not exempt then
            local matched=false
            for _,user in ipairs(auth) do if user==cfg.proxy_username then matched=true end end
            if not matched or type(cfg.proxy_authorization)~='string' then
                return nil,'OpenClash proxy authentication unavailable; use an enabled matching OpenClash authentication entry or an explicit loopback exemption'
            end
        end
    end
    return config.mode
end
return M
