-- Generation-scoped ownership for readiness workers. Cancellation publishes its
-- marker before reading the worker record; workers publish before starting a
-- service and validate again afterward. Old generations cannot replace records
-- or stop services belonging to a replacement launcher.
local n = require 'nixio'
local fs = require 'nixio.fs'
local M = {}
local function path(cfg, name) return cfg.run_dir .. '/' .. name end
local function identity(pid)
    if not tostring(pid):match('^%d+$') or tonumber(pid)<2 then return nil end
    local stat=fs.readfile('/proc/'..pid..'/stat')
    if not stat or stat:match('^(%d+)')~=tostring(pid) then return nil end
    -- comm may itself contain spaces and parentheses; use the last close paren.
    local fields=stat:match('^%d+ %(.+%) (.+)$')
    if not fields then return nil end
    local values={}; for value in fields:gmatch('%S+') do values[#values+1]=value end
    local started,group=values[20],values[3] -- Linux stat fields 22 and 5.
    if not started or not started:match('^%d+$') or not group or not group:match('^%d+$') then return nil end
    return started,group,values[1]
end
local function decode(generation)
    if type(generation)~='string' then return nil end
    local pid,started=generation:match('^(%d+)%-(%d+)$')
    if not pid or tonumber(pid)<2 then return nil end
    return pid,started
end
local function atomic(file, value)
    local temporary=file..'.new.'..n.getpid()
    assert(fs.writefile(temporary,value),'cannot write startup ownership')
    assert(fs.rename(temporary,file),'cannot publish startup ownership')
end
local function record_path(cfg,generation)
    assert(decode(generation),'invalid startup generation')
    return path(cfg,'startup-worker-'..generation)
end
local function read_record(cfg,generation)
    local file=record_path(cfg,generation)
    local data=fs.readfile(file)
    if not data then return nil,nil,file end
    local pid,started=data:match('^(%d+) (%d+)\n$')
    if not pid or tonumber(pid)<2 then return nil,nil,file,true end
    return pid,started,file
end
function M.current(cfg,strict)
    local value=fs.readfile(path(cfg,'startup-generation'))
    if not value then return nil end
    value=value:gsub('\n$','')
    if not decode(value) then assert(not strict,'invalid startup generation record'); return nil end
    return value
end
function M.valid(cfg,generation)
    local pid,started=decode(generation)
    if not pid or fs.stat(path(cfg,'stopping')) then return false end
    local actual,_,state=identity(pid)
    return M.current(cfg)==generation and actual==started and state~='Z' and state~='X' and state~='x'
end
function M.begin(cfg)
    local pid=n.getpid()
    local started=assert(identity(pid),'cannot identify launcher process')
    local generation=pid..'-'..started
    atomic(path(cfg,'startup-generation'),generation..'\n')
    if fs.stat(path(cfg,'stopping')) then assert(fs.remove(path(cfg,'stopping')),'cannot clear startup cancellation') end
    return generation
end
function M.clear(cfg,generation,pid)
    if not decode(generation) then return end
    local recorded,_,file=read_record(cfg,generation)
    if recorded==tostring(pid) then fs.remove(file) end
end
function M.register(cfg,generation)
    if not M.valid(cfg,generation) then return false end
    local pid=n.getpid()
    local started,group=identity(pid)
    if not started or group~=tostring(pid) then return false end
    atomic(record_path(cfg,generation),pid..' '..started..'\n')
    if not M.valid(cfg,generation) then M.clear(cfg,generation,pid); return false end
    return true
end
function M.cancel(cfg)
    atomic(path(cfg,'stopping'),'stopping\n')
    local generation=M.current(cfg,true)
    if not generation then return true end
    local pid,started,file,invalid=read_record(cfg,generation)
    assert(not invalid,'invalid startup worker record')
    if not pid then return true end
    local actual,group=identity(pid)
    if actual==started and group==pid then
        -- Validate Linux starttime before signalling, never trust a stale PID.
        local group_ok,group_err=n.kill(-tonumber(pid),n.const.SIGKILL)
        local pid_ok,pid_err=n.kill(tonumber(pid),n.const.SIGKILL)
        assert(group_ok or group_err==n.const.ESRCH,'cannot cancel startup process group')
        assert(pid_ok or pid_err==n.const.ESRCH,'cannot cancel startup worker')
    end
    -- A late old-generation publish will fail register's second validation.
    M.clear(cfg,generation,pid)
    return true
end
return M
