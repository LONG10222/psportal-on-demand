-- Init stop hook: cancel readiness/service-start workers before stopping core.
local n=require 'nixio'
local fs=require 'nixio.fs'
local directory=arg[0]:match('^(.*)/') or '.'
package.path=directory..'/?.lua;'..package.path
local owner=require 'startup_owner'
n.umask('077')
local cfg={run_dir=arg[1] or '/tmp/portalproxy'}
if fs.stat(cfg.run_dir) then assert(owner.cancel(cfg)) end
