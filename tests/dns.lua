-- Pure DNS wire parser tests. No sockets, daemon or resolver is used.
local directory=arg[0]:match('^(.*)/') or '.'
package.path=directory..'/../src/?.lua;'..package.path
local dns=require 'dns'
local protocol=require 'protocol'
local count=0
local function check(value,message) assert(value,message); count=count+1 end
local function word(v) return string.char(math.floor(v/256)%256,v%256) end
local function name(host)
    local out={}
    for label in host:gmatch('[^.]+') do out[#out+1]=string.char(#label)..label end
    return table.concat(out)..'\0'
end
local id=12345
local qname=name('ps5.example')
local question=qname..word(1)..word(1)
local pointer='\192\12'
local function rr(typ,body,owner,class)
    return (owner or pointer)..word(typ)..word(class or 1)..'\0\0\0\60'..word(#body)..body
end
local function a(ip,owner,class)
    local body={}
    for n in ip:gmatch('%d+') do body[#body+1]=string.char(tonumber(n)) end
    return rr(1,table.concat(body),owner,class)
end
local function aaaa(words,owner) local out={}; for _,w in ipairs(words) do out[#out+1]=word(w) end; return rr(28,table.concat(out),owner) end
local function response(answers,authority,additional,flags,q)
    answers,authority,additional=answers or {},authority or {},additional or {}
    return word(id)..word(flags or 0x8180)..word(1)..word(#answers)..word(#authority)..word(#additional)..
        (q or question)..table.concat(answers)..table.concat(authority)..table.concat(additional)
end
local function expect(packet,ip,denied,message,q,queryid)
    local actual,blocked=dns.parse_response(packet,queryid or id,q or question)
    check(actual==ip and blocked==denied,message..': got '..tostring(actual)..','..tostring(blocked))
end
local private=a('192.168.50.30')
local public=a('1.1.1.1')
expect(response({private}),'192.168.50.30',false,'private A')
expect(response({public}),nil,false,'public A')
expect(response({private,public}),nil,false,'mixed A')
expect(response({public,private}),nil,false,'reverse mixed A')
expect(response({}),nil,false,'empty successful answer')
for _,ip in ipairs({'127.0.0.1','0.0.0.0','169.254.169.254','100.64.0.1','224.0.0.1','203.0.113.1'}) do
    expect(response({a(ip)}),nil,true,'denied A '..ip)
    expect(response({private,a(ip)}),nil,true,'private plus denied A '..ip)
    expect(response({public,a(ip)}),nil,true,'public plus denied A '..ip)
end
local loopback=aaaa({0,0,0,0,0,0,0,1})
local mapped=aaaa({0,0,0,0,0,0xffff,0x7f00,1})
local ula=aaaa({0xfd12,0,0,0,0,0,0,1})
local global=aaaa({0x2606,0x4700,0x4700,0,0,0,0,0x1111})
expect(response({loopback}),nil,true,'AAAA loopback in A response')
expect(response({private,mapped}),nil,true,'mapped IPv6 loopback')
expect(response({private,global}),nil,false,'mixed A with public AAAA')
expect(response({private},nil,{loopback}),nil,true,'denied additional AAAA')
expect(response({private},{a('127.0.0.1')}),nil,true,'denied authority A')
expect(response({private},nil,{public}),'192.168.50.30',false,'safe unrelated glue does not become a target')
local q6=qname..word(28)..word(1)
expect(response({ula},nil,nil,nil,q6),'fd12:0:0:0:0:0:0:1',false,'ULA AAAA query',q6)
expect(response({global},nil,nil,nil,q6),nil,false,'public AAAA query',q6)
expect(response({ula}),nil,false,'do not use AAAA to answer A query')

local alias=name('console.example')
expect(response({rr(5,alias),a('192.168.50.31',alias)}),'192.168.50.31',false,'CNAME chain')
expect(response({a('192.168.50.31',alias)}),nil,false,'unrelated private answer')
expect(response({rr(5,alias),a('192.168.50.31',name('CONSOLE.EXAMPLE'))}),'192.168.50.31',false,'case-insensitive owner')
expect(response({rr(5,pointer)}),nil,true,'CNAME self-cycle')
expect(response({rr(5,alias),rr(5,qname,alias)}),nil,true,'CNAME multi-record cycle')
expect(response({rr(5,alias),private}),nil,true,'CNAME with conflicting address')
expect(response({rr(5,alias),rr(5,name('different.example'))}),nil,true,'conflicting CNAME targets')
expect(response({rr(5,alias..'x')}),nil,true,'CNAME trailing garbage')
expect(response({rr(5,'\192')}),nil,true,'truncated CNAME pointer')
-- The second answer can legally point into an earlier CNAME RDATA name.
local cname=rr(5,alias)
local alias_offset=12+#question+12
local alias_pointer=string.char(192+math.floor(alias_offset/256),alias_offset%256)
expect(response({cname,a('10.0.0.2',alias_pointer)}),'10.0.0.2',false,'compressed CNAME target owner')

local valid=response({private})
for cut=0,#valid-1 do expect(valid:sub(1,cut),nil,true,'truncation at byte '..cut) end
local two_answers=response({private,a('10.0.0.2')})
for cut=#valid,#two_answers-1 do expect(two_answers:sub(1,cut),nil,true,'partial second answer at byte '..cut) end
expect(valid..'x',nil,true,'trailing packet bytes')
expect(response({private},nil,nil,0x0180),nil,true,'QR missing')
expect(response({private},nil,nil,0x8980),nil,true,'non-query opcode')
expect(response({private},nil,nil,0x8380),nil,true,'truncated response bit')
expect(response({private},nil,nil,0x8183),nil,true,'nonzero response code')
expect(response({private},nil,nil,0x81c0),nil,true,'reserved header bit')
expect(valid,nil,true,'wrong transaction ID',nil,id+1)
expect(valid:sub(1,4)..word(0)..valid:sub(7),nil,true,'missing question')
expect(valid:sub(1,4)..word(2)..valid:sub(7),nil,true,'multiple questions')
expect(valid,nil,true,'different echoed question',name('bad.example')..word(1)..word(1))
expect(response({private},nil,nil,nil,qname..word(1)..word(3)),nil,true,'non-IN question',qname..word(1)..word(3))
expect(response({private},nil,nil,nil,qname..word(255)..word(1)),nil,true,'unsupported ANY question',qname..word(255)..word(1))
expect(response({a('192.168.1.1',nil,3)}),nil,true,'non-IN answer')
expect(response({rr(1,'\192\168\1')}),nil,true,'short A RDATA')
expect(response({rr(1,'\192\168\1\1\0')}),nil,true,'long A RDATA')
expect(response({rr(28,string.rep('\0',15))}),nil,true,'short AAAA RDATA')
expect(response({rr(28,string.rep('\0',17))}),nil,true,'long AAAA RDATA')
local many={}; for i=1,64 do many[i]=private end
expect(response(many),'192.168.50.30',false,'64 answers accepted')
many[65]=a('127.0.0.1')
expect(response(many),nil,true,'65 answers rejected without ignoring the last')
expect(response({private},many),nil,true,'authority count bounded')
expect(response({private},nil,many),nil,true,'additional count bounded')
expect(string.rep('\0',4097),nil,true,'oversized packet')
for _,owner in ipairs({'\192\0','\255\255','\64\0','\128\0','\192'}) do
    expect(response({a('192.168.1.1',owner)}),nil,true,'invalid owner encoding')
end
local owner_offset=12+#question
local self_pointer=string.char(192+math.floor(owner_offset/256),owner_offset%256)
expect(response({a('192.168.1.1',self_pointer)}),nil,true,'owner pointer self-cycle')
local future_pointer=string.char(192+math.floor((owner_offset+2)/256),(owner_offset+2)%256)
expect(response({a('192.168.1.1',future_pointer)}),nil,true,'owner forward pointer')
local overlong=name(string.rep('a',63)..'.'..string.rep('b',63)..'.'..string.rep('c',63)..'.'..string.rep('d',63))
expect(response({a('192.168.1.1',overlong)}),nil,true,'expanded owner over 255 bytes')
local soa=rr(6,name('ns.example')..name('hostmaster.example')..string.rep('\0',20))
expect(response({private},{soa}),'192.168.50.30',false,'valid SOA record')
expect(response({private},{rr(6,name('ns.example')..name('hostmaster.example')..string.rep('\0',19))}),nil,true,'truncated SOA fields')
expect(response({private},nil,{rr(15,word(10)..name('mail.example'))}),'192.168.50.30',false,'valid MX record')
expect(response({private},nil,{rr(33,word(0)..word(0)..word(80)..name('web.example'))}),'192.168.50.30',false,'valid SRV record')
expect(response({private},nil,{rr(15,word(10)..'\192')}),nil,true,'truncated MX name')
expect(response({private},nil,{rr(33,word(0)..word(0)..word(80)..'\192')}),nil,true,'truncated SRV name')
check(select(2,dns.parse_response(nil,id,question))==true,'nil packet')
check(select(2,dns.parse_response(valid,id,nil))==true,'nil question')
check(select(2,dns.parse_response(valid,'12345',question))==true,'non-numeric ID')
-- Mutation checks exercise bounds and pointer handling without nondeterminism.
-- No malformed packet may crash or yield an unsafe direct-connect address.
for pos=1,#valid do
    for _,byte in ipairs({0,1,63,64,127,192,255}) do
        local packet=valid:sub(1,pos-1)..string.char(byte)..valid:sub(pos+1)
        local ok,ip,denied=pcall(dns.parse_response,packet,id,question)
        check(ok and type(denied)=='boolean' and
            (ip==nil or (type(ip)=='string' and not denied and protocol.destination(ip)=='local')),
            'safe mutation at byte '..pos..' value '..byte)
    end
end
for _,fake in ipairs({'198.18.0.1','198.19.255.254'}) do
    local ip,denied=dns.parse_response(response({a(fake)}),id,question,true)
    check(ip==nil and denied==false,'linked fake-IP is forwarded by name, never dialed')
    expect(response({a(fake)}),nil,true,'standalone fake-IP remains denied')
    local _,bad=dns.parse_response(response({a(fake),a('127.0.0.1')}),id,question,true)
    check(bad,'linked fake-IP never masks forbidden answers')
    local _,broken=dns.parse_response(response({a(fake)}):sub(1,-2),id,question,true)
    check(broken,'linked fake-IP cannot mask malformed packets')
end
for _,reserved in ipairs({'198.17.0.1','198.20.0.1','169.254.169.254','0.0.0.0'}) do
    local ip,denied=dns.parse_response(response({a(reserved)}),id,question,true)
    check(ip==nil and (protocol.destination(reserved)=='external' or denied),'linked exception does not relax other ranges')
end
print('Passed '..count..' DNS response assertions')
