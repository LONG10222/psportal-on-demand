module('luci.controller.portalproxy', package.seeall)

function index()
    if not require('nixio.fs').access('/etc/config/portalproxy') then return end
    local page = entry({'admin', 'services', 'portalproxy'}, form('portalproxy'), _('StarPass / 星渡'), 65)
    page.dependent = true
    page.leaf = false
    page.sysauth = 'root'
    page.sysauth_authenticator = 'htmlauth'
    local api = entry({'admin','services','portalproxy','dashboard_api'},call('dashboard_api'))
    api.leaf=true; api.sysauth='root'; api.sysauth_authenticator='htmlauth'
end

function dashboard_api()
    local http=require 'luci.http'
    local context=require('luci.dispatcher').context or {}
    http.header('Cache-Control','no-store')
    if context.authuser~='root' then http.status(403,'Forbidden');return end
    local method=http.getenv('REQUEST_METHOD')
    local command='/usr/bin/python3 /usr/libexec/portalproxy/gateway/monitor.py status'
    if method=='POST' then
        if type(context.authtoken)~='string' or context.authtoken=='' or http.formvalue('token')~=context.authtoken then
            http.status(403,'Forbidden');return
        end
        local operation=http.formvalue('operation')
        local commands={
            ['subscriptions-refresh']='/usr/bin/python3 /usr/libexec/portalproxy/gateway/monitor.py start-refresh',
            ['check-update']='/usr/bin/python3 /usr/libexec/portalproxy/gateway/updater.py check',
            ['install-update']='/usr/bin/python3 /usr/libexec/portalproxy/gateway/updater.py install'
        }
        command=commands[operation]
        if not command then http.status(400,'Bad Request');return end
    elseif method~='GET' then http.status(405,'Method Not Allowed');return end
    -- Only literal commands are selected; submitted values never enter a shell.
    local output=require('luci.sys').exec(command..' 2>/dev/null')
    local json=require 'luci.jsonc'
    local ok,data=pcall(json.parse,output)
    http.prepare_content('application/json')
    http.write_json(ok and type(data)=='table' and data or {ok=false,error='本地管理服务不可用'})
end
