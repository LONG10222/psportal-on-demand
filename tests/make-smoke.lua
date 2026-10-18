local fs=require 'nixio.fs'
local n=require 'nixio'
local json=require 'luci.jsonc'
local d,base,tag,idle=arg[1],arg[2],arg[3],assert(tonumber(arg[4]))
for port=21081,21084 do
    local socket=assert(n.bind('127.0.0.1',port,'inet','stream'),'Fixture port '..port..' is occupied')
    socket:close()
end
local function shell(s) return "'"..s:gsub("'","'\\''").."'" end
local function write(path,text) assert(fs.writefile(path,text));assert(fs.chmod(path,'700')) end
local health='https://connectivitycheck.gstatic.com/generate_204'
local core_name='portalproxy-smoke-core-'..tag
local lan_name='portalproxy-smoke-lan-'..tag
local listener_name='portalproxy-smoke-listener-'..tag
fs.mkdir(d..'/run','700')
write(d..'/fixture.json',json.stringify({backend_port=21082,api_port=21083,lan_port=21084,health_url=health}))
write(d..'/api-header','Authorization: Bearer test-only-fixture\n')
write(d..'/policy.json',json.stringify({bind='127.0.0.1',port=21081,allowed_ip='127.0.0.1',backend_port=21082,
    api_port=21083,api_header=d..'/api-header',local_dns='127.0.0.1',idle_seconds=idle,wakeup_timeout=8,
    core_name=core_name,core_service=d..'/'..core_name,run_dir=d..'/run',health_url=health}))
local function service(name,command,stop)
    local script='#!/bin/sh /etc/rc.common\nSTART=99\nSTOP=10\nUSE_PROCD=1\nstart_service() {\n procd_open_instance main\n procd_set_param command '..command..'\n procd_set_param term_timeout 2\n procd_set_param stdout 1\n procd_set_param stderr 1\n procd_close_instance\n}\n'
    if stop then script=script..'stop_service() {\n local cancellation=0\n /usr/bin/lua '..shell(base..'/src/cancel-startup.lua')..' '..shell(d..'/run')..' || cancellation=$?\n '..shell(stop)..' stop || return $?\n return "$cancellation"\n}\n' end
    write(d..'/'..name,script)
end
service(core_name,'/usr/bin/lua '..shell(base..'/tests/fixture.lua')..' core '..shell(d..'/fixture.json'))
service(lan_name,'/usr/bin/lua '..shell(base..'/tests/fixture.lua')..' lan '..shell(d..'/fixture.json'))
service(listener_name,'/usr/bin/lua '..shell(base..'/src/ondemand.lua')..' '..shell(d..'/policy.json'),d..'/'..core_name)
