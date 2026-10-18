-- User intent is independent of Mihomo's transient selection cache.
local M = {}
local reserved={direct=true,reject=true,rejectdrop=true,compatible=true,pass=true,dns=true,global=true,portal=true}
M.default_filter = '(?i)香港|🇭🇰|\\bHK\\b|Hong[ -]?Kong`(?i)日本|东京|大阪|🇯🇵|\\bJP\\b|Japan`^(?!REJECT$).*`^REJECT$'
function M.validate(mode, name)
    mode, name = mode or 'auto', name or ''
    assert(mode=='auto' or mode=='preferred' or mode=='fixed', 'Invalid selection_mode')
    assert(type(name)=='string' and #name<=256 and not name:find('[%c`]')
        and not name:find('\194[\128-\159]') -- Unicode C1 controls
        and not name:find('\226\128[\168-\174]') -- line/bidi controls
        and not name:find('\226\129[\166-\169]'), 'Invalid preferred_node') -- bidi isolates
    assert(not reserved[name:lower():gsub('[%s%-%_]','')], 'Reserved preferred_node')
    assert(mode=='auto' or #name>0, 'Choose a preferred_node first')
    return mode,name
end
function M.exact(name)
    -- Escape regexp2 metacharacters. Backtick (filter separator) is rejected.
    return '^'..name:gsub('([\\%.%+%*%?%[%]%(%)%{%}%^%$%|])','\\%1')..'$'
end
function M.group(c)
    local mode,name=M.validate(c.selection_mode,c.preferred_node)
    local filter=M.default_filter
    if mode=='preferred' then filter=M.exact(name)..'`'..filter
    elseif mode=='fixed' then filter=M.exact(name)..'`^REJECT$' end
    -- Multiple tiers reorder static and provider nodes together. Keep REJECT
    -- last, even on older cores that lack empty-fallback/default-selected.
    -- File providers reload live, so readiness checks alone are insufficient.
    return {name='PORTAL',type=mode=='fixed' and 'select' or 'fallback',use={'SUBSCRIPTION'},proxies={'REJECT'},
        filter=filter,url=c.health_url,['expected-status']=204,interval=c.health_interval,timeout=c.health_timeout,
        ['exclude-type']='Direct|Compatible|Pass|Dns',
        ['max-failed-times']=2,lazy=false,['empty-fallback']='REJECT',['disable-udp']=true}
end
return M
