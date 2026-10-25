#!/usr/bin/lua
package.path='/usr/libexec/portalproxy/?.lua;'..package.path
local mode=require 'product_mode'
if arg[1]=='game' or arg[1]=='accelerator' then
    local ok=pcall(mode.switch,arg[1])
    if not ok then io.stderr:write('Mode change failed; stop active acceleration and check the installed modules.\n');os.exit(1) end
    print('Workspace saved: '..arg[1])
else io.stderr:write('Usage: portalproxy mode game|accelerator\n');os.exit(2) end
