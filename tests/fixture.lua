local n = require 'nixio'
n.signal(n.const.SIGPIPE,'ign')
local fs = require 'nixio.fs'
local json = require 'luci.jsonc'
local c = assert(json.parse(assert(fs.readfile(arg[2]))))
local listeners = {}
local function listen(port,role)
    local s=assert(n.bind('127.0.0.1',port,'inet','stream')); assert(s:listen(16))
    listeners[#listeners+1]={fd=s,events=n.poll_flags('in'),role=role}
end
if arg[1]=='lan' then listen(c.lan_port,'lan') else listen(c.backend_port,'backend');listen(c.api_port,'api') end
while true do
    local ready=n.poll(listeners,1000)
    if ready and ready>0 then for _,l in ipairs(listeners) do
        if n.bit.band(l.revents or 0,n.poll_flags('in'))~=0 then
            local s=l.fd:accept()
            if s then
                s:setopt('socket','rcvtimeo',1)
                local request=''
                for _=1,8 do local data=s:recv(8192);if not data or data=='' then break end;request=request..data;if request:find('\r\n\r\n',1,true) then break end end
                local status,body='204 No Content',''
                if l.role=='lan' then status,body='200 OK','LAN fixture\n'
                elseif l.role=='api' then
                    status='200 OK'
                    body=json.stringify({proxies={PORTAL={type='Fallback',now='HK fixture',all={'HK fixture'}},
                        ['HK fixture']={type='Shadowsocks',extra={[c.health_url]={alive=true,history={{delay=1}}}}}}})
                end
                local response='HTTP/1.1 '..status..'\r\nContent-Length: '..#body..'\r\nConnection: close\r\n\r\n'..body
                local offset=0
                while offset<#response do local written=s:send(response,offset);if not written then break end;offset=offset+written end
                s:close()
            end
        end
    end end
end
