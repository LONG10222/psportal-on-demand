-- Authenticated status is read-only; every mutation requires POST and CSRF.
local calls,output,status,params,method,user,token
module=function() end
package.seeall=function() end
package.loaded['nixio.fs']={access=function() return true end}
package.loaded['luci.dispatcher']={context={}}
package.loaded['luci.http']={header=function() end,status=function(s) status=s end,
 getenv=function() return method end,formvalue=function(k) return params[k] end,
 prepare_content=function(t) assert(t=='application/json') end,write_json=function(v) output=v end}
package.loaded['luci.jsonc']={parse=function(v) assert(v=='safe json');return {ok=true} end}
package.loaded['luci.sys']={exec=function(command) calls[#calls+1]=command;return 'safe json' end}
assert(loadfile('luci/controller/portalproxy.lua'))()
local function run(m,u,p)
 calls={};status=nil;output=nil;method=m;user=u;params=p or {}
 package.loaded['luci.dispatcher'].context={authuser=u,authtoken='secret'}
 dashboard_api()
end
run('GET','guest');assert(status==403 and #calls==0)
run('POST','root',{operation='check-update'});assert(status==403 and #calls==0)
run('POST','root',{operation='install-update',token='wrong'});assert(status==403 and #calls==0)
run('GET','root',{operation='install-update'});assert(#calls==1 and calls[1]:find('monitor.py status',1,true))
run('PUT','root');assert(status==405 and #calls==0)
run('POST','root',{operation='check-update; malicious',token='secret'});assert(status==400 and #calls==0)
for _,op in ipairs({'check-update','install-update','subscriptions-refresh'}) do
 run('POST','root',{operation=op,token='secret'});assert(#calls==1 and output.ok)
end
print('Dashboard API: root, method, CSRF and fixed command routing passed')
