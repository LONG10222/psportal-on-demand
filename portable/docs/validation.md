# Linux development milestone validation

Date: 2026-10-18 UTC. Application source version: 0.1.0, preview revision 2 (safe core-error visibility).

## Environment and deliverable

- Native Linux x86_64, Debian 13, glibc 2.41
- Python 3.12.14; PyInstaller 6.16.0; Tcl 9.0.4
- Standalone `PSPortalProxy-linux-x86_64.tar.gz`; extract the whole folder
- Python and Tcl/Tk bundled; Mihomo is **not bundled** and must be supplied separately
- Actual test core: official Mihomo Meta v1.19.32 linux-amd64, Go 1.26.8
- Upstream compressed core SHA256: `8451100836c9eda194331c2babfad490b2faf30cebc1a04b0e76fd8ac2d35d10`, verified against release asset metadata
- The executable's direct GLIBC symbol requirements top out at 2.17; this does not establish old-distribution compatibility. System graphics/X11, zlib, libc and related libraries remain prerequisites. Runtime testing was on this host only

## Passed

- 78 Python tests with both optional real-core and packaged-binary tests enabled, zero skipped
- Strict destination policy, mixed/denied DNS fail-closed, exact peer allowlisting, malformed headers, request-smuggling defenses, HTTP framing and CONNECT half-close
- Public-only DNS-pinned HTTPS subscription transport, hostname/SNI preservation, no redirects, bounded transfer watchdog, size/framing/truncation validation, private atomic files, redacted errors
- Eight concurrent starts share a single owned process; active tunnels prevent idle shutdown; clean idle shutdown and a subsequent wake
- Exact fixed-node controller selection; missing fixed node fails rather than falling back
- Real Mihomo generated configuration validation and HTTP/CONNECT through a controlled local HTTP upstream
- Packaged executable itself: two HTTP/CONNECT cold-start/idle cycles, active-tunnel protection, stdin-EOF shutdown, no residual owned sockets/runtime lock/session directory
- Tk import and Tcl initialization; desktop configuration/controller/process tests; CLI help
- Original router regression tests unchanged: 3,744 Lua assertions plus LuCI model checks, and four packaging tests (Lua run with available texlua)

Commands (run from `portable`):

```sh
MIHOMO_BINARY=/trusted/path/mihomo \
PSPORTAL_BINARY="$PWD/dist/PSPortalProxy/PSPortalProxy" \
python3 -m unittest discover -s tests -v
```

The packaged tests use the explicit localhost-only mode. Synthetic provider nodes
and local upstreams intercept all test traffic; no user subscription, credentials,
Internet exit or actual PlayStation network traffic is involved.

## Not established

- Physical Portal, real LAN/Wi-Fi routing, real subscription/provider availability or actual remote-node performance
- Graphical desktop appearance/interaction: no active display; a task-local virtual-display attempt could not create its required local sockets in this sandbox
- Native Windows/macOS builds or runtime behavior at this milestone
- Android/iOS builds, device installation, background operation or full platform parity
- Real-node auto/preferred health ordering beyond source/filter tests
- Older Linux distributions, other CPUs, signing/notarization or app-store delivery
- Completed audit of every native runtime library license for public redistribution; supplied notices cover the identified bundled Python, Tcl/Tk, PyInstaller and project components

No firewall, DNS, system proxy, VPN, boot service or computer settings were changed.
The separate native/mobile implementation is work in progress and is excluded from
this milestone's source review package.
