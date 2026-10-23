-- Read only this application's bounded log. Never echo exception bodies.
local path='/tmp/portalproxy/events.log'
local file=io.open(path,'r')
if not file then print('No StarPass events yet.'); return end
local size=file:seek('end') or 0
file:seek('set',math.max(0,size-65536))
if size>65536 then file:read('*l') end
local raw=file:read(65536) or '';file:close()
local lines={}
for line in raw:gmatch('[^\r\n]+') do
    local timestamp,event=line:match('^([%d%-:TZ]+) ([a-z_]+)')
    if timestamp and #timestamp<=32 and event then
        local entry=timestamp..' '..event
        local reason=line:match(' reason=([a-z_]+)')
        if reason and #reason<=64 then entry=entry..' reason='..reason end
        local seconds=line:match(' external_idle_seconds=(%d+)')
        if seconds and #seconds<=10 then entry=entry..' external_idle_seconds='..seconds end
        lines[#lines+1]=entry
    end
end
for index=math.max(1,#lines-39),#lines do print(lines[index]) end
