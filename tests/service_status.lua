package.path='src/?.lua;'..package.path
local object={test={instances={main={running=true,pid=1234}}}}
package.loaded['luci.jsonc']={parse=function() return object end}
local old_popen=io.popen
local calls=0
io.popen=function(command,mode)
    calls=calls+1
    assert(command==[[ubus -t 1 call service list '{"name":"test"}' 2>/dev/null]])
    assert(mode=='r')
    return {read=function(_,limit) assert(limit==65537);return 'fixture' end,close=function() end}
end
local service=require 'service_status'
assert(service.pid('test',false)==1234)
assert(service.pid('test',true)==1234)
object.test.instances.main.running=false
assert(service.pid('test',false)==nil)
object.test.instances.other={running=true,pid=2345}
assert(service.pid('test',true)==2345)
assert(service.pid('test; injected',true)==nil and calls==4)
object.test.instances.other.pid='2345'
assert(service.pid('test',true)==nil)
io.popen=old_popen
print('Service status: bounded separate ubus clients, ownership and shell-injection rejection passed')
