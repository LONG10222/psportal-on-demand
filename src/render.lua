#!/usr/bin/lua
local directory = arg[0]:match('^(.*)/') or '.'
package.path = directory .. '/?.lua;' .. package.path
local fs = require 'nixio.fs'
local n = require 'nixio'
local json = require 'luci.jsonc'
local config = require 'config'
n.umask('077')
local options = {}
local keys = {'core_mode','source_mode','openclash_source','listen_ip','client_ip','local_dns','listen_port','backend_port','api_port','dns_port','idle_seconds',
    'wakeup_timeout','health_interval','health_timeout','routing_mark','core_path',
    'selection_mode','preferred_node','subscription_url','subscription_user_agent','bootstrap_dns','health_url','doh_url'}
for _,key in ipairs(keys) do
    local f = assert(io.popen('uci -q get portalproxy.main.'..key..' 2>/dev/null'))
    local value = f:read('*a'):gsub('[\r\n]+$',''); f:close()
    if value ~= '' then options[key] = value end
end
local ok,err = pcall(function()
    options = require('openclash_source').apply(options)
    local validated = config.validate(options)
    if validated.core_mode == 'standalone' then
        if validated.core_path == '/usr/libexec/portalproxy/mihomo' and not fs.access(validated.core_path,'x') then
            for _,candidate in ipairs({'/usr/bin/mihomo','/etc/openclash/core/clash_meta'}) do
                if fs.access(candidate,'x') then options.core_path=candidate; break end
            end
        end
        assert(fs.access(options.core_path or validated.core_path,'x'),
            'Standalone core missing. Link existing OpenClash or install a compatible Mihomo; no service started')
    end
    local linked
    if validated.core_mode == 'openclash' then
        linked = require('openclash').discover(); config.render(options,nil,nil,linked)
    end
    if arg[1] == '--check' then print('Configuration is valid.'); return end
    fs.mkdir('/etc/portalproxy','700'); fs.mkdir('/etc/portalproxy/providers','700')
    assert(fs.chmod('/etc/portalproxy','700')); assert(fs.chmod('/etc/portalproxy/providers','700'))
    if linked then
        local _,policy = config.render(options,nil,nil,linked)
        local path = '/etc/portalproxy/policy.json'
        assert(fs.writefile(path..'.new',json.stringify(policy)))
        assert(fs.chmod(path..'.new','600')); assert(fs.rename(path..'.new',path))
        print('OpenClash linked policy written. External core and configuration unchanged.')
        return
    end
    local secret = fs.readfile('/etc/portalproxy/api-secret')
    if secret then secret = secret:gsub('%s+$','') end
    if not secret or not secret:match('^%x+$') or #secret ~= 64 then
        local random = assert(io.open('/dev/urandom','rb')); local bytes = assert(random:read(32)); random:close()
        secret = bytes:gsub('.',function(c) return string.format('%02x',c:byte()) end)
        assert(fs.writefile('/etc/portalproxy/api-secret',secret..'\n'))
    end
    assert(fs.chmod('/etc/portalproxy/api-secret','600'))
    local core,policy = config.render(options,secret)
    local core_yaml = config.to_yaml(core,json.stringify)
    for name,value in pairs({['config.yaml']=core_yaml,['policy.json']=json.stringify(policy),['api-header']='Authorization: Bearer '..secret..'\n'}) do
        local path = '/etc/portalproxy/'..name
        assert(fs.writefile(path..'.new',value)); assert(fs.chmod(path..'.new','600')); assert(fs.rename(path..'.new',path))
    end
    print('Runtime configuration written. No core started.')
end)
if not ok then io.stderr:write('Configuration error: '..tostring(err):gsub('^.-:%d+: ','')..'\n'); os.exit(1) end
