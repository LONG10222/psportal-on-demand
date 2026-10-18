-- Pure policy/parser tests: no sockets, services, subscriptions or Internet.
local directory=arg[0]:match('^(.*)/') or '.'
package.path=directory..'/../src/?.lua;'..package.path
local p=require 'protocol'
local count=0
local function check(value,message) assert(value,message); count=count+1 end
local function destinations(expected,hosts)
    for _,host in ipairs(hosts) do
        check(p.destination(host)==expected,expected..' destination '..host)
        check(p.local_ip(host)==(expected=='local'),'LAN classification '..host)
    end
end

destinations('local',{'10.0.0.1','10.255.255.254','172.16.0.1','172.31.255.254',
    '192.168.0.1','192.168.255.254','fc00::1','fdff:ffff::1','FD12:3456::1',
    'fd12:3456:0000:0000:0000:0000:0000:0001','fc00::192.168.1.1'})
destinations('external',{'1.1.1.1','8.8.8.8','100.63.255.254','100.128.0.1',
    '126.255.255.254','128.0.0.1','169.253.255.254','169.255.0.1',
    '172.15.255.254','172.32.0.1','192.0.1.1','192.0.3.1','198.17.255.254','198.20.0.1',
    '223.255.255.254','2001:4860:4860::8888','2606:4700:4700::1111',
    '2001:200::1','3ffe::1','3fff:1000::1'})
destinations('deny',{'0.0.0.0','0.1.2.3','127.0.0.1','127.255.255.254',
    '100.64.0.1','100.127.255.254','169.254.1.1','169.254.169.254',
    '192.0.0.1','192.0.0.9','192.0.0.170','192.0.2.1','192.88.99.1',
    '198.18.0.1','198.19.255.254','198.51.100.1','203.0.113.1',
    '224.0.0.1','239.255.255.254','240.0.0.1','255.255.255.255',
    '::','::1','0:0:0:0:0:0:0:1','0000:0000:0000:0000:0000:0000:0000:0001',
    '::ffff:127.0.0.1','::FFFF:7F00:1','0:0:0:0:0:ffff:7f00:1','::ffff:192.168.1.1',
    '::ffff:8.8.8.8','::127.0.0.1','::7f00:1','::ffff:0:7f00:1',
    '64:ff9b::7f00:1','64:ff9b:1::7f00:1','100::1','100:0:0:1::1',
    '2001::7f00:1','2001:1ff:ffff::1','2001:db8::1','2002:7f00:1::1',
    '3fff::1','3fff:fff:ffff::1','4000::1','5f00::1','fe80::1','febf::1',
    'fec0::1','ff02::1','ffff::1','localhost','LOCALHOST.','service.localhost',
    '127.1','127.0.1','2130706433','0177.0.0.1','127.000.000.001',
    '0x7f000001','0X7F000001','0x7f.0.0.1','0x7f.1','0x7f.0x0.0x0.0x1',
    '999.1.2.3','256.0.0.1','1.2.3.4.5','', 'a..example','-a.example',
    'a-.example','a_b.example','[::1]','fe80::1%eth0','fc00::1%1','fc00::.','fc00:::1'})
destinations('name',{'example.com','ps5','ps5.lan','ps5.local','localhost.example',
    'fc-example.com','123.example','0x7f.example','xn--bcher-kva.example'})
check(p.destination(nil)=='deny','nil destination')
check(p.destination({})=='deny','non-string destination')
check(not p.local_ip('192.168.1.1.'),'local_ip requires a literal address')

for _,ip in ipairs({'::','::1','1::','1:2:3:4:5:6:7:8','1:2:3:4:5:6::8',
    '1:2:3:4:5::7:8','::ffff:192.0.2.1','1:2:3:4:5:6:192.0.2.1'}) do
    check(p.ipv6(ip),'valid IPv6 '..ip)
end
for _,ip in ipairs({'',':',':::','1:::2','1::2::3','1:2:3:4:5:6:7',
    '1:2:3:4:5:6:7:8:9','1:2:3:4:5:6:7::8',':1:2:3:4:5:6:7',
    '1:2:3:4:5:6:7:','12345::','fg00::1','::ffff:127.1','::ffff:0177.0.0.1',
    '::ffff:999.0.0.1','1:2:3:4:5:192.0.2.1','::192.0.2.1:1','[fc00::1]',
    'fe80::1%eth0','fc00::1.','fc00:'}) do
    check(not p.ipv6(ip),'invalid IPv6 '..ip)
end

for _,method in ipairs({'GET','CONNECT'}) do
    for _,case in ipairs({{'[fd12::1]','fd12::1',method=='GET' and 80 or 443},
        {'[fd12::1]:8080','fd12::1',8080},{'[2001:4860::8888]','2001:4860::8888',method=='GET' and 80 or 443},
        {'Example.COM.','example.com',method=='GET' and 80 or 443}}) do
        local target=method=='GET' and ('http://'..case[1]..'/path') or case[1]
        local r=p.parse_request(method..' '..target..' HTTP/1.1\r\n\r\n')
        check(r and r.host==case[2] and r.port==case[3],'parse '..target)
    end
    for _,host in ipairs({'127.1','2130706433','0177.0.0.1','0x7f000001','0x7f.0.0.1',
        '999.1.2.3','1.2.3.4.5','a..example','-a.example','a-.example','a_b.example',
        '[example.com]','[127.0.0.1]','[fc00:::1]','[fe80::1%eth0]','[fc00::1]extra',
        '[fc00::1]:0','[fc00::1]:65536','fc00::1',string.rep('a',64)..'.example'}) do
        local target=method=='GET' and ('http://'..host..'/') or host
        check(not p.parse_request(method..' '..target..' HTTP/1.1\r\n\r\n'),'reject authority '..target)
    end
    -- Valid but forbidden literals parse so the caller can return a policy error.
    for _,host in ipairs({'127.0.0.1','[::1]','[::ffff:127.0.0.1]','localhost'}) do
        local target=method=='GET' and ('http://'..host..'/') or host
        local r=p.parse_request(method..' '..target..' HTTP/1.1\r\n\r\n')
        check(r and p.destination(r.host)=='deny','deny parsed authority '..target)
    end
end
check(not p.parse_request(nil),'nil request')
print('Passed '..count..' destination policy assertions')
