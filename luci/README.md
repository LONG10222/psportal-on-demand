# Optional legacy LuCI interface

The installer copies `controller/portalproxy.lua`,
`model/cbi/portalproxy.lua` and `view/portalproxy/onboarding.htm` into the matching `/usr/lib/lua/luci/`
directories when LuCI is present. The interface requires the legacy Lua
CBI runtime (`luci-compat` on LuCI versions that provide it). The CLI is
independent of this optional page.

Open **Services → PS Portal** in a root-authenticated LuCI session.

The responsive StarPass introduction uses the same restrained slate/blue hierarchy
as the desktop and phone apps. Three read-only cards separate preparation,
explicit service application and device-side verification. The cards follow the
browser's light/dark preference without changing the router theme. No form action,
polling, configuration value or subscription secret is added to this template.

- Viewing/reloading the page reads only `/tmp/portalproxy/nodes.json` and
  UCI settings. It does not contact the core, send probes, or reset idle time.
  A missing cache is normal before the first wake. Status and latency are
  historical; stale snapshots and sleeping/not-ready states are labelled.
- Enter a replacement HTTPS subscription URL in the empty password input.
  Leaving it blank preserves the existing URL. Stored or submitted URLs are
  never included in the page HTML, status, errors, redirects, or command lines.
- Select automatic, preferred-with-fallback, or fixed mode. Choose a cached
  node or type the exact node name. The saved name remains independent of
  current automatic selection and is retained when selecting automatic mode.
- **Save settings (no restart)** validates and commits the configuration.
  This persists across reboot without interrupting current connections.
  It does not create a generic LuCI pending-change diff containing the URL.
- **Apply saved settings and restart listener** ignores unsaved form edits,
  renders the saved configuration, and explicitly restarts the listener.
  This stops the core and interrupts active Portal connections. The core
  remains on demand after restarting. A render failure prevents the restart.
- **Update subscription now** uses the saved URL and only invokes the fixed
  `update-subscription.lua` helper. It downloads the file-provider cache
  without starting, contacting, or restarting the core. A running Mihomo
  core may automatically reload the changed file, switch live routes, and
  interrupt active Portal connections. A sleeping core stays asleep and
  loads the cache on its next ordinary wake. The existing node snapshot can
  remain unchanged until the listener refreshes it.
- Fixed mode fails closed if the requested name is missing or unavailable.
  It does not silently select a different node.

There are no public mutation endpoints, core-controller proxy routes,
JavaScript polling loops, or automatic apply hooks. All actions use LuCI's
native CBI `form()` dispatch and its session/POST/CSRF checks, plus an
explicit root identity and token check in the model. Successful actions and
service-action errors use post/redirect/get, so a browser refresh does not
repeat a restart or download. External commands have constant arguments,
with output suppressed in the UI; errors are generic.

## Verification

Run `lua5.1 tests/luci.lua` from the repository root. The test mocks LuCI,
UCI, the cache, command execution, and the shared configuration validator;
it exercises read-only views, root/CSRF checks, blank secret rendering,
persistent preferences, action separation, fixed commands, malformed/stale
caches, and post/redirect/get. It never downloads anything or runs services.

The implementation was checked against the upstream Lua CBI dispatcher,
SimpleForm, and standard templates. Actual target-firmware theme rendering,
login/CSRF behavior, and router service lifecycle still require router smoke
verification; mock coverage is not a live-router test.

Upstream references:
- https://github.com/openwrt/luci/blob/openwrt-19.07/modules/luci-base/luasrc/dispatcher.lua
- https://github.com/openwrt/luci/blob/openwrt-19.07/modules/luci-compat/luasrc/cbi.lua
- https://github.com/openwrt/luci/blob/openwrt-18.06/modules/luci-base/luasrc/view/cbi/simpleform.htm

## Application updates

The onboarding panel includes a collapsed, read-only update guide and fixed official
Releases link. Opening LuCI never checks releases, downloads a binary, changes UCI or
restarts services. An external page requires connectivity and is not evidence that
the installed version is current. It receives no configuration or subscription data
from the link; the link suppresses the referrer and isolates the new tab.

Use router packages/source and a compatible core for the actual firmware and CPU,
not APKs or desktop archives. Preserve local configuration and keep backups private:
they can contain subscription credentials. OpenClash's core remains independently
managed. See the source installer's documented recovery limits before updating.
