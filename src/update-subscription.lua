#!/usr/bin/lua
-- Explicit, one-shot cache update. This program never starts, contacts or stops
-- the core. A running core's file watcher may reload the replaced cache and
-- change routes. No subscription URL is accepted on the command line.
local directory=arg[0]:match('^(.*)/') or '.'
package.path=directory..'/?.lua;'..package.path
local n=require 'nixio'
local fs=require 'nixio.fs'
local subscription=require 'subscription'
local stage='initialization'
local temporary,body
n.umask('077')

local function write_all(fd,data)
    local offset=0
    while offset<#data do
        local size=fd:write(data,offset)
        assert(size and size>0, 'Cannot write private subscription file')
        offset=offset+size
    end
    return true
end

-- Both libc DNS resolution and curl are supervised. curl's own timeout does
-- not bound a separate blocking libc getaddrinfo(), so it gets its own child.
local function capture(work,seconds,receive)
    local reader,writer=n.pipe()
    assert(reader and writer, 'Cannot create subscription pipe')
    local pid=n.fork()
    if not pid then reader:close(); writer:close(); error('Cannot create subscription worker') end
    if pid==0 then
        reader:close()
        local ok=pcall(function()
            local null=assert(n.open('/dev/null','r+'))
            assert(n.dup(null,n.stdin)); assert(n.dup(writer,n.stdout)); assert(n.dup(null,n.stderr))
            null:close(); writer:close()
            work()
        end)
        os.exit(ok and 0 or 1)
    end
    writer:close()
    local finished,exit_ok,eof=false,false,false
    local ok=pcall(function()
        assert(reader:setblocking(false), 'Cannot configure subscription pipe')
        local deadline=assert(n.sysinfo()).uptime+seconds
        while not (finished and eof) do
            assert(n.sysinfo().uptime<deadline, 'Subscription operation timed out')
            if not eof then
                local count,err=n.poll({{fd=reader,events=n.poll_flags('in','hup','err')}},200)
                assert(count or err==n.const.EINTR, 'Subscription pipe poll failed')
                if count and count>0 then
                    local chunk,read_error=reader:read(8192)
                    if chunk=='' then eof=true
                    elseif chunk then receive(chunk)
                    else assert(read_error==n.const.EAGAIN or read_error==n.const.EINTR,
                        'Subscription pipe read failed') end
                end
            else n.nanosleep(0,100000000) end
            if not finished then
                local done,kind,code=n.waitpid(pid,'nohang')
                assert(done~=nil, 'Cannot wait for subscription worker')
                if done and done~=0 then
                    finished=true; exit_ok=kind=='exited' and code==0
                end
            end
        end
    end)
    reader:close()
    if not finished then
        -- This is our unreaped direct child, so its PID cannot have been reused.
        n.kill(pid,n.const.SIGKILL)
        n.waitpid(pid)
    end
    return ok and exit_ok
end

local function private_directory(path)
    local st=fs.lstat(path)
    if not st then assert(fs.mkdir(path,'700'), 'Cannot create private subscription directory'); st=fs.lstat(path) end
    assert(st and st.type=='dir' and st.uid==0, 'Unsafe subscription directory')
    assert(fs.chmod(path,'700'), 'Cannot restrict subscription directory')
end

local function main()
    assert(not arg[1], 'Subscription update takes no arguments')
    assert(n.getuid()==0, 'Subscription update requires root')
    local uci=require 'uci'.cursor()
    assert(uci:get('portalproxy','main','core_mode')~='openclash','Manage linked subscriptions in OpenClash')
    stage='configuration validation'
    local options={subscription_url=uci:get('portalproxy','main','subscription_url'),
        subscription_user_agent=uci:get('portalproxy','main','subscription_user_agent')}
    subscription.validate_url(options.subscription_url)
    subscription.validate_user_agent(options.subscription_user_agent)
    assert(fs.access('/usr/bin/curl','x'), 'curl is required')
    print('A running core may reload updated nodes and change routes; pause active gaming before updating.')
    stage='private cache preparation'
    private_directory('/etc/portalproxy')
    private_directory('/etc/portalproxy/providers')
    local random=assert(n.open('/dev/urandom','r'))
    local bytes=assert(random:read(16)); random:close()
    assert(#bytes==16, 'Cannot create private subscription name')
    local suffix=bytes:gsub('.',function(c) return string.format('%02x',c:byte()) end)
    local candidate='/etc/portalproxy/providers/.update-'..suffix
    assert(fs.mkdir(candidate,'700'), 'Cannot create private subscription workspace')
    temporary=candidate
    local config_path=temporary..'/request.conf'
    local body_path=temporary..'/body'
    body=assert(n.open(body_path,n.open_flags('wronly','creat','excl'),'600'))
    local size=subscription.update(options,{
        resolve=function(host)
            stage='DNS lookup and destination policy'
            local output=''
            assert(capture(function()
                local records=n.getaddrinfo(host,'inet')
                local ip=subscription.validate_addresses(records)
                write_all(n.stdout,ip)
            end,subscription.DNS_SECONDS,function(chunk)
                assert(#output+#chunk<=15, 'Invalid DNS worker result')
                output=output..chunk
            end), 'Subscription DNS lookup failed')
            return {{family='inet',address=output}}
        end,
        fetch=function(configuration,receive)
            stage='HTTPS transfer'
            local file=assert(n.open(config_path,n.open_flags('wronly','creat','excl'),'600'))
            local ok=pcall(write_all,file,configuration)
            local closed=file:close()
            assert(ok and closed, 'Cannot write private curl configuration')
            return capture(function()
                -- -q MUST be first. Empty inherited environment excludes proxy,
                -- CA override, SSL key-log and user curl-configuration variables.
                n.exece('/usr/bin/curl',{'-q','--config',config_path},{PATH='/usr/bin:/bin',LC_ALL='C'})
                error('Cannot execute curl')
            end,subscription.TRANSFER_SECONDS,receive)
        end,
        write=function(chunk) return write_all(body,chunk) end,
        commit=function(expected)
            stage='cache replacement'
            local st=body:stat()
            assert(st and st.type=='reg' and st.size==expected and expected<=subscription.MAX_BYTES,
                'Invalid subscription cache size')
            assert(body:sync(), 'Cannot sync subscription cache')
            assert(body:close(), 'Cannot close subscription cache'); body=nil
            assert(fs.chmod(body_path,'600'), 'Cannot restrict subscription cache')
            -- Same-directory filesystem: either old complete file or new one.
            return fs.rename(body_path,'/etc/portalproxy/providers/subscription.yaml')
        end
    })
    print('Subscription cache updated ('..size..' bytes). Sleeping core not awakened; running core may reload/change routes.')
    print('Transport checks passed; provider/YAML validity is not guaranteed. Mihomo may reject malformed content.')
end

local ok=pcall(main)
if body then body:close() end
if temporary then
    fs.remove(temporary..'/request.conf'); fs.remove(temporary..'/body'); fs.rmdir(temporary)
end
if not ok then
    -- Never print raw exceptions, curl diagnostics, response content or the URL.
    io.stderr:write('Subscription update failed during '..stage..'; existing cache retained.\n')
    os.exit(1)
end
