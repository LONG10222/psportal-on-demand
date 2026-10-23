-- Native form() dispatch supplies session/POST/CSRF checks. SimpleForm avoids
-- exposing subscription changes in Map's generic UCI diff/error views.
local http = require 'luci.http'
local dispatcher = require 'luci.dispatcher'
local fs = require 'nixio.fs'
local json = require 'luci.jsonc'
local sys = require 'luci.sys'

local form = SimpleForm('portalproxy_ui', translate('星渡 StarPass'),
    translate('游戏设备的 HTTP/TCP 代理共享。'))
form.submit = false
form.reset = false
form.template = 'portalproxy/dashboard'
form.portal_fields = {}
local function field(kind, name, ...)
    local value = form:field(kind, name, ...)
    form.portal_fields[name] = value
    return value
end

-- Enforce root identity also on LuCI versions converting legacy metadata to a
-- new dispatcher tree. Do not read any settings before this check.
if not dispatcher.context or dispatcher.context.authuser ~= 'root' then
    http.status(403, 'Forbidden')
    form.errmessage = translate('请使用 root 登录 LuCI。')
    return form
end
http.header('Cache-Control', 'no-store')

local cursor = require('uci').cursor()
local options = cursor:get_all('portalproxy', 'main') or {}
local linked = options.core_mode == 'openclash'
package.path = '/usr/libexec/portalproxy/?.lua;' .. package.path
local runtime
do
    local ok, status = pcall(require, 'runtime_status')
    if ok then
        local read_ok, state = pcall(status.read)
        if read_ok then runtime = state end
    end
end
local live = field(DummyValue, '_listener', translate('共享状态'))
live.value = runtime and (runtime.stale and translate('状态已过期，请检查服务') or translate('共享中 · 外网待验证'))
    or translate('已停止')
if runtime then
    local connections = field(DummyValue, '_connections', translate('连接与运行时长'))
    connections.value = string.format('%d 个外网连接 / %d 个局域网连接 · %d 秒', runtime.external_connections, runtime.local_connections, runtime.uptime_seconds)
    local traffic = field(DummyValue, '_traffic', translate('设备上传 / 下载'))
    traffic.value = string.format('%.0f 字节 / %.0f 字节', runtime.counters.upload_bytes, runtime.counters.download_bytes)
end
local network = cursor:get_all('network', 'lan') or {}
local network_fields = {'listen_ip', 'client_ip', 'local_dns', 'listen_port', 'idle_seconds', 'bootstrap_dns'}
local definitions = {
    {'listen_ip', '路由器地址', network.ipaddr and network.ipaddr:match('^[^/]+') or ''},
    {'client_ip', '允许接入的设备 IP', ''},
    {'local_dns', '局域网 DNS', (network.gateway or network.ipaddr or ''):match('^[^/]+') or ''},
    {'listen_port', '代理端口', '10081'},
    {'idle_seconds', '空闲回收（秒）', '60'},
    {'bootstrap_dns', '引导 DNS（可选）', ''}
}
local game_mode = field(DummyValue, '_game_mode', translate('接入帮助'))
game_mode.template = 'portalproxy/onboarding'
game_mode.value = translate('Game-device sharing (HTTP/TCP). Configure the allowed device, start the service, then enter this router address and proxy port in the device manual HTTP proxy settings. Verify a webpage on the device before testing the intended game feature. Listener ready or a connection does not prove Internet access. Game UDP and whole-device routing are not provided. Turn off the device HTTP proxy when finished.')
local core_mode = field(ListValue, 'core_mode', translate('核心模式'))
core_mode:value('standalone', translate('独立按需核心'))
core_mode:value('openclash', translate('复用 OpenClash'))
core_mode.default = options.core_mode or 'standalone'
core_mode.rmempty = false
for _, definition in ipairs(definitions) do
    local key = definition[1]
    local value = field(Value, key, translate(definition[2]))
    value.default = options[key] and options[key] ~= '' and options[key] or definition[3]
    value.rmempty = key == 'bootstrap_dns'
    value.maxlength = 256
    if key == 'bootstrap_dns' then
        value:depends('core_mode', 'standalone')
    elseif key == 'listen_port' then value.datatype = 'range(1024,65535)'
    elseif key == 'idle_seconds' then value.datatype = 'range(10,3600)'
    else value.datatype = 'ip4addr' end
end
if linked then
    local manage = field(DummyValue, '_openclash', translate('订阅与节点'))
    manage.value = translate('在 OpenClash 中管理订阅、节点和测速。星渡只复用现有代理入口。')
end
local function plain(value)
    return type(value) == 'string' and #value <= 256
        and not value:find('%c') and value or nil
end
local function latency(value)
    return type(value) == 'number' and value > 0 and value < 3600000
        and math.floor(value) .. ' ms' or translate('未知')
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
local state = snapshot.ready == true and translate('上次快照：核心就绪')
    or translate('上次快照：核心休眠或未就绪')
if linked then state = snapshot.ready == true and translate('上次快照：OpenClash 入口可用，外网与节点健康待验证') or translate('上次快照：OpenClash 入口不可用') end
if stale then state = state .. ' / ' .. translate('历史缓存') end
local status = field(DummyValue, '_status', translate('核心快照'))
status.value = state
local timestamp = field(DummyValue, '_updated', translate('快照时间'))
timestamp.value = updated and os.date('%Y-%m-%d %H:%M:%S %Z', updated) or translate('尚无快照')
if not linked then
local current = type(snapshot.current) == 'table' and snapshot.current or {}
local actual = field(DummyValue, '_current', translate('上次快照的实际节点'))
actual.value = (plain(current.name) or translate('未知')) .. ' / ' .. latency(current.delay)
local path = {}
if type(current.path) == 'table' then
    for i, name in ipairs(current.path) do
        if i > 16 then break end
        if plain(name) then path[#path + 1] = name end
    end
end
local route = field(DummyValue, '_path', translate('上次快照的选择路径'))
route.value = #path > 0 and table.concat(path, ' > ') or translate('未知')

else
    local routing = field(DummyValue, '_routing', translate('上次快照的路由模式'))
    routing.value = (snapshot.route_policy == 'rule' or snapshot.route_policy == 'global' or snapshot.route_policy == 'direct') and snapshot.route_policy or translate('未知')
    local rows = {}
    for i, group in ipairs(type(snapshot.groups) == 'table' and snapshot.groups or {}) do
        if i > 256 then break end
        if type(group) == 'table' and plain(group.name) and plain(group.type) then
            rows[#rows+1] = {name=group.name,type=group.type,selected=plain(group.selected) or translate('动态 / 未知')}
        end
    end
    local groups = form:section(Table, rows, translate('OpenClash 策略组'), translate('只读历史快照。某个组的选择不代表每次请求的实际出口。'))
    form.portal_groups = groups
    groups:option(DummyValue, 'name', translate('策略组'))
    groups:option(DummyValue, 'type', translate('类型'))
    groups:option(DummyValue, 'selected', translate('当前选择'))
end

local saved = field(DummyValue, '_saved', translate('已保存的节点偏好'))
saved:depends('core_mode','standalone')
saved.value = plain(options.preferred_node) and options.preferred_node ~= ''
    and options.preferred_node or translate('无')
local subscription = field(Value, 'subscription_url', translate('订阅链接（HTTPS）'),
    translate('留空保留原订阅；新链接不会回显。先保存，再更新订阅。'))
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
        return nil, translate('请输入有效的 HTTPS 订阅链接。')
    end
    return value
end

local mode = field(ListValue, 'selection_mode', translate('节点策略'))
mode:depends('core_mode','standalone')
mode:value('auto', translate('自动回退：香港 → 日本 → 其他'))
mode:value('preferred', translate('优先所选节点，失败时自动回退'))
mode:value('fixed', translate('仅固定节点，失败时停止外网请求'))
mode.default = options.selection_mode or 'auto'
mode.rmempty = false
local preferred = field(Value, 'preferred_node', translate('首选 / 固定节点'),
    translate('从快照选择或填写完整名称。固定节点缺失或不可用时会拒绝外网请求。'))
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
                local health = node.alive == true and translate('上次可用')
                    or node.alive == false and translate('上次不可用') or translate('未知')
                preferred:value(name, name .. ' / ' .. latency(node.delay) .. ' / ' .. health)
                node_rows[#node_rows + 1] = {name = name, delay = latency(node.delay),
                    health = health, selected = node.selected == true and translate('是') or translate('否')}
            end
        end
    end
end
local nodes = form:section(Table, node_rows, translate('节点快照'),
    linked and translate('只读节点列表；选择节点和测速请在 OpenClash 操作。')
    or translate('列表为历史数据；刷新页面不会唤醒休眠核心。'))
form.portal_nodes = nodes
nodes:option(DummyValue, 'name', translate('名称'))
if not linked then
nodes:option(DummyValue, 'delay', translate('延迟'))
nodes:option(DummyValue, 'health', translate('上次健康状态'))
nodes:option(DummyValue, 'selected', translate('上次选中'))
end

local function button(name, label, description)
    local value = field(Button, name, label, description)
    value.inputtitle = label
    value.inputstyle = name == '_save' and 'save' or 'apply'
    -- Button parsing never executes an action before complete form validation.
    function value.write() end
    function value.remove() end
end
button('_save', translate('保存配置'))
button('_apply', translate('应用已保存配置'))
button('_start', translate('启动共享'))
button('_stop', translate('停止共享'))
button('_refresh', translate('刷新快照'))
if not linked then button('_update', translate('更新订阅'),
    translate('使用已保存链接下载缓存；不会启动核心。运行中的核心可能重载节点并中断连接。')) end

-- Post/redirect/get prevents a browser refresh from repeating a service action.
-- Fixed result messages only; no submitted value enters a redirect.
local results = {
    saved = translate('配置已保存。共享状态保持不变；运行中需点击“应用已保存配置”使修改生效。'),
    applied = translate('已应用保存的配置。已启用的共享会重启；已停止的共享仍保持停止。'),
    started = translate('已按保存的配置启动，请查看共享状态。启动成功不代表外网或游戏已连通。'),
    stopped = translate('共享已停止，开机自启已取消。请关闭设备上的手动代理。'),
    refreshed = translate('快照已刷新；节点详情可展开查看。'),
    updated = translate('订阅缓存已更新。运行中的核心可能重载节点；快照仍需单独刷新。')
}
local errors = {
    apply_failed = translate('应用失败，请检查已保存的配置和本地服务状态。'),
    update_failed = translate('订阅更新失败，请检查已保存的链接和本地服务状态。'),
    start_failed = translate('启动失败，请检查配置、依赖和核心状态。'),
    stop_failed = translate('停止未完成，请检查本地服务状态。'),
    refresh_failed = translate('快照不可用；核心可能正在休眠，刷新不会唤醒它。')
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
        self.errmessage = translate('提交已失效，请刷新页面后重试。')
        return true
    end
    local action, count
    count = 0
    for _, name in ipairs({'_save', '_apply', '_update', '_start', '_stop', '_refresh'}) do
        if http.formvalue('cbid.portalproxy_ui.1.' .. name) then
            action = name
            count = count + 1
        end
    end
    if count ~= 1 then
        self.errmessage = translate('请一次执行一个操作。')
        return true
    end
    if action == '_save' then
        if state ~= FORM_VALID then
            self.errmessage = translate('配置无效，未保存。请检查标记的 IP、端口和超时字段。')
            return true
        end
        local candidate = {}
        for key, value in pairs(options) do candidate[key] = value end
        candidate.core_mode = data.core_mode or options.core_mode or 'standalone'
        candidate.selection_mode = data.selection_mode or options.selection_mode or 'auto'
        candidate.preferred_node = data.preferred_node or options.preferred_node or ''
        -- CBI omits empty optional values. An explicit empty standalone field
        -- must clear the preference; hidden linked settings must be retained.
        if candidate.core_mode == 'standalone' and http.formvalue('cbid.portalproxy_ui.1.preferred_node') ~= nil then
            candidate.preferred_node = data.preferred_node or ''
        end
        for _, key in ipairs(network_fields) do
            if data[key] ~= nil then candidate[key] = data[key] end
        end
        if candidate.core_mode == 'standalone' and http.formvalue('cbid.portalproxy_ui.1.bootstrap_dns') ~= nil then
            candidate.bootstrap_dns = data.bootstrap_dns or ''
        end
        if candidate.bootstrap_dns == '' then candidate.bootstrap_dns = candidate.local_dns end
        if replacement and replacement ~= '' then candidate.subscription_url = replacement end
        local ok = pcall(function()
            package.path = '/usr/libexec/portalproxy/?.lua;' .. package.path
            local config = assert(loadfile('/usr/libexec/portalproxy/config.lua'))()
            config.validate(candidate)
        end)
        if not ok then
            self.errmessage = translate('配置无效，未保存。请检查 IP、端口、超时；独立模式还需有效的 HTTPS 订阅和节点策略。')
            return true
        end
        local changes = cursor:changes('portalproxy')
        if type(changes) == 'table' and next(changes) then
            self.errmessage = translate('存在其他未提交的星渡配置，请先处理后再保存。')
            return true
        end
        local committed = pcall(function()
            assert(cursor:set('portalproxy', 'main', 'core_mode', candidate.core_mode))
            assert(cursor:set('portalproxy', 'main', 'selection_mode', candidate.selection_mode))
            assert(cursor:set('portalproxy', 'main', 'preferred_node', candidate.preferred_node))
            for _, key in ipairs(network_fields) do
                if candidate[key] ~= nil then assert(cursor:set('portalproxy', 'main', key, candidate[key])) end
            end
            if replacement and replacement ~= '' then
                assert(cursor:set('portalproxy', 'main', 'subscription_url', candidate.subscription_url))
            end
            assert(cursor:commit('portalproxy'))
            assert(fs.chmod('/etc/config/portalproxy', '600'))
        end)
        if not committed then
            self.errmessage = translate('保存失败，请检查本地配置文件权限后重试。')
            return true
        end
        return completed('saved')
    elseif action == '_apply' then
        local ok, code = pcall(sys.call, '/usr/bin/lua /usr/libexec/portalproxy/render.lua >/dev/null 2>&1 && /etc/init.d/portalproxy restart >/dev/null 2>&1')
        return completed(ok and code == 0 and 'applied' or 'apply_failed')
    elseif action == '_start' or action == '_stop' or action == '_refresh' then
        local commands = {
            _start = {'/usr/sbin/portalproxy enable >/dev/null 2>&1', 'started', 'start_failed'},
            _stop = {'/usr/sbin/portalproxy disable >/dev/null 2>&1', 'stopped', 'stop_failed'},
            _refresh = {'/usr/sbin/portalproxy nodes-refresh >/dev/null 2>&1', 'refreshed', 'refresh_failed'}
        }
        local command = commands[action]
        local ok, code = pcall(sys.call, command[1])
        return completed(ok and code == 0 and command[2] or command[3])
    elseif action == '_update' then
        if linked then return completed('update_failed') end
        local ok, code = pcall(sys.call, '/usr/bin/lua /usr/libexec/portalproxy/update-subscription.lua >/dev/null 2>&1')
        return completed(ok and code == 0 and 'updated' or 'update_failed')
    end
    return true
end

form.portal_linked = linked
form.portal_running = runtime and not runtime.stale or false
form.portal_address = plain(options.listen_ip) or ''
form.portal_port = plain(options.listen_port) or '10081'
form.portal_client = plain(options.client_ip) or ''
form.portal_configured = form.portal_address ~= '' and form.portal_client ~= ''
return form
