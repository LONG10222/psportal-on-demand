-- Native form() dispatch supplies session/POST/CSRF checks. SimpleForm avoids
-- exposing subscription changes in Map's generic UCI diff/error views.
local http = require 'luci.http'
local dispatcher = require 'luci.dispatcher'
local fs = require 'nixio.fs'
local json = require 'luci.jsonc'
local sys = require 'luci.sys'

local form = SimpleForm('portalproxy_ui', translate('StarPass / 星渡'),
    translate('Viewing this page reads a local snapshot only. It does not start the core, probe nodes, or keep the core awake. Save settings first, then explicitly apply them when connections may be interrupted.'))
form.submit = false
form.reset = false

-- Enforce root identity also on LuCI versions converting legacy metadata to a
-- new dispatcher tree. Do not read any settings before this check.
if not dispatcher.context or dispatcher.context.authuser ~= 'root' then
    http.status(403, 'Forbidden')
    form.errmessage = translate('A root LuCI login is required.')
    return form
end
http.header('Cache-Control', 'no-store')

local cursor = require('uci').cursor()
local options = cursor:get_all('portalproxy', 'main') or {}
local linked = options.core_mode == 'openclash'
local game_mode = form:field(DummyValue, '_game_mode', translate('Game mode / 游戏模式'))
game_mode.value = translate('Game-device sharing (HTTP/TCP). Configure the allowed device, start the service, then enter this router address and proxy port in the device manual HTTP proxy settings. Verify a webpage on the device before testing the intended game feature. Listener ready or a connection does not prove Internet access. Game UDP and whole-device routing are not provided. Turn off the device HTTP proxy when finished.')
local core_mode = form:field(ListValue, 'core_mode', translate('Core ownership'),
    translate('Standalone starts and stops its own core. OpenClash linked reuses the already running external core; final DNS, rules and DIRECT choices stay with OpenClash. Idle closes only StarPass sessions. HTTP sharing does not carry game UDP.'))
core_mode:value('standalone', translate('Standalone on-demand core'))
core_mode:value('openclash', translate('OpenClash linked (read-only)'))
core_mode.default = options.core_mode or 'standalone'
core_mode.rmempty = false
if linked then
    local manage = form:field(DummyValue, '_openclash', translate('Subscription and node management'))
    manage.value = translate('Use Services → OpenClash. This page never changes its subscriptions, selectors, rules, service or firewall.')
end
local function plain(value)
    return type(value) == 'string' and #value <= 256
        and not value:find('%c') and value or nil
end
local function latency(value)
    return type(value) == 'number' and value > 0 and value < 3600000
        and math.floor(value) .. ' ms' or translate('Unknown')
end

-- Accept only the sanitized schema, never raw JSON, runtime configuration,
-- core API replies, URL fields, or decoder errors. Bound file and list sizes.
local snapshot = {}
do
    local path = '/tmp/portalproxy/nodes.json'
    local size = fs.stat(path, 'size')
    if type(size) == 'number' and size <= 1048576 then
        local file = io.open(path, 'rb')
        if file then
            local raw = file:read(1048577)
            file:close()
            if raw and #raw <= 1048576 then
                local ok, value = pcall(json.parse, raw)
                if ok and type(value) == 'table' then snapshot = value end
            end
        end
    end
end
if (snapshot.core_mode == 'openclash') ~= linked then snapshot = {} end
local updated = type(snapshot.updated_at) == 'number' and snapshot.updated_at or nil
if updated and (updated ~= updated or updated < 0 or updated > os.time() + 300
    or updated ~= math.floor(updated)) then updated = nil end
local stale = not updated or os.time() - updated > 120
local state = snapshot.ready == true and translate('Ready at last snapshot')
    or translate('Sleeping or not ready at last snapshot')
if linked then state = snapshot.ready == true and translate('OpenClash endpoint available at snapshot; Internet and node health unknown') or translate('OpenClash endpoint unavailable at snapshot') end
if stale then state = state .. ' / ' .. translate('stale cache') end
local status = form:field(DummyValue, '_status', translate('Cached core state'))
status.value = state
local timestamp = form:field(DummyValue, '_updated', translate('Snapshot time'))
timestamp.value = updated and os.date('!%Y-%m-%d %H:%M:%S UTC', updated) or translate('No cached status')
if not linked then
local current = type(snapshot.current) == 'table' and snapshot.current or {}
local actual = form:field(DummyValue, '_current', translate('Actual node at last snapshot'))
actual.value = (plain(current.name) or translate('Unknown')) .. ' / ' .. latency(current.delay)
local path = {}
if type(current.path) == 'table' then
    for i, name in ipairs(current.path) do
        if i > 16 then break end
        if plain(name) then path[#path + 1] = name end
    end
end
local route = form:field(DummyValue, '_path', translate('Cached selection path'))
route.value = #path > 0 and table.concat(path, ' > ') or translate('Unknown')

else
    local routing = form:field(DummyValue, '_routing', translate('OpenClash routing mode at snapshot'))
    routing.value = (snapshot.route_policy == 'rule' or snapshot.route_policy == 'global' or snapshot.route_policy == 'direct') and snapshot.route_policy or translate('Unknown')
    local rows = {}
    for i, group in ipairs(type(snapshot.groups) == 'table' and snapshot.groups or {}) do
        if i > 256 then break end
        if type(group) == 'table' and plain(group.name) and plain(group.type) then
            rows[#rows+1] = {name=group.name,type=group.type,selected=plain(group.selected) or translate('Dynamic / unknown')}
        end
    end
    local groups = form:section(Table, rows, translate('OpenClash groups (cached, read-only)'), translate('A group selection is not proof of the exit used by a particular request. Refresh explicitly with portalproxy nodes-refresh; page views never contact the core.'))
    groups:option(DummyValue, 'name', translate('Group'))
    groups:option(DummyValue, 'type', translate('Type'))
    groups:option(DummyValue, 'selected', translate('Selected member'))
end

local saved = form:field(DummyValue, '_saved', translate('Saved preference'))
saved:depends('core_mode','standalone')
saved.value = plain(options.preferred_node) and options.preferred_node ~= ''
    and options.preferred_node or translate('None')
local subscription = form:field(Value, 'subscription_url', translate('Replace HTTPS subscription URL'),
    translate('Input is hidden and never filled from the stored URL. Leave empty to keep the current subscription. Save before using Update subscription.'))
subscription:depends('core_mode','standalone')
subscription.password = true
subscription.rmempty = true
subscription.maxlength = 8192
-- Standard Value renders cfgvalue/default. Never repopulate a posted secret,
-- including after an unrelated field fails validation.
function subscription.cfgvalue() return '' end
function subscription.remove() end
function subscription.validate(self, value)
    if type(value) ~= 'string' or #value > 8192 then
        return nil, translate('Enter a valid HTTPS subscription URL.')
    end
    return value
end

local mode = form:field(ListValue, 'selection_mode', translate('Selection mode'))
mode:depends('core_mode','standalone')
mode:value('auto', translate('Automatic regional fallback'))
mode:value('preferred', translate('Preferred node, with automatic fallback'))
mode:value('fixed', translate('Fixed node only (fail closed)'))
mode.default = options.selection_mode or 'auto'
mode.rmempty = false
local preferred = form:field(Value, 'preferred_node', translate('Preferred / fixed node name'),
    translate('Choose a cached name or enter the exact name, including case and spaces. The name is retained in automatic mode. Fixed mode rejects external traffic if the node is missing or unavailable; it never silently uses another node.'))
preferred:depends('core_mode','standalone')
preferred.default = plain(options.preferred_node) or ''
preferred.maxlength = 256
preferred.rmempty = true
local node_rows = {}
local seen = {}
if type(snapshot.nodes) == 'table' then
    for i, node in ipairs(snapshot.nodes) do
        if i > 1000 then break end
        if type(node) == 'table' then
            local name = plain(node.name)
            if name and name ~= '' and not seen[name] then
                seen[name] = true
                local health = node.alive == true and translate('Available at snapshot')
                    or node.alive == false and translate('Unavailable at snapshot') or translate('Unknown')
                preferred:value(name, name .. ' / ' .. latency(node.delay) .. ' / ' .. health)
                node_rows[#node_rows + 1] = {name = name, delay = latency(node.delay),
                    health = health, selected = node.selected == true and translate('Yes') or translate('No')}
            end
        end
    end
end
local nodes = form:section(Table, node_rows, translate('Cached nodes'),
    translate('These are historical values. A sleeping core is not contacted to refresh this list.'))
nodes:option(DummyValue, 'name', translate('Name'))
nodes:option(DummyValue, 'delay', translate('Delay'))
nodes:option(DummyValue, 'health', translate('Cached health'))
nodes:option(DummyValue, 'selected', translate('Selected at snapshot'))

local function button(name, label, description)
    local value = form:field(Button, name, label, description)
    value.inputtitle = label
    value.inputstyle = name == '_save' and 'save' or 'apply'
    -- Button parsing never executes an action before complete form validation.
    function value.write() end
    function value.remove() end
end
button('_save', translate('Save settings (no restart)'),
    translate('Save to UCI without restarting the listener or waking the core. Running connections keep their current configuration until Apply or the next service start.'))
button('_apply', translate('Apply saved settings and restart listener'),
    translate('Uses saved settings only; unsaved edits are ignored. Restarts the StarPass listener and stops its owned core, interrupting Portal sessions. An external OpenClash core is never restarted or stopped.'))
if not linked then button('_update', translate('Update subscription now'),
    translate('Downloads the cache using the saved URL without starting the core. A running core may automatically reload the changed file, switch live routes, and interrupt active Portal connections.')) end

-- Post/redirect/get prevents a browser refresh from repeating a service action.
-- Fixed result messages only; no submitted value enters a redirect.
local results = {
    saved = translate('Settings saved. The listener was not restarted. Apply saved settings when interrupting active connections is acceptable.'),
    applied = translate('Saved settings applied and listener restarted. Standalone remains on demand; linked mode leaves OpenClash running unchanged.'),
    updated = translate('Subscription cache updated. A running core may reload it and change live routes. The status below may still show the previous snapshot.')
}
local errors = {
    apply_failed = translate('Could not apply saved settings. Check the saved configuration and local service status.'),
    update_failed = translate('Subscription update did not complete. Check the saved configuration and local service status.')
}
if http.getenv('REQUEST_METHOD') == 'GET' then
    local result = http.formvalue('result')
    form.message = results[result]
    form.errmessage = errors[result]
end
local function completed(result)
    http.redirect(dispatcher.build_url('admin', 'services', 'portalproxy') .. '?result=' .. result)
    return false
end

function form.handle(self, state, data)
    local replacement = data.subscription_url
    data.subscription_url = nil
    if state == FORM_NODATA then return true end
    local token = dispatcher.context.authtoken
    if http.getenv('REQUEST_METHOD') ~= 'POST' or not self:submitstate()
        or type(token) ~= 'string' or token == '' or http.formvalue('token') ~= token then
        http.status(403, 'Forbidden')
        self.errmessage = translate('Invalid form submission. Reload the page and try again.')
        return true
    end
    local action, count
    count = 0
    for _, name in ipairs({'_save', '_apply', '_update'}) do
        if http.formvalue('cbid.portalproxy_ui.1.' .. name) then
            action = name
            count = count + 1
        end
    end
    if count ~= 1 then
        self.errmessage = translate('Choose exactly one action.')
        return true
    end
    if action == '_save' then
        if state ~= FORM_VALID then return true end
        local candidate = {}
        for key, value in pairs(options) do candidate[key] = value end
        candidate.core_mode = data.core_mode or options.core_mode or 'standalone'
        candidate.selection_mode = data.selection_mode or options.selection_mode or 'auto'
        candidate.preferred_node = data.preferred_node or options.preferred_node or ''
        if replacement and replacement ~= '' then candidate.subscription_url = replacement end
        local ok = pcall(function()
            package.path = '/usr/libexec/portalproxy/?.lua;' .. package.path
            local config = assert(loadfile('/usr/libexec/portalproxy/config.lua'))()
            config.validate(candidate)
        end)
        if not ok then
            self.errmessage = translate('Settings are invalid. Check the HTTPS URL, mode, exact node name, and existing Portal configuration. No changes were saved.')
            return true
        end
        local changes = cursor:changes('portalproxy')
        if type(changes) == 'table' and next(changes) then
            self.errmessage = translate('Other pending Portal UCI changes exist. Apply or discard those changes before saving here.')
            return true
        end
        local committed = pcall(function()
            assert(cursor:set('portalproxy', 'main', 'core_mode', candidate.core_mode))
            assert(cursor:set('portalproxy', 'main', 'selection_mode', candidate.selection_mode))
            assert(cursor:set('portalproxy', 'main', 'preferred_node', candidate.preferred_node))
            if replacement and replacement ~= '' then
                assert(cursor:set('portalproxy', 'main', 'subscription_url', candidate.subscription_url))
            end
            assert(cursor:commit('portalproxy'))
            assert(fs.chmod('/etc/config/portalproxy', '600'))
        end)
        if not committed then
            self.errmessage = translate('Could not finish saving settings. Check local configuration permissions before retrying.')
            return true
        end
        return completed('saved')
    elseif action == '_apply' then
        local ok, code = pcall(sys.call, '/usr/bin/lua /usr/libexec/portalproxy/render.lua >/dev/null 2>&1 && /etc/init.d/portalproxy restart >/dev/null 2>&1')
        return completed(ok and code == 0 and 'applied' or 'apply_failed')
    elseif action == '_update' then
        if linked then return completed('update_failed') end
        local ok, code = pcall(sys.call, '/usr/bin/lua /usr/libexec/portalproxy/update-subscription.lua >/dev/null 2>&1')
        return completed(ok and code == 0 and 'updated' or 'update_failed')
    end
    return true
end

return form
