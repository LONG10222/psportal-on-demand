#!/usr/bin/lua
-- Root/SSH UI: cache reads never start or renew the core.
local directory=arg[0]:match('^(.*)/') or '.'
package.path=directory..'/?.lua;'..package.path
local n=require 'nixio'
local fs=require 'nixio.fs'
local json=require 'luci.jsonc'
local uci=require 'uci'.cursor()
local selection=require 'selection'
local action=arg[1] or 'list'
local ok=pcall(function()
    assert(n.getuid()==0,'root required'); n.umask('077')
    if action=='set' then
        assert(uci:get('portalproxy','main','core_mode')~='openclash','Manage linked nodes in OpenClash')
        local mode,name=selection.validate(arg[2],arg[3])
        assert(uci:get('portalproxy','main'),'Run setup first')
        uci:set('portalproxy','main','selection_mode',mode)
        if arg[3] then uci:set('portalproxy','main','preferred_node',name) end
        assert(uci:commit('portalproxy')); assert(fs.chmod('/etc/config/portalproxy','600'))
        print('Preference saved. Run portalproxy apply to activate (disconnects existing sessions).'); return
    end
    assert(action=='list' or action=='refresh','Invalid command')
    local cfg=json.parse(fs.readfile('/etc/portalproxy/policy.json') or '')
    assert(cfg,'Run setup first')
    local status=require 'node_status'
    local snapshot
    if action=='refresh' then
        if cfg.core_mode~='openclash' then
        local t=require 'luci.util'.ubus('service','list',{name=cfg.core_name}) or {}
        local i=t[cfg.core_name] and t[cfg.core_name].instances
        assert(i and i.main and i.main.running,'Core is sleeping; refresh does not wake it')
        end
        snapshot=assert(status.collect(cfg)); assert(status.write(cfg,snapshot))
    else snapshot=status.read(cfg) end
    if cfg.core_mode=='openclash' then
        print('Core mode: OpenClash linked (read-only; external core is unmanaged)')
        print('Manage subscriptions and node choices in OpenClash. Rules may select DIRECT.')
        if not snapshot then print('No matching cached snapshot; use nodes-refresh while OpenClash is running.'); return end
        print('Cached snapshot, not a live test: '..tostring(snapshot.updated_at))
        print('Routing mode: '..(snapshot.route_policy or 'unavailable'))
        print('Endpoint readiness at snapshot: '..(snapshot.ready and 'available (not an Internet test)' or 'unavailable'))
        if snapshot.reason then print('Reason: '..snapshot.reason) end
        for _,group in ipairs(snapshot.groups or {}) do print(group.name..' | '..group.type..' | '..(group.selected or 'dynamic/unresolved')) end
        if not snapshot.nodes_available then print('Node list unavailable; endpoint readiness is separate'); return end
        print('Node names: '..tostring(#snapshot.nodes)..'; no single actual exit or latency is implied')
        return
    end
    print('Mode: '..(uci:get('portalproxy','main','selection_mode') or 'auto'))
    local preferred=uci:get('portalproxy','main','preferred_node') or ''
    if #preferred<=256 and not preferred:find('%c') then print('Preferred: '..preferred) end
    if not snapshot then print('No cached node data. Connect once, then refresh while the core is running.'); return end
    print('Cached snapshot (not a live test), updated: '..tostring(snapshot.updated_at))
    print('Actual node at snapshot: '..(snapshot.current and snapshot.current.name or 'unavailable'))
    local found=false
    for _,node in ipairs(snapshot.nodes or {}) do
        if node.name==preferred then found=true end
        print(node.name..' | '..(node.alive and tostring(node.delay)..' ms' or 'unavailable/untested'))
    end
    if preferred~='' and not found then print('Preferred name absent from snapshot: deleted, renamed, or stale cache. Fixed mode fails closed.') end
end)
if not ok then io.stderr:write('Node operation failed. Check configuration, permissions and core status; no secrets were printed.\n'); os.exit(1) end
