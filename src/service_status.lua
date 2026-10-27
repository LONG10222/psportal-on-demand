-- Each query executes a bounded ubus client. luci.util.ubus caches a connection
-- and event-loop descriptors which must not be shared across forked readiness
-- workers: competing readers can freeze both processes indefinitely.
local json=require 'luci.jsonc'
local M={}
function M.pid(name,external)
    if type(name)~='string' or #name>64 or not name:match('^[%w_%-]+$') then return nil end
    local pipe=io.popen("ubus -t 1 call service list '{\"name\":\""..name.."\"}' 2>/dev/null",'r')
    if not pipe then return nil end
    local raw=pipe:read(65537);pipe:close()
    if not raw or #raw>65536 then return nil end
    local ok,value=pcall(json.parse,raw)
    local instances=ok and type(value)=='table' and type(value[name])=='table' and value[name].instances
    if type(instances)~='table' then return nil end
    local function pid(instance)
        local value=type(instance)=='table' and instance.running==true and instance.pid
        return type(value)=='number' and value>1 and value==math.floor(value) and value or nil
    end
    if external then
        for _,instance in pairs(instances) do local value=pid(instance);if value then return value end end
    else return pid(instances.main) end
end
return M
