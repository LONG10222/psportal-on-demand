local json = require 'luci.jsonc'
local fs = require 'nixio.fs'
local value = fs.readfile('/tmp/portalproxy/status.json')
local state = value and json.parse(value)
if not state then print('Listener: stopped or not yet initialized'); os.exit(0) end
if not fs.stat('/proc/'..tostring(state.launcher_pid)) then print('Listener: stopped (last saved state is stale)'); os.exit(0) end
print('Listener: running')
print('Core: '..(state.core_running and 'running' or 'off'))
print('External idle: '..tostring(state.idle_seconds)..' / '..tostring(state.idle_timeout)..' seconds')
print('External connections: '..tostring(state.external_connections))
print('LAN connections: '..tostring(state.local_connections))
print('External requests: '..tostring(state.counters.external_requests))
print('Rejected clients: '..tostring(state.counters.denied_clients))
