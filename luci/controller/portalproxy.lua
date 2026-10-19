-- Optional legacy LuCI / luci-compat controller. No public API routes.
module('luci.controller.portalproxy', package.seeall)

function index()
    if not require('nixio.fs').access('/etc/config/portalproxy') then return end
    local page = entry({'admin', 'services', 'portalproxy'}, form('portalproxy'), _('StarPass / 星渡'), 65)
    page.dependent = true
    page.sysauth = 'root'
    page.sysauth_authenticator = 'htmlauth'
end
