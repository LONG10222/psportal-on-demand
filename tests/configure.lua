-- Execute the real configuration entry point with isolated UCI/files.
package.path='src/?.lua;'..package.path
local options={core_mode='openclash',enabled='0'}
local writes,commits={},0
package.loaded.uci={cursor=function() return {
 get_all=function() return options end,get=function() return 'proxy' end,
 set=function(_,_,_,key,value) writes[key]=value; return true end,
 commit=function() commits=commits+1; return true end
} end}
package.loaded['nixio.fs']={chmod=function() return true end}
local old_open=io.open
io.open=function(path)
 assert(path=='fixture-input')
 local values={'192.168.50.2','192.168.50.30','192.168.50.1','','10081','60','','','0','openclash'}
 local index=0
 return {read=function() index=index+1; return values[index] end,close=function() end}
end
arg={[0]='src/configure.lua',[1]='fixture-input'}
assert(loadfile('src/configure.lua'))()
io.open=old_open
assert(commits==1 and writes.client_ip=='192.168.50.30')
assert(writes.enabled==nil, 'configuration must preserve service enable intent')
assert(package.loaded.openclash==nil, 'saving must not discover/contact external runtime')
print('Configuration: save-only setup preserves disabled state and never discovers external runtime')
