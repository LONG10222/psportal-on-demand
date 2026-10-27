local directory = arg[0]:match('^(.*)/') or '.'
package.path = directory .. '/?.lua;' .. package.path
local state = require('runtime_status').read()
if not state then print('Listener: stopped or no matching live status'); os.exit(0) end
print('Listener: '..(state.stale and 'status stale; verify service' or 'running (not an Internet test)'))
print('Core mode: '..(state.core_mode=='openclash' and 'OpenClash linked; external service is unmanaged' or 'standalone'))
print('Core: '..(state.core_starting and 'preparing' or state.core_running and 'running' or 'off / not reported by procd'))
print('Listener uptime: '..state.uptime_seconds..' seconds')
if state.core_mode=='openclash' then print('Owned external sessions: '..(state.session_active and 'active' or 'idle; OpenClash is not stopped')) end
print('External idle: '..tostring(state.idle_seconds)..' / '..tostring(state.idle_timeout)..' seconds')
print('External connections: '..tostring(state.external_connections))
print('LAN connections: '..tostring(state.local_connections))
print('Received from device: '..state.counters.upload_bytes..' bytes; received from upstream: '..state.counters.download_bytes..' bytes (includes protocol headers)')
print('External requests: '..tostring(state.counters.external_requests))
print('Rejected clients: '..tostring(state.counters.denied_clients))
