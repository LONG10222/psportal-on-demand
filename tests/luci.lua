-- No LuCI installation/router/network required. All side effects are mocked.
-- Run from the repository root: lua5.1 tests/luci.lua
local real_loadfile = loadfile
local real_open = io.open
local model_path = 'luci/model/cbi/portalproxy.lua'
local function equal(a, b) assert(a == b, tostring(a) .. ' ~= ' .. tostring(b)) end
local function identity(s) return s end
translate = identity
FORM_NODATA, FORM_VALID, FORM_INVALID = 0, 1, -1
DummyValue, Value, ListValue, Button, Table = 'dummy', 'value', 'list', 'button', 'table'
local scenario
local function field(self, kind, name, title, description)
    local f = {kind=kind, option=name, title=title, description=description, choices={}}
    function f:depends(key, value) self.dependency={key,value} end
    function f:value(key, label) self.choices[#self.choices+1] = {key, label} end
    self.fields[name] = f
    return f
end
function SimpleForm(name, title, description)
    local f = {config=name, title=title, description=description, fields={}, data={}}
    f.field = field
    function f:section(kind, rows) return {option=function() end, rows=rows} end
    function f:submitstate() return scenario.params['cbi.submit'] end
    return f
end
local function load(overrides)
    scenario = {method='GET', user='root', token='session-token', params={}, commands={}, writes={}, commit=0,
        options={selection_mode='auto', preferred_node='JP exact', subscription_url='https://private.example/token-secret'},
        snapshot={updated_at=os.time(), ready=false, current={name='JP exact',delay=42,path={'PORTAL','JP exact'}},
            nodes={{name='JP exact',delay=42,alive=true,selected=true},{name='bad\nname'}, {name='HK',alive=false}}}}
    for key, value in pairs(overrides or {}) do scenario[key] = value end
    package.loaded['luci.http'] = {
        status=function(code) scenario.status=code end,
        header=function() end,
        getenv=function() return scenario.method end,
        formvalue=function(key) return scenario.params[key] end,
        redirect=function(url) scenario.redirect=url end
    }
    package.loaded['luci.dispatcher'] = {context={authuser=scenario.user,authtoken=scenario.token},
        build_url=function() return '/cgi-bin/luci/admin/services/portalproxy' end}
    package.loaded['nixio.fs'] = {stat=function() return 4 end,chmod=function() return true end}
    package.loaded['luci.jsonc'] = {parse=function() return scenario.snapshot end}
    package.loaded['luci.sys'] = {call=function(command)
        scenario.commands[#scenario.commands+1] = command
        if scenario.callerror then error('hidden exception') end
        return scenario.exitcode or 0
    end}
    package.loaded['uci'] = {cursor=function() return {
        get_all=function() return scenario.options end,
        changes=function() return scenario.changes or {} end,
        set=function(_, config, section, key, value)
            equal(config, 'portalproxy'); equal(section, 'main')
            scenario.writes[key] = value
            return true
        end,
        commit=function() scenario.commit=scenario.commit+1; return true end
    } end}
    io.open = function(path)
        equal(path, '/tmp/portalproxy/nodes.json')
        return {read=function() return 'data' end,close=function() end}
    end
    loadfile = function(path)
        equal(path, '/usr/libexec/portalproxy/config.lua')
        return function() return {validate=function(config)
            scenario.validated = config
            if scenario.real_validation then
                package.path='src/?.lua;'..package.path
                return assert(real_loadfile('src/config.lua'))().validate(config)
            end
            assert(config.selection_mode=='auto' or config.selection_mode=='preferred' or config.selection_mode=='fixed')
            assert(config.subscription_url:match('^https://'))
            assert(config.selection_mode=='auto' or config.preferred_node~='')
        end} end
    end
    return assert(real_loadfile(model_path))()
end
local function post(action, token)
    scenario.method='POST'
    scenario.params={['cbi.submit']='1',token=token or scenario.token}
    scenario.params['cbid.portalproxy_ui.1.'..action]='clicked'
end

local f=load()
equal(#scenario.commands,0); equal(scenario.commit,0)
equal(f.fields._game_mode.kind, DummyValue)
assert(f.fields._game_mode.value:find('does not prove Internet access',1,true))
assert(f.fields._game_mode.value:find('Game UDP and whole-device routing are not provided',1,true))
assert(f.fields._game_mode.value:find('Turn off the device HTTP proxy when finished',1,true))
equal(f.fields.subscription_url:cfgvalue(), '')
assert(not f.description:find('token-secret',1,true))
assert(f.fields._status.value:find('Sleeping',1,true))
equal(#f.fields.preferred_node.choices,2)
equal(f.fields.preferred_node.default,'JP exact')
equal(f:handle(FORM_NODATA,{}),true); equal(#scenario.commands,0)
assert(f.fields._update.description:find('interrupt active Portal connections',1,true))

f=load({user='nobody'})
equal(scenario.status,403); equal(next(f.fields),nil); equal(f.handle,nil)

f=load(); post('_apply','wrong'); f:handle(FORM_VALID,{})
equal(scenario.status,403); equal(#scenario.commands,0)
f=load(); post('_apply'); scenario.method='GET'; f:handle(FORM_VALID,{})
equal(scenario.status,403); equal(#scenario.commands,0)
f=load(); post('_apply'); scenario.params['cbi.submit']=nil; f:handle(FORM_VALID,{})
equal(scenario.status,403); equal(#scenario.commands,0)
f=load(); post('_apply'); scenario.params['cbid.portalproxy_ui.1._update']='clicked'; f:handle(FORM_VALID,{})
equal(#scenario.commands,0)

f=load(); post('_save')
local data={selection_mode='auto',preferred_node='JP exact',subscription_url=''}
equal(f:handle(FORM_VALID,data),false)
equal(scenario.commit,1); equal(#scenario.commands,0)
equal(scenario.writes.preferred_node,'JP exact'); equal(scenario.writes.subscription_url,nil)
assert(scenario.redirect:find('result=saved',1,true))

f=load(); post('_save')
data={selection_mode='preferred',preferred_node='HK',subscription_url='https://new.example/secret'}
f:handle(FORM_VALID,data)
equal(scenario.commit,1); equal(scenario.writes.subscription_url,'https://new.example/secret')
equal(f.fields.subscription_url:cfgvalue(),''); equal(data.subscription_url,nil)
assert(not scenario.redirect:find('secret',1,true))

f=load(); post('_save'); data={selection_mode='fixed',preferred_node='',subscription_url='https://private.example/secret'}
f:handle(FORM_VALID,data)
equal(scenario.commit,0); equal(next(scenario.writes),nil); equal(data.subscription_url,nil)
assert(f.errmessage:find('No changes were saved',1,true))
f=load({changes={portalproxy={main={preferred_node='pending'}}}}); post('_save')
f:handle(FORM_VALID,{selection_mode='auto',preferred_node='HK'})
equal(scenario.commit,0); equal(next(scenario.writes),nil)

f=load(); post('_apply')
f:handle(FORM_VALID,{subscription_url='https://evil.example/; touch /tmp/bad',preferred_node='unsaved'})
equal(scenario.commit,0); equal(#scenario.commands,1)
equal(scenario.commands[1],'/usr/bin/lua /usr/libexec/portalproxy/render.lua >/dev/null 2>&1 && /etc/init.d/portalproxy restart >/dev/null 2>&1')
assert(scenario.redirect:find('result=applied',1,true))
f=load({exitcode=1}); post('_update'); f:handle(FORM_VALID,{})
equal(scenario.commit,0); equal(#scenario.commands,1)
equal(scenario.commands[1],'/usr/bin/lua /usr/libexec/portalproxy/update-subscription.lua >/dev/null 2>&1')
assert(scenario.redirect:find('result=update_failed',1,true))
f=load({callerror=true}); post('_apply'); f:handle(FORM_VALID,{})
assert(scenario.redirect:find('result=apply_failed',1,true))

f=load({snapshot={updated_at='bad',current='bad',nodes={false,{}, {name='safe'}}}})
assert(f.fields._status.value:find('stale cache',1,true))
equal(#f.fields.preferred_node.choices,1)
f=load({snapshot={updated_at=0/0}}); equal(f.fields._updated.value,'No cached status')
f=load({snapshot={updated_at=123.5}}); equal(f.fields._updated.value,'No cached status')
f=load({params={result='updated'}})
equal(#scenario.commands,0); assert(f.message:find('Subscription cache updated',1,true))
assert(f.message:find('change live routes',1,true))

f=load({options={core_mode='openclash',selection_mode='auto',preferred_node='',subscription_url=''},
    snapshot={core_mode='openclash',updated_at=os.time(),ready=true,route_policy='rule',groups={{name='GLOBAL',type='Selector',selected='DIRECT'}},nodes={}}})
equal(#scenario.commands,0); equal(scenario.commit,0)
equal(f.fields.subscription_url:cfgvalue(),''); equal(f.fields.subscription_url.dependency[2],'standalone'); equal(f.fields.preferred_node.dependency[2],'standalone'); equal(f.fields._current,nil)
equal(f.fields._update,nil); equal(f.fields._routing.value,'rule')
assert(f.fields._status.value:find('Internet and node health unknown',1,true))
assert(f.fields._openclash.value:find('OpenClash',1,true))
post('_update'); f:handle(FORM_VALID,{})
equal(#scenario.commands,0); equal(scenario.commit,0)
assert(scenario.redirect:find('result=update_failed',1,true))
f=load({options={core_mode='openclash'},snapshot={updated_at=os.time(),ready=true,current={name='old'}}})
assert(f.fields._status.value:find('stale cache',1,true))
equal(f.fields._current,nil)
f=load(); post('_save'); f:handle(FORM_VALID,{core_mode='openclash'})
equal(scenario.writes.core_mode,'openclash'); equal(scenario.writes.preferred_node,'JP exact')
equal(scenario.writes.subscription_url,nil); equal(#scenario.commands,0)

f=load({real_validation=true,options={core_mode='openclash',listen_ip='192.168.50.2',client_ip='192.168.50.30',local_dns='192.168.50.1'}})
post('_save'); f:handle(FORM_VALID,{core_mode='standalone',selection_mode='auto',subscription_url='https://fixture.example/profile'})
equal(scenario.commit,1); equal(scenario.writes.core_mode,'standalone')
equal(scenario.writes.subscription_url,'https://fixture.example/profile'); equal(#scenario.commands,0)

loadfile, io.open = real_loadfile, real_open
assert(loadfile('luci/controller/portalproxy.lua')) -- syntax only; no live controller
print('LuCI model: auth, CSRF, cached-only GET, secret hiding, saved preferences, actions and redirect tests passed')
