-- Read subscription metadata only. Never starts OpenClash or changes its UCI.
local subscription = require 'subscription'
local M = {}
function M.list(uci)
    local rows = {}
    if type(uci.foreach) ~= 'function' then return rows end
    uci:foreach('openclash', 'config_subscribe', function(s)
        if #rows >= 64 or s.enabled == '0' then return end
        local ok = pcall(subscription.validate_url, s.address)
        local id = s['.name']
        if ok and type(id) == 'string' and id:match('^[%w_]+$') then
            local title = type(s.name) == 'string' and s.name or 'OpenClash subscription'
            title = title:gsub('%c', ''):sub(1, 80)
            rows[#rows + 1] = {id=id, title=title}
        end
    end)
    return rows
end
function M.apply(options, uci)
    local result = {}; for k,v in pairs(options) do result[k]=v end
    local mode = result.source_mode or 'manual'
    assert(mode == 'manual' or mode == 'openclash', 'Invalid subscription source')
    if mode == 'manual' or result.core_mode == 'openclash' then return result end
    uci = uci or require('uci').cursor()
    local selected = result.openclash_source or ''
    local chosen
    for _,row in ipairs(M.list(uci)) do
        if (selected == '' and not chosen) or selected == row.id then chosen=row end
    end
    assert(chosen, 'Selected OpenClash subscription is unavailable; select it again')
    result.subscription_url = subscription.validate_url(uci:get('openclash', chosen.id, 'address')).url
    result.subscription_user_agent = subscription.validate_user_agent(
        uci:get('openclash', chosen.id, 'sub_ua') or 'clash.meta')
    result.openclash_source = chosen.id
    return result
end
return M
