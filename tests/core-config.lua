local directory=arg[0]:match('^(.*)/') or '.'
package.path=directory..'/../src/?.lua;'..package.path
local fs=require 'nixio.fs'
local json=require 'luci.jsonc'
local config=require 'config'
local root=assert(arg[1])
local core=config.render({listen_ip='192.168.50.2',client_ip='192.168.50.30',local_dns='192.168.50.1',
    subscription_url='https://subscription.example.com/clash'},string.rep('a',64))
local text=config.to_yaml(core,json.stringify)
local decoded=assert(json.parse(text))
for _,key in ipairs({'default-nameserver','proxy-server-nameserver','direct-nameserver'}) do
    assert(type(decoded.dns[key])=='table' and decoded.dns[key][1]=='192.168.50.1','Invalid serialized DNS array: '..key)
end
assert(decoded.dns['nameserver-policy']['subscription.example.com'][1]=='192.168.50.1')
assert(not text:find('\\/',1,true),'YAML-incompatible JSON slash escape')
assert(fs.mkdir(root..'/providers','700'))
assert(fs.writefile(root..'/config.yaml',text))
assert(fs.writefile(root..'/providers/subscription.yaml','proxies:\n  - name: HK fixture\n    type: socks5\n    server: 127.0.0.1\n    port: 9\n'))
print('PASS: runtime JSON serialization and DNS lists.')
