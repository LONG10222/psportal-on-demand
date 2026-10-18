local M = {}
local protocol = require 'protocol'

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
    c.listen_ip = ipv4(o.listen_ip,'listen_ip')
    c.client_ip = ipv4(o.client_ip,'client_ip')
    assert(protocol.local_ip(c.listen_ip) and not c.listen_ip:match('^127%.'), 'listen_ip must be a LAN address')
    assert(protocol.local_ip(c.client_ip) and not c.client_ip:match('^127%.'), 'client_ip must be a LAN address')
    assert(c.listen_ip ~= c.client_ip, 'client_ip must differ from listen_ip')
    c.local_dns = ipv4(o.local_dns,'local_dns')
    c.listen_port = integer(o.listen_port,10081,1024,65535,'listen_port')
    c.backend_port = integer(o.backend_port,18680,1024,65535,'backend_port')
    c.api_port = integer(o.api_port,18681,1024,65535,'api_port')
    c.dns_port = integer(o.dns_port,18653,1024,65535,'dns_port')
    local seen = {}
    for _,p in ipairs({c.listen_port,c.backend_port,c.api_port,c.dns_port}) do
        assert(not seen[p], 'Ports must be distinct'); seen[p] = true
    end
    c.idle_seconds = integer(o.idle_seconds,60,10,3600,'idle_seconds')
    c.wakeup_timeout = integer(o.wakeup_timeout,12,3,60,'wakeup_timeout')
    c.health_interval = integer(o.health_interval,60,15,3600,'health_interval')
    c.health_timeout = integer(o.health_timeout,5000,1000,15000,'health_timeout')
    c.subscription_interval = integer(o.subscription_interval,21600,3600,604800,'subscription_interval')
    c.routing_mark = integer(o.routing_mark,0,0,2147483647,'routing_mark')
    c.core_path = o.core_path or '/usr/libexec/portalproxy/mihomo'
    assert(c.core_path:match('^/[%w%._/%-]+$'), 'Invalid core_path')
    c.subscription_url = o.subscription_url or ''
    assert(not c.subscription_url:find('[%s%c]') and not c.subscription_url:find('REPLACE_ME',1,true), 'Set a real subscription_url locally')
    local authority = c.subscription_url:match('^https://([^/%?#]+)')
    assert(authority and not authority:find('@',1,true), 'subscription_url must use HTTPS without userinfo')
    local host,port = authority:match('^([%w%.%-]+):(%d+)$')
    if not host then assert(not authority:find(':',1,true), 'Invalid subscription port'); host=authority end
    assert(host:match('^[%w%.%-]+$') and #host<=253, 'Invalid subscription host')
    if port then integer(port,nil,1,65535,'subscription port') end
    c.subscription_host = host
    c.subscription_user_agent = o.subscription_user_agent or 'clash.meta'
    assert(#c.subscription_user_agent < 256 and not c.subscription_user_agent:find('[\r\n]'), 'Invalid subscription_user_agent')
    c.health_url = o.health_url or 'https://connectivitycheck.gstatic.com/generate_204'
    assert(c.health_url:match('^https://[^%s]+$'), 'health_url must use HTTPS')
    c.doh_url = o.doh_url or 'https://1.1.1.1/dns-query'
    assert(c.doh_url:match('^https://[^%s#]+$'), 'doh_url must use HTTPS without a fragment')
    c.bootstrap_dns = {}
    for ip in (o.bootstrap_dns or c.local_dns):gmatch('%S+') do c.bootstrap_dns[#c.bootstrap_dns+1] = ipv4(ip,'bootstrap_dns') end
    assert(#c.bootstrap_dns > 0, 'Set at least one bootstrap DNS server')
    return c
end

function M.render(options,secret,paths)
    local c = M.validate(options)
    assert(type(secret) == 'string' and #secret == 64 and secret:match('^%x+$'), 'Invalid management secret')
    paths = paths or {data='/etc/portalproxy', run='/tmp/portalproxy', core_service='/etc/init.d/portalproxy-core', core_name='portalproxy-core'}
    local health = {enable=true,url=c.health_url,interval=c.health_interval,timeout=c.health_timeout,lazy=false,['expected-status']=204}
    local provider = {type='http',url=c.subscription_url,path='./providers/subscription.yaml',interval=c.subscription_interval,proxy='DIRECT',
        ['size-limit']=5242880,header={['User-Agent']={c.subscription_user_agent}},['health-check']=health,
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
        ['proxy-groups']={{name='PORTAL',type='fallback',use={'SUBSCRIPTION'},
            filter='(?i)香港|🇭🇰|\\bHK\\b|Hong[ -]?Kong`(?i)日本|东京|大阪|🇯🇵|\\bJP\\b|Japan`.*',
            url=c.health_url,['expected-status']=204,interval=c.health_interval,timeout=c.health_timeout,
            ['max-failed-times']=2,lazy=false,['empty-fallback']='REJECT',['disable-udp']=true}},
        rules=protocol.backend_reject_rules()}
    core.rules[#core.rules+1]='MATCH,PORTAL'
    if c.routing_mark ~= 0 then core['routing-mark'] = c.routing_mark end
    local policy = {bind=c.listen_ip,port=c.listen_port,allowed_ip=c.client_ip,backend_port=c.backend_port,api_port=c.api_port,
        local_dns=c.local_dns,idle_seconds=c.idle_seconds,wakeup_timeout=c.wakeup_timeout,health_url=c.health_url,
        api_header=paths.data..'/api-header',core_name=paths.core_name,core_service=paths.core_service,run_dir=paths.run}
    return core,policy,c
end

return M
