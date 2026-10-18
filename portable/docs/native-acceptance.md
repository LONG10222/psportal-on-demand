# Native acceptance checklist

Status: this is a test plan. No row is a claim of native acceptance. Record date, commit/source digest, OS version, CPU architecture, Python and PyInstaller versions, Mihomo version/digest, test outcome and sanitized evidence for every build.

## Build matrix

| Platform | Build/executable verified | GUI exercised | Real Mihomo | Real Portal | Signed / notarized |
|---|---|---|---|---|---|
| Windows x64 | Not run | Not run | Not run | Not run | Not configured |
| Windows ARM64 | Not run | Not run | Not run | Not run | Not configured |
| macOS Apple Silicon | Not run | Not run | Not run | Not run | Not configured |
| macOS Intel | Not run | Not run | Not run | Not run | Not configured |
| Linux x64 | Built; import/CLI/EOF checks passed | Not run (display unavailable) | Passed controlled offline fixture | Not run | Not configured |
| Linux ARM64 | Not run | Not run | Not run | Not run | Not configured |

On 2026-10-18 the Linux x64 executable was built in the cloud workspace and exercised with real Mihomo 1.19.32 against a controlled local provider/upstream. HTTP/CONNECT, idle stop, re-wake and stdin-EOF cleanup passed. Tcl initializes headlessly; the GUI could not be displayed. This does not establish desktop, public subscription, LAN or physical Portal acceptance. Windows/macOS builds remain unrun. See validation.md for the exact verification record.

## Desktop and interrupted flows

- Start from a standard user account without an administrator/root prompt, from a path with spaces and non-ASCII characters
- First launch shows an empty LAN/core/subscription form and usable defaults; no network connections or core process are created
- Save an invalid IP, port conflict, missing node name, nonexistent core, insecure subscription URL and malformed JSON; show a useful safe error with no URL/token leak
- Save valid settings, reopen and compare; advanced fields survive GUI edits; POSIX file modes / Windows folder ACLs are appropriate
- Cancel core/config selection; cancel discarding edits; close with unsaved edits and choose both outcomes
- Click Start repeatedly; only one child appears; listener readiness appears in the log; another window targeting the same runtime refuses duplicate ownership
- Attempt bind to an unavailable address and occupied listener port; show failure without killing or changing an unrelated process
- While running, configuration edits/selection are disabled; stop/restart works without stale pipes, ports or runtime locks
- Close while running, cancel close, then confirm close; ensure listener, core and temporary runtime are gone
- Stop immediately after Start, during subscription download, core startup and an active tunnel; the window stays responsive and the process tree exits
- Terminate the GUI parent unexpectedly; verify EOF reaches its child and listener/core exit; inspect for stale runtime only after verifying no process owns it
- Test log flooding and long records; memory stays bounded and URLs/credentials are not shown
- Resize, change display scaling and tab through controls; test screen-reader labels if accessibility is a release requirement

## Real networking and core

- Use a trusted LAN and a Portal DHCP reservation; confirm this computer's exact private IPv4 address and ports
- Review the firewall dialog manually and allow only required inbound access on a trusted/private LAN, preferably scoped to the Portal IP
- Verify allowed clients reach the proxy and unlisted clients cannot; public/wildcard listener addresses must be rejected; loopback is allowed only with an exactly loopback-only allowlist for local development
- Verify core/controller are loopback-only; no TUN interface, system proxy, DNS, routes, firewall or autostart entry changed
- Start listener without traffic; confirm no Mihomo process and no subscription fetch
- First external request: exactly one core starts, subscription is fetched securely, real Mihomo accepts configuration and traffic succeeds
- Exercise HTTP absolute-form and HTTPS CONNECT against controlled endpoints; private/special-use destinations are rejected
- Keep an external tunnel active past idle timeout; core stays up. Close all sessions; core stops after idle period while listener remains
- Request again and verify wake; repeat rapidly with concurrent requests
- Test real auto, prefer (healthy/missing/unhealthy preferred node), and fixed (present/missing/unhealthy node); verify claimed route on real Mihomo
- Test invalid subscription, timeout, redirect, invalid certificate, oversized provider and offline network without exposing credentials
- Run alongside an unrelated proxy/core; port collisions fail safely and Stop never touches the unrelated process
- Sleep/resume, reconnect Wi-Fi and change LAN address; document recovery and required Portal reconnect
- Verify actual Portal login, library, reconnect and Remote Play; identify traffic that bypasses manual HTTP proxy; do not infer UDP/VPN support

## Distribution and secrets

- Unpack on a clean machine without Python; GUI and frozen backend run from the entire distributed folder/app bundle
- Validate hashes and OS/CPU; scan packages; check licenses, notices and provenance
- Verify no local config, real subscription, provider, token, signing key or personal path entered the archive
- Complete Windows signing or macOS signing/notarization before claiming a trusted public release; follow normal OS security workflows
- Test startup/EOF/shutdown using the built executable; verify packaged Tk and backend imports
- Preserve failures/skips in release reporting; require evidence before marking any platform/device test complete
