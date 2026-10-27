#!/usr/bin/lua
package.path='/usr/libexec/portalproxy/?.lua;'..package.path
local mode=require 'product_mode'
if arg[1]=='game' or arg[1]=='accelerator' or arg[1]=='starpass' then
    local ok=pcall(mode.switch,arg[1])
    if not ok then io.stderr:write('Mode change failed; check the installed modules and official pause confirmation.\n');os.exit(1) end
    print('Workspace saved: '..arg[1])
else io.stderr:write('Usage: portalproxy mode game|accelerator|starpass\n');os.exit(2) end
