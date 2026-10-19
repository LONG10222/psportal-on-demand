local protocol=require 'protocol'
local M={}

local function u16(s,p)
    local a,b=s:byte(p,p+1)
    if not b then return nil end
    return a*256+b
end

-- Decode a possibly compressed name, preserving label boundaries in a
-- lowercase wire-format key. Pointers must be backward, in bounds and acyclic.
-- Return the first byte after the encoded name, not after its pointer target.
local function name(s,start)
    local p,nextpos=start,nil
    local labels,seen={},{}
    local length=1
    for _=1,128 do
        if seen[p] then return nil end
        seen[p]=true
        local size=s:byte(p)
        if not size then return nil end
        if size==0 then
            return table.concat(labels)..'\0',nextpos or p+1
        elseif size>=192 then
            local low=s:byte(p+1)
            if not low then return nil end
            local target=(size-192)*256+low+1
            if target<13 or target>=p then return nil end
            nextpos=nextpos or p+2
            p=target
        elseif size>63 then
            return nil
        else
            if p+size>#s then return nil end
            length=length+size+1
            if length>255 then return nil end
            labels[#labels+1]=string.char(size)..s:sub(p+1,p+size):lower()
            p=p+size+1
        end
    end
    return nil
end

-- question is the exact wire QNAME..QTYPE..QCLASS sent by the caller. Only a
-- complete successful IN A/AAAA response is usable. Invalid responses return
-- nil,true; safe public/mixed or empty answers return nil,false for fallback.
function M.parse_response(data,id,question,allow_fakeip)
    if type(data)~='string' or #data<12 or #data>4096 or
        type(question)~='string' or #question<5 or #question>259 or
        type(id)~='number' or id<0 or id>65535 or id~=math.floor(id) then return nil,true end
    local flags=u16(data,3)
    local an,ns,ar=u16(data,7),u16(data,9),u16(data,11)
    if u16(data,1)~=id or flags<32768 or math.floor(flags/2048)%16~=0 or
        math.floor(flags/512)%2~=0 or math.floor(flags/64)%2~=0 or flags%16~=0 or
        u16(data,5)~=1 or an>64 or ns>64 or ar>64 or
        data:sub(13,12+#question)~=question then return nil,true end
    local query,p=name(data,13)
    local qtype=p and u16(data,p)
    if not query or p+3~=12+#question or (qtype~=1 and qtype~=28) or u16(data,p+2)~=1 then return nil,true end
    p=p+4
    local aliases,addresses={},{}
    local has_public=false
    for i=1,an+ns+ar do
        local owner,nextpos=name(data,p)
        if not owner or nextpos+9>#data then return nil,true end
        local typ,class,len=u16(data,nextpos),u16(data,nextpos+2),u16(data,nextpos+8)
        p=nextpos+10
        local after=p+len
        -- Our query carries no EDNS OPT record; all returned records must be IN.
        if class~=1 or after-1>#data then return nil,true end
        if typ==1 or typ==28 then
            local ip
            if typ==1 then
                if len~=4 then return nil,true end
                ip=table.concat({data:byte(p,p+3)},'.')
            else
                if len~=16 then return nil,true end
                local words={}
                for offset=0,14,2 do words[#words+1]=string.format('%x',u16(data,p+offset)) end
                ip=table.concat(words,':')
            end
            local route=protocol.destination(ip)
            -- Linked mode may receive OpenClash's default synthetic A range.
            -- Never connect to it directly; forward the original public name.
            -- This exception does not affect literals, other reserved ranges,
            -- malformed records, or local names (caller keeps it disabled).
            if allow_fakeip==true and typ==1 and ip:match('^198%.1[89]%.') then route='external' end
            if route=='deny' or route=='name' then return nil,true end
            if i<=an then
                if route=='external' then has_public=true end
                addresses[owner]=addresses[owner] or {}
                addresses[owner][#addresses[owner]+1]={ip=ip,typ=typ}
            end
        elseif typ==2 or typ==5 or typ==12 or typ==39 then
            local target,ending=name(data,p)
            if not target or ending~=after then return nil,true end
            if typ==5 and i<=an then
                if aliases[owner] and aliases[owner]~=target then return nil,true end
                aliases[owner]=target
            end
        elseif typ==6 then
            local first,middle=name(data,p)
            local second,ending
            if first then second,ending=name(data,middle) end
            if not second or ending+20~=after then return nil,true end
        elseif typ==15 or typ==33 then
            local prefix=typ==15 and 2 or 6
            if len<=prefix then return nil,true end
            local target,ending=name(data,p+prefix)
            if not target or ending~=after then return nil,true end
        end
        p=after
    end
    if p~=#data+1 then return nil,true end
    -- Do not use unrelated answer addresses, CNAME loops or conflicting data.
    for owner in pairs(aliases) do
        local seen,current={},owner
        while aliases[current] do
            if seen[current] or addresses[current] then return nil,true end
            seen[current]=true
            current=aliases[current]
        end
    end
    local current=query
    while aliases[current] do current=aliases[current] end
    if has_public then return nil,false end
    for _,record in ipairs(addresses[current] or {}) do
        if record.typ==qtype then return record.ip,false end
    end
    return nil,false
end

return M
