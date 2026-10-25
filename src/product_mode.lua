-- Persisted game/accelerator workspace. No external core service is managed.
local M = {}
function M.valid(mode) return mode == 'game' or mode == 'accelerator' end
function M.switch(mode, deps)
    assert(M.valid(mode), 'Invalid workspace mode')
    deps = deps or {uci=require('uci').cursor(), fs=require('nixio.fs'), sys=require('luci.sys'), json=require('luci.jsonc')}
    local uci,fs,sys=deps.uci,deps.fs,deps.sys
    local previous=uci:get('portalproxy','main','product_mode') or 'game'
    if previous == mode then return mode end
    if mode == 'accelerator' then
        assert(fs.access('/usr/libexec/rpcd/xianniu') and (fs.access('/www/luci-static/resources/view/xianniu_router/overview_v2.js') or fs.access('/www/luci-static/resources/view/xianniu_router/overview.js')),
            'Install the Xianniu router module first')
    else
        local raw=fs.readfile('/var/run/xianniu-router.json')
        local ok,state=pcall(deps.json.parse,raw or '')
        assert(not (ok and type(state)=='table' and state.running), 'Stop Xianniu acceleration before switching modes')
    end
    assert(fs.mkdir('/tmp/portalproxy-mode.lock','700'), 'Another mode change is in progress')
    local ok,err=pcall(function()
        assert(sys.call('/etc/init.d/portalproxy stop >/dev/null 2>&1')==0, 'Cannot stop the owned listener')
        assert(uci:set('portalproxy','main','product_mode',mode));assert(uci:commit('portalproxy'))
        assert(fs.chmod('/etc/config/portalproxy','600'))
        if mode=='game' and uci:get('portalproxy','main','enabled')=='1' then
            assert(sys.call('/etc/init.d/portalproxy start >/dev/null 2>&1')==0, 'Game listener failed to start')
        end
    end)
    fs.rmdir('/tmp/portalproxy-mode.lock')
    if not ok then
        uci:set('portalproxy','main','product_mode',previous);uci:commit('portalproxy')
        if previous=='game' and uci:get('portalproxy','main','enabled')=='1' then sys.call('/etc/init.d/portalproxy start >/dev/null 2>&1') end
        error(err)
    end
    return mode
end
return M
