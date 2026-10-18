-- Pure ownership/race tests: in-memory files and process identities only.
local directory=arg[0]:match('^(.*)/') or '.'
local count=0
local function check(value,message) assert(value,message); count=count+1 end
local function stat(pid,started,group,state)
    local fields={state or 'S','1',tostring(group or pid)}
    for i=4,19 do fields[i]='0' end
    fields[20]=tostring(started)
    return pid..' (lua (worker)) '..table.concat(fields,' ')..'\n'
end
local function fixture()
    local w={pid=100,files={},kills={},operations={}}
    local cfg={run_dir='/mock/run'}
    w.files['/proc/100/stat']=stat(100,1000)
    local function op(kind,path) w.operations[#w.operations+1]={kind=kind,path=path} end
    local fs={
        readfile=function(path) op('read',path); return w.files[path] end,
        writefile=function(path,value) op('write',path); if w.fail_write then return nil end; w.files[path]=value; return true end,
        stat=function(path) return w.files[path] and {size=#w.files[path]} or nil end,
        remove=function(path) op('remove',path); w.files[path]=nil; return true end,
        rename=function(a,b)
            op('rename',b)
            if w.before_publish then w.before_publish(a,b) end
            w.files[b]=w.files[a]; w.files[a]=nil; return true
        end}
    local n={const={SIGKILL=9,ESRCH=3},getpid=function() return w.pid end,
        kill=function(pid,signal) w.kills[#w.kills+1]={pid=pid,signal=signal}; if w.kill_error then return nil,w.kill_error end; return true end}
    local env={assert=assert,type=type,tonumber=tonumber,tostring=tostring,pairs=pairs,ipairs=ipairs,
        require=function(name) if name=='nixio' then return n end; assert(name=='nixio.fs'); return fs end}
    local chunk
    if setfenv then chunk=assert(loadfile(directory..'/../src/startup_owner.lua')); setfenv(chunk,env)
    else chunk=assert(loadfile(directory..'/../src/startup_owner.lua','t',env)) end
    return w,cfg,chunk()
end
local w,cfg,owner=fixture()
local generation=owner.begin(cfg)
check(generation=='100-1000','generation includes PID and Linux starttime')
check(owner.valid(cfg,generation),'new generation is valid')
w.pid=200; w.files['/proc/200/stat']=stat(200,2000)
check(owner.register(cfg,generation),'session leader worker registers')
check(w.files['/mock/run/startup-worker-'..generation]=='200 2000\n','worker identity persisted')
w.pid=100; check(owner.cancel(cfg),'cancellation succeeds')
check(w.files['/mock/run/stopping']~=nil,'cancellation marker remains until next generation')
check(not owner.valid(cfg,generation),'canceled generation cannot launch')
check(#w.kills==2 and w.kills[1].pid==-200 and w.kills[2].pid==200,'cancel kills worker group and PID')
check(w.files['/mock/run/startup-worker-'..generation]==nil,'canceled worker record removed')
local marker,record
for i,op in ipairs(w.operations) do
    if op.kind=='rename' and op.path=='/mock/run/stopping' then marker=i end
    if marker and op.kind=='read' and op.path=='/mock/run/startup-worker-'..generation then record=record or i end
end
check(marker and record and marker<record,'marker is published before cancellation reads worker')

w,cfg,owner=fixture(); generation=owner.begin(cfg)
w.pid=200; w.files['/proc/200/stat']=stat(200,2000); check(owner.register(cfg,generation),'worker registers before reuse test')
w.files['/proc/200/stat']=stat(200,9999)
owner.cancel(cfg)
check(#w.kills==0,'reused PID never receives signal')

w,cfg,owner=fixture(); generation=owner.begin(cfg)
w.files['/proc/100/stat']=stat(100,1000,100,'Z')
check(not owner.valid(cfg,generation),'zombie launcher is not a valid owner')
w.files['/proc/100/stat']=stat(100,1001)
check(not owner.valid(cfg,generation),'reused launcher PID invalidates old generation')
w.files['/proc/100/stat']=nil
check(not owner.valid(cfg,generation),'missing launcher invalidates ownership')

w,cfg,owner=fixture(); generation=owner.begin(cfg)
w.pid=200; w.files['/proc/200/stat']=stat(200,2000,100)
check(not owner.register(cfg,generation),'worker must first create a private process group')
check(w.files['/mock/run/startup-worker-'..generation]==nil,'failed registration publishes no record')

-- Pause old worker between initial validation and publication. Cancellation
-- sees no worker yet; replacement generation starts and publishes its record.
-- The old publication must then invalidate itself without touching successor.
w,cfg,owner=fixture(); generation=owner.begin(cfg)
w.pid=200; w.files['/proc/200/stat']=stat(200,2000)
local successor
w.before_publish=function(_,destination)
    if destination~='/mock/run/startup-worker-'..generation then return end
    w.before_publish=nil
    w.pid=100; owner.cancel(cfg)
    w.pid=300; w.files['/proc/300/stat']=stat(300,3000); successor=owner.begin(cfg)
    w.pid=400; w.files['/proc/400/stat']=stat(400,4000)
    check(owner.register(cfg,successor),'successor worker registers during old publish race')
    w.pid=200
end
check(not owner.register(cfg,generation),'late old registration fails after generation changes')
check(w.files['/mock/run/startup-worker-'..generation]==nil,'late old publication is removed')
check(w.files['/mock/run/startup-worker-'..successor]=='400 4000\n','old registration cannot overwrite successor record')
check(#w.kills==0,'late old registration never signals successor')
check(owner.valid(cfg,successor),'successor remains valid')
owner.clear(cfg,generation,200)
check(w.files['/mock/run/startup-worker-'..successor]=='400 4000\n','old reap cannot clear successor record')

w,cfg,owner=fixture(); generation=owner.begin(cfg)
w.fail_write=true
check(not pcall(owner.cancel,cfg),'cancellation marker write failure is visible')
check(#w.kills==0,'failed cancellation marker does not claim process cancellation')
w,cfg,owner=fixture(); generation=owner.begin(cfg)
w.pid=200; w.files['/proc/200/stat']=stat(200,2000); check(owner.register(cfg,generation),'worker registers before zombie test')
w.files['/proc/200/stat']=stat(200,2000,200,'Z')
owner.cancel(cfg)
check(#w.kills==2 and w.kills[1].pid==-200,'zombie worker leader still identifies descendants for group kill')

w,cfg,owner=fixture(); generation=owner.begin(cfg)
w.files['/mock/run/startup-worker-'..generation]='malformed record\n'
check(not pcall(owner.cancel,cfg),'malformed worker record fails cancellation visibly')
check(w.files['/mock/run/stopping']~=nil,'malformed record leaves cancellation marker in place')

w,cfg,owner=fixture(); generation=owner.begin(cfg)
w.files['/mock/run/startup-generation']='malformed generation\n'
check(not pcall(owner.cancel,cfg),'malformed generation fails cancellation visibly')

w,cfg,owner=fixture(); generation=owner.begin(cfg)
w.pid=200; w.files['/proc/200/stat']=stat(200,2000); check(owner.register(cfg,generation),'worker registers before kill failure')
w.kill_error=1
check(not pcall(owner.cancel,cfg),'failed process cancellation is visible')
check(#w.kills==2,'cancellation attempts both group and PID even if group kill fails')
print('Passed '..count..' startup ownership assertions')
