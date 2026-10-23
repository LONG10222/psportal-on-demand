package.path='src/?.lua;'..package.path
local generation='1234-5678'
local value
package.loaded['nixio.fs']={stat=function() return 42 end,readfile=function() return 'fixture' end}
package.loaded['luci.jsonc']={parse=function() return value end}
package.loaded.startup_owner={current=function() return generation end,valid=function() return generation~=nil end}
local status=require 'runtime_status'
assert(status.clean(nil)==nil)
value={launcher_pid=1234,updated_at=os.time(),uptime_seconds=15,external_connections=2,local_connections=1,
    core_mode='openclash',core_running=true,counters={upload_bytes=123,download_bytes=456,secret='must disappear'}}
local cleaned=status.read()
assert(cleaned and not cleaned.stale and cleaned.external_connections==2 and cleaned.uptime_seconds==15)
assert(cleaned.counters.upload_bytes==123 and cleaned.counters.download_bytes==456 and cleaned.counters.secret==nil)
value.counters.upload_bytes=-1; value.counters.download_bytes=0/0
assert(status.read().counters.upload_bytes==0 and status.read().counters.download_bytes==0)
value.updated_at=os.time()-30
assert(status.read().stale)
value.launcher_pid=9999
assert(status.read()==nil, 'stale/reused PID must not appear live')
generation=nil
assert(status.read()==nil, 'stopped listener must not appear live')
print('Runtime status: live ownership, stale snapshots, bounded counters and secret exclusion passed')
