package.path='src/?.lua;'..package.path
local source=require 'openclash_source'
local mode=require 'product_mode'
local writes,calls={},{}
local subscriptions={
 {['.name']='paid',name='My subscription',address='https://provider.example/sub?token=private-token',enabled='1'},
 {['.name']='disabled',name='Disabled',address='https://other.example/sub',enabled='0'},
 {['.name']='bad',name='Unsafe',address='http://not-https.example/sub'}
}
local u={}
function u:foreach(config,kind,fn) assert(config=='openclash' and kind=='config_subscribe');for _,s in ipairs(subscriptions) do fn(s) end end
function u:get(config,section,key)
 if config=='openclash' then for _,s in ipairs(subscriptions) do if s['.name']==section then return s[key] end end end
end
local rows=source.list(u);assert(#rows==1 and rows[1].id=='paid' and rows[1].address==nil)
assert(not rows[1].title:find('private%-token'))
local input={core_mode='standalone',source_mode='openclash',openclash_source='paid'}
local got=source.apply(input,u)
assert(got.subscription_url==subscriptions[1].address and input.subscription_url==nil)
assert(not pcall(source.apply,{source_mode='openclash',openclash_source='gone'},u))
assert(not pcall(source.apply,{source_mode='invalid'},u))
assert(source.apply({source_mode='manual',subscription_url='manual'},u).subscription_url=='manual')
-- No OpenClash enable/start requirement and no write method on the cursor.
assert(got.subscription_user_agent=='clash.meta')
local current,enabled,installed,running='game','1',true,false
local d={uci={},fs={},sys={},json={}}
function d.uci:get(_,_,key) if key=='product_mode' then return current elseif key=='enabled' then return enabled end end
function d.uci:set(c,s,k,v) assert(c=='portalproxy' and s=='main' and k=='product_mode');current=v;writes[#writes+1]=v;return true end
function d.uci:commit(c) assert(c=='portalproxy');return true end
function d.fs.access() return installed end
function d.fs.readfile() return '{}' end
function d.fs.mkdir() return true end
function d.fs.rmdir() return true end
function d.fs.chmod() return true end
function d.json.parse() return {running=running} end
function d.sys.call(c) assert(c:match('^/etc/init.d/portalproxy '));calls[#calls+1]=c;return 0 end
assert(mode.switch('accelerator',d)=='accelerator' and current=='accelerator')
assert(#calls==1 and calls[1]:find(' stop ',1,true))
assert(mode.switch('accelerator',d)=='accelerator' and #calls==1)
running=true;assert(not pcall(mode.switch,'game',d));assert(#calls==1 and current=='accelerator')
running=false;assert(mode.switch('game',d)=='game' and #calls==3)
assert(calls[3]:find(' start ',1,true))
installed=false;assert(not pcall(mode.switch,'accelerator',d));assert(current=='game' and #calls==3)
assert(not pcall(mode.switch,'clash',d));assert(current=='game')
enabled='0';installed=true;mode.switch('accelerator',d);mode.switch('game',d);assert(#calls==5)
print('Workspace/source tests: read-only disabled-OpenClash import, private metadata, saved mode, owned lifecycle and active-session exclusion passed')
