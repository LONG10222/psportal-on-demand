-- Local bounded status only: no sockets, probes, or service mutations.
local fs = require 'nixio.fs'
local json = require 'luci.jsonc'
local ownership = require 'startup_owner'
local M = {}
local function count(value)
    return type(value) == 'number' and value == value and value >= 0
        and value <= 9007199254740991 and value == math.floor(value) and value or 0
end
function M.clean(value)
    if type(value) ~= 'table' then return nil end
    local counters = type(value.counters) == 'table' and value.counters or {}
    local result = {core_mode=value.core_mode=='openclash' and 'openclash' or 'standalone',
        launcher_pid=count(value.launcher_pid), updated_at=count(value.updated_at),
        uptime_seconds=count(value.uptime_seconds), core_running=value.core_running==true,
        core_starting=value.core_starting==true, session_active=value.session_active==true,
        idle_seconds=count(value.idle_seconds), idle_timeout=count(value.idle_timeout),
        external_connections=count(value.external_connections), local_connections=count(value.local_connections),
        counters={}}
    for _, key in ipairs({'upload_bytes','download_bytes','external_requests','local_requests','denied_clients','starts','idle_stops'}) do
        result.counters[key] = count(counters[key])
    end
    return result
end
function M.read()
    local cfg = {run_dir='/tmp/portalproxy'}
    local generation = ownership.current(cfg)
    if not generation or not ownership.valid(cfg,generation) then return nil end
    local size = fs.stat(cfg.run_dir..'/status.json','size')
    if type(size) ~= 'number' or size > 65536 then return nil end
    local raw = fs.readfile(cfg.run_dir..'/status.json',65537)
    if not raw or #raw > 65536 then return nil end
    local ok, value = pcall(json.parse,raw)
    local result = ok and M.clean(value) or nil
    if not result or tostring(result.launcher_pid) ~= generation:match('^(%d+)%-') then return nil end
    result.stale = result.updated_at == 0 or os.time()-result.updated_at > 15 or result.updated_at > os.time()+5
    return result
end
return M
