-- Pure discovery/runtime fixtures. Never connects to a router or real UCI.
local directory=arg[0]:match('^(.*)/') or '.'
package.path=directory..'/../src/?.lua;'..package.path
local adapter=require 'openclash'
local config=require 'config'
local count=0
local function check(v,message) assert(v,message); count=count+1 end
local function rejects(fn,message) check(not pcall(fn),message) end
local base={enable='1',http_port='7890',mixed_port='7893',cn_port='9090',dashboard_password='private.test-token!@$'}
local function cursor(values,overwrite)
    return {get=function(_,package,section,key)
        check(package=='openclash','reads only OpenClash UCI')
        check(section=='config' or section=='@overwrite[0]','only known sections')
        return (section=='@overwrite[0]' and (overwrite or {}) or (values or base))[key]
    end}
end
local cfg=adapter.discover(cursor())
check(cfg.backend_port==7890 and cfg.api_port==9090 and cfg.proxy_kind=='http','HTTP preferred, controller discovered')
check(adapter.auth(cfg,cursor())=='Authorization: Bearer private.test-token!@$','punctuation preserved exactly')
check(adapter.auth(cfg,cursor(nil,{dashboard_password=''}))=='','explicit empty overwrite does not fall back to secret')
check(adapter.discover(cursor(nil,{http_port='0'})).backend_port==7893,'disabled HTTP falls back to mixed')
check(adapter.discover(cursor(nil,{http_port='',mixed_port='8900'})).backend_port==8900,'empty HTTP overwrite respected')
check(adapter.discover(cursor(nil,{http_port='8900',cn_port='9091'})).api_port==9091,'overwrite ports win')
for _,bad in ipairs({'0','-1','65536','1.5','http://127.0.0.1','7890;touch /tmp/no','nan','inf'}) do
    rejects(function() adapter.discover(cursor(nil,{http_port=bad,mixed_port='0'})) end,'invalid proxy port rejected')
    rejects(function() adapter.discover(cursor(nil,{cn_port=bad})) end,'invalid API port rejected')
end
rejects(function() adapter.discover(cursor({enable='0'})) end,'disabled OpenClash rejected')
rejects(function() adapter.discover(cursor(nil,{cn_port='7890'})) end,'proxy/API collision rejected')
for _,secret in ipairs({'x\r\nInjected: bad','x\0bad','x\tbad',' leading','trailing ',string.rep('a',257)}) do
    check(adapter.auth(cfg,cursor(nil,{dashboard_password=secret}))==nil,'unsafe secret fails before request')
end
check(adapter.auth(cfg,cursor(nil,{cn_port='9091'}))==nil,'changed controller cannot receive old credentials')
check(adapter.auth(cfg,cursor(nil,{http_port='8900'}))==nil,'changed proxy requires reapply')
for _,mode in ipairs({'rule','global','direct'}) do
    check(adapter.runtime({port=7890,mode=mode,authentication={}},cfg)==mode,'runtime routing mode retained')
end
check(not adapter.runtime({port=7891,mode='rule'},cfg),'runtime/UCI drift rejected')
check(not adapter.runtime({port=7890,mode='other'},cfg),'unknown routing mode rejected')
check(not adapter.runtime({port=7890,mode='rule',authentication={'do-not-copy:password'}},cfg),'proxy auth without loopback exception rejected')
for _,prefix in ipairs({'127.0.0.1/32','127.0.0.0/8','127.0.0.1/8'}) do
    check(adapter.runtime({port=7890,mode='rule',authentication={'user:secret'},['skip-auth-prefixes']={prefix}},cfg)=='rule','explicit loopback exemption supported')
end
check(not adapter.runtime({port=7890,mode='rule',authentication='not-a-list'},cfg),'malformed auth rejected')
local options={core_mode='openclash',listen_ip='192.168.50.2',client_ip='192.168.50.30',local_dns='192.168.50.1'}
local core,policy=config.render(options,nil,nil,cfg)
check(core==nil,'linked mode renders no owned core config')
check(policy.core_mode=='openclash' and policy.core_name=='openclash','linked policy has explicit ownership')
check(policy.core_service==nil and policy.api_header==nil and policy.secret==nil,'linked policy carries no service path or secret')
check(policy.backend_port==7890 and policy.api_port==9090 and policy.proxy_kind=='http','linked runtime ports are discovered')
check(policy.port==10081 and policy.allowed_ip==options.client_ip and policy.idle_seconds==60,'original client ACL and idle preserved')
options.listen_port='7890'
rejects(function() config.render(options,nil,nil,cfg) end,'listener/proxy collision rejected')
options.listen_port='9090'
rejects(function() config.render(options,nil,nil,cfg) end,'listener/controller collision rejected')
options.listen_port='18680'; options.backend_port='bad'; options.api_port='bad'; options.dns_port='bad'
options.subscription_url='old-invalid-placeholder'; options.selection_mode='fixed'; options.preferred_node=''
local _,dormant=config.render(options,nil,nil,cfg)
check(dormant.port==18680,'unused standalone ports/subscription/preference cannot block linked mode')
options.listen_port=nil; options.core_mode='typo'
rejects(function() config.validate(options) end,'unknown ownership rejected')
print('Passed '..count..' OpenClash discovery, ownership and runtime assertions')
