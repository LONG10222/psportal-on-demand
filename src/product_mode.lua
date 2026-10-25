-- Persisted game/accelerator workspace. No external core service is managed.
local M = {}
function M.valid(mode) return mode == 'game' or mode == 'accelerator' end
function M.switch(mode, deps)
    assert(M.valid(mode), 'Invalid workspace mode')
    deps = deps or {uci=require('uci').cursor(), fs=require('nixio.fs'), sys=require('luci.sys'), json=require('luci.jsonc')}
    local uci,fs=deps.uci,deps.fs
    local previous=uci:get('portalproxy','main','product_mode') or 'game'
    if previous == mode then return mode end
    if mode == 'accelerator' then
        assert(fs.access('/usr/libexec/rpcd/xianniu') and (fs.access('/www/luci-static/resources/view/xianniu_router/overview_v2.js') or fs.access('/www/luci-static/resources/view/xianniu_router/overview.js')),
            'Install the Xianniu router module first')
    end
    assert(fs.mkdir('/tmp/portalproxy-mode.lock','700'), 'Another mode change is in progress')
    local ok,err=pcall(function()
        assert(uci:set('portalproxy','main','product_mode',mode));assert(uci:commit('portalproxy'))
        assert(fs.chmod('/etc/config/portalproxy','600'))
    end)
    fs.rmdir('/tmp/portalproxy-mode.lock')
    if not ok then
        uci:set('portalproxy','main','product_mode',previous);uci:commit('portalproxy')
        error(err)
    end
    return mode
end
return M
