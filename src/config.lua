local M = {}
local protocol = require 'protocol'
local selection = require 'selection'
local subscription = require 'subscription'

function M.to_yaml(value,encode)
    -- json-c emits a JSON slash escape that some YAML readers reject.
    local text = encode(value):gsub('\\/','/')
    return text
end

local function integer(value,default,min,max,name)
    if value == nil or value == '' then value = default end
    local n = tonumber(value)
    assert(n and n == math.floor(n) and n >= min and n <= max, 'Invalid ' .. name)
    return n
end

local function ipv4(value,name)
    assert(protocol.ipv4(value), 'Invalid ' .. name .. ': enter an IPv4 address')
    return value
end

function M.validate(o)
    local c = {}
    c.core_mode = o.core_mode or 'standalone'
    assert(c.core_mode == 'standalone' or c.core_mode == 'openclash', 'Invalid core_mode')
    c.listen_ip = ipv4(o.listen_ip,'listen_ip')
    c.client_ip = ipv4(o.client_ip,'client_ip')
    assert(protocol.local_ip(c.listen_ip) and not c.listen_ip:match('^127%.'), 'listen_ip must be a LAN address')
    assert(protocol.local_ip(c.client_ip) and not c.client_ip:match('^127%.'), 'client_ip must be a LAN address')
    assert(c.listen_ip ~= c.client_ip, 'client_ip must differ from listen_ip')
    c.local_dns = ipv4(o.local_dns,'local_dns')
    c.listen_port = integer(o.listen_port,10081,1024,65535,'listen_port')
    c.idle_seconds = integer(o.idle_seconds,60,10,3600,'idle_seconds')
    c.wakeup_timeout = integer(o.wakeup_timeout,12,3,60,'wakeup_timeout')
    -- Dormant standalone settings must not constrain externally managed mode.
    if c.core_mode == 'openclash' then return c end
    c.backend_port = integer(o.backend_port,18680,1024,65535,'backend_port')
    c.api_port = integer(o.api_port,18681,1024,65535,'api_port')
    c.dns_port = integer(o.dns_port,18653,1024,65535,'dns_port')
    local seen = {}
    for _,p in ipairs({c.listen_port,c.backend_port,c.api_port,c.dns_port}) do
        assert(not seen[p], 'Ports must be distinct'); seen[p] = true
    end
    c.health_interval = integer(o.health_interval,60,15,3600,'health_interval')
    c.health_timeout = integer(o.health_timeout,5000,1000,15000,'health_timeout')
    c.subscription_interval = integer(o.subscription_interval,21600,3600,604800,'subscription_interval')
    c.routing_mark = integer(o.routing_mark,0,0,2147483647,'routing_mark')
    c.core_path = o.core_path or '/usr/libexec/portalproxy/mihomo'
    assert(c.core_path:match('^/[%w%._/%-]+$'), 'Invalid core_path')
    c.subscription_url = o.subscription_url or ''
    assert(not c.subscription_url:find('[%s%c]') and not c.subscription_url:find('REPLACE_ME',1,true), 'Set a real subscription_url locally')
    if c.core_mode == 'standalone' then c.subscription_host = subscription.validate_url(c.subscription_url).host end
    c.selection_mode,c.preferred_node = selection.validate(o.selection_mode,o.preferred_node)
    c.subscription_user_agent = subscription.validate_user_agent(o.subscription_user_agent)
    c.health_url = o.health_url or 'https://connectivitycheck.gstatic.com/generate_204'
    assert(c.health_url:match('^https://[^%s]+$'), 'health_url must use HTTPS')
    c.doh_url = o.doh_url or 'https://1.1.1.1/dns-query'
    assert(c.doh_url:match('^https://[^%s#]+$'), 'doh_url must use HTTPS without a fragment')
    c.bootstrap_dns = {}
    for ip in (o.bootstrap_dns or c.local_dns):gmatch('%S+') do c.bootstrap_dns[#c.bootstrap_dns+1] = ipv4(ip,'bootstrap_dns') end
    assert(#c.bootstrap_dns > 0, 'Set at least one bootstrap DNS server')
    return c
end

function M.render(options,secret,paths,linked)
    local c = M.validate(options)
    paths = paths or {data='/etc/portalproxy', run='/tmp/portalproxy', core_service='/etc/init.d/portalproxy-core', core_name='portalproxy-core'}
    if c.core_mode == 'openclash' then
        assert(type(linked) == 'table', 'OpenClash discovery required')
        local backend = integer(linked.backend_port,nil,1,65535,'OpenClash proxy port')
        local api = integer(linked.api_port,nil,1,65535,'OpenClash controller port')
        assert(c.listen_port ~= backend and c.listen_port ~= api and backend ~= api, 'OpenClash ports must differ from listener')
        assert(linked.proxy_kind == 'http' or linked.proxy_kind == 'mixed', 'Invalid OpenClash proxy kind')
        return nil,{core_mode='openclash',bind=c.listen_ip,port=c.listen_port,allowed_ip=c.client_ip,
            backend_port=backend,api_port=api,proxy_kind=linked.proxy_kind,
            local_dns=c.local_dns,idle_seconds=c.idle_seconds,wakeup_timeout=c.wakeup_timeout,
            core_name='openclash',run_dir=paths.run},c
    end
    assert(type(secret) == 'string' and #secret == 64 and secret:match('^%x+$'), 'Invalid management secret')
    local health = {enable=true,url=c.health_url,interval=c.health_interval,timeout=c.health_timeout,lazy=false,['expected-status']=204}
    -- Explicit pinned HTTPS downloads write a private node-provider cache.
    -- Mihomo watches file providers and may reload them while already running.
    local provider = {type='file',path='./providers/subscription.yaml',['health-check']=health,
        ['exclude-type']='direct|compatible|pass|dns',
        ['exclude-filter']='(?i)^(剩余流量|距离下次|套餐到期|到期时间|官网|更新订阅|Traffic|Expire|Reset)'}
    if c.routing_mark ~= 0 then provider.override = {['routing-mark']=c.routing_mark} end
    local core = {port=c.backend_port,['socks-port']=0,['mixed-port']=0,['redir-port']=0,['tproxy-port']=0,
        ['allow-lan']=false,['bind-address']='127.0.0.1',['lan-allowed-ips']={'127.0.0.1/32'},mode='rule',
        ['log-level']='warning',ipv6=false,['find-process-mode']='off',['external-controller']='127.0.0.1:'..c.api_port,
        secret=secret,profile={['store-selected']=false,['store-fake-ip']=false},tun={enable=false},sniffer={enable=false},
        dns={enable=true,listen='127.0.0.1:'..c.dns_port,ipv6=false,['enhanced-mode']='redir-host',
            -- json-c treats a repeated table reference as a cycle and emits null.
            ['default-nameserver']={unpack(c.bootstrap_dns)},['proxy-server-nameserver']={unpack(c.bootstrap_dns)},
            ['direct-nameserver']={unpack(c.bootstrap_dns)},
            ['nameserver-policy']={[c.subscription_host]={unpack(c.bootstrap_dns)}},nameserver={c.doh_url..'#PORTAL'}},
        ['proxy-providers']={SUBSCRIPTION=provider},
        ['proxy-groups']={selection.group(c)},
        rules=protocol.backend_reject_rules()}
    core.rules[#core.rules+1]='MATCH,PORTAL'
    if c.routing_mark ~= 0 then core['routing-mark'] = c.routing_mark end
    local policy = {core_mode='standalone',bind=c.listen_ip,port=c.listen_port,allowed_ip=c.client_ip,backend_port=c.backend_port,api_port=c.api_port,
        local_dns=c.local_dns,idle_seconds=c.idle_seconds,wakeup_timeout=c.wakeup_timeout,health_url=c.health_url,
        selection_mode=c.selection_mode,preferred_node=c.preferred_node,
        api_header=paths.data..'/api-header',core_name=paths.core_name,core_service=paths.core_service,run_dir=paths.run}
    return core,policy,c
end

return M
