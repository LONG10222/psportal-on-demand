#!/usr/bin/lua
local directory = arg[0]:match('^(.*)/') or '.'
package.path = directory .. '/?.lua;' .. package.path
local fs = require 'nixio.fs'
local uci = require 'uci'.cursor()
local config = require 'config'
local f = assert(io.open(assert(arg[1]),'r'))
local values = {}
local keys = {'listen_ip','client_ip','local_dns','bootstrap_dns','listen_port','idle_seconds','subscription_url','seed_file','routing_mark','core_mode'}
for _,key in ipairs(keys) do values[key] = f:read('*l') or '' end
f:close()
local ok,err = pcall(function()
    local options = uci:get_all('portalproxy','main') or {}
    for _,key in ipairs(keys) do if key ~= 'seed_file' and values[key] ~= '' then options[key] = values[key] end end
    config.validate(options)
    if options.core_mode=='openclash' then config.render(options,nil,nil,require('openclash').discover()) end
    local seed
    if options.core_mode~='openclash' and values.seed_file ~= '' then
        local st = fs.stat(values.seed_file)
        assert(st and st.type == 'reg' and st.size > 0 and st.size <= 5242880, 'Seed must be a regular Clash/Mihomo YAML file, at most 5 MiB')
        seed = assert(fs.readfile(values.seed_file))
    end
    if not uci:get('portalproxy','main') then uci:section('portalproxy','proxy','main',{}) end
    for _,key in ipairs(keys) do if key ~= 'seed_file' and values[key] ~= '' then uci:set('portalproxy','main',key,values[key]) end end
    uci:set('portalproxy','main','enabled','1')
    assert(uci:commit('portalproxy'))
    assert(fs.chmod('/etc/config/portalproxy','600'))
    if seed then
        fs.mkdir('/etc/portalproxy','700'); fs.mkdir('/etc/portalproxy/providers','700')
        assert(fs.writefile('/etc/portalproxy/providers/subscription.yaml',seed))
        assert(fs.chmod('/etc/portalproxy/providers/subscription.yaml','600'))
    end
end)
if not ok then io.stderr:write('Setup failed: '..tostring(err):gsub('^.-:%d+: ','')..'\n'); os.exit(1) end
