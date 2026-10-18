-- Pure configuration contracts: no router, core, network or service executes.
local directory=arg[0]:match('^(.*)/') or '.'
package.path=directory..'/../src/?.lua;'..package.path
local selection=require 'selection'
local count=0
local function check(value,message) assert(value,message); count=count+1 end
local function rejects(fn,message) local ok=pcall(fn); check(not ok,message) end
local function eq(actual,expected,message) check(actual==expected,message) end
local function options(mode,name)
    return {selection_mode=mode,preferred_node=name,
        health_url='https://connectivitycheck.example.test/generate_204',health_interval=60,health_timeout=5000}
end
local function split(value)
    local result={}
    for part in (value..'`'):gmatch('(.-)`') do result[#result+1]=part end
    return result
end
local mode,name=selection.validate()
eq(mode,'auto','default mode is auto'); eq(name,'','default preferred node is empty')
for _,item in ipairs({'HK 01','日本 🇯🇵 2','Hong Kong [BGP] + 1.5x','US\\New York','a/#?&=%:!@;\"\''}) do
    for _,value in ipairs({'auto','preferred','fixed'}) do
        local m,n=selection.validate(value,item)
        eq(m,value,'preserve accepted mode'); eq(n,item,'preserve name literally')
    end
end
for _,value in ipairs({'fastest','manual','','AUTO',true,1,{}}) do
    rejects(function() selection.validate(value,'HK 01') end,'unknown mode rejected')
end
for _,value in ipairs({'preferred','fixed'}) do
    rejects(function() selection.validate(value,'') end,'non-auto needs a name')
    rejects(function() selection.validate(value) end,'non-auto cannot omit name')
end
for _,value in ipairs({'DIRECT','REJECT','COMPATIBLE','PASS','GLOBAL','PORTAL','Direct','reject-drop','RejectDrop','DNS','Dns','d i r e c t','P_O_R_T_A_L'}) do
    rejects(function() selection.validate('preferred',value) end,'reserved target rejected')
end
for byte=0,31 do
    rejects(function() selection.validate('fixed','HK'..string.char(byte)..'01') end,'control byte rejected')
end
rejects(function() selection.validate('preferred','HK'..string.char(127)) end,'DEL rejected')
for byte=128,159 do
    rejects(function() selection.validate('fixed','HK'..string.char(194,byte)) end,'Unicode C1 control rejected')
end
for byte=168,174 do
    rejects(function() selection.validate('fixed','HK'..string.char(226,128,byte)) end,'Unicode line or bidi control rejected')
end
for byte=166,169 do
    rejects(function() selection.validate('fixed','HK'..string.char(226,129,byte)) end,'Unicode bidi isolate rejected')
end
rejects(function() selection.validate('preferred','HK`.*') end,'filter separator injection rejected')
rejects(function() selection.validate('fixed',string.rep('x',257)) end,'overlong name rejected')
eq(select(2,selection.validate('fixed',string.rep('x',256))),string.rep('x',256),'bounded name accepted')
for _,value in ipairs({{},1,true}) do
    rejects(function() selection.validate('fixed',value) end,'non-string name rejected')
end
eq(selection.exact('HK 01'),'^HK 01$','exact name anchored')
eq(selection.exact('HK.+*?[](){}^$|\\'),'^HK\\.\\+\\*\\?\\[\\]\\(\\)\\{\\}\\^\\$\\|\\\\$','all regex metacharacters escaped')
eq(selection.exact('日本 🇯🇵 / 2-x_#'),'^日本 🇯🇵 / 2-x_#$','ordinary punctuation and Unicode preserved')
eq(selection.exact('(?i).*|DIRECT'),'^\\(\\?i\\)\\.\\*\\|DIRECT$','regex mode and alternative injection neutralized')
local auto=selection.group(options('auto','previous choice'))
eq(auto.name,'PORTAL','stable group identity'); eq(auto.type,'fallback','auto is ordered fallback')
eq(auto.filter,selection.default_filter,'auto ignores remembered preferred name')
local regions=split(auto.filter)
eq(#regions,4,'auto has three node tiers and one rejection tier')
eq(regions[1],'(?i)香港|🇭🇰|\\bHK\\b|Hong[ -]?Kong','Hong Kong filter first')
eq(regions[2],'(?i)日本|东京|大阪|🇯🇵|\\bJP\\b|Japan','Japan filter second')
eq(regions[3],'^(?!REJECT$).*','other region tier excludes static reject')
eq(regions[4],'^REJECT$','reject sentinel comes last')
local preferred=selection.group(options('preferred','US [Fast]+1'))
eq(preferred.type,'fallback','preferred keeps fallback behavior')
local tiers=split(preferred.filter)
eq(#tiers,5,'preferred adds one exact tier')
eq(tiers[1],'^US \\[Fast\\]\\+1$','preferred exact tier first')
for i=1,4 do eq(tiers[i+1],regions[i],'preferred keeps regional and rejection order') end
local fixed=selection.group(options('fixed','US [Fast]+1'))
eq(fixed.type,'select','fixed never falls through to another healthy node')
eq(fixed.filter,'^US \\[Fast\\]\\+1$`^REJECT$','fixed admits exact name and reject sentinel')
eq(#split(fixed.filter),2,'fixed has no catchall or regional tiers')
for _,group in ipairs({auto,preferred,fixed}) do
    eq(group.proxies[1],'REJECT','all modes have explicit fail-closed sentinel')
    eq(#group.proxies,1,'static proxy list contains only reject sentinel')
    eq(group['empty-fallback'],'REJECT','empty filtered provider requests rejection')
    eq(group['disable-udp'],true,'group UDP remains disabled')
    eq(group.use[1],'SUBSCRIPTION','only controlled provider selected')
    eq(#group.use,1,'one controlled provider only')
    eq(group['exclude-type'],'Direct|Compatible|Pass|Dns','direct and non-proxy types excluded after filtering')
    eq(group.url,options().health_url,'health URL preserved')
    eq(group['expected-status'],204,'health check requires expected status')
    eq(group.interval,60,'health interval preserved')
    eq(group.timeout,5000,'health timeout preserved')
    eq(group.lazy,false,'health checks do not depend on UI viewing')
end
auto.use[1]='MUTATED'; auto.proxies[1]='MUTATED'
eq(preferred.use[1],'SUBSCRIPTION','group provider arrays do not alias')
eq(preferred.proxies[1],'REJECT','group sentinel arrays do not alias')
eq(selection.group(options('auto')).use[1],'SUBSCRIPTION','later renders are unaffected')
print('Passed '..count..' pure selection/configuration assertions (no core executed)')
