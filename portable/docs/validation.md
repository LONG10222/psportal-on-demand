# Unified Linux development build validation

> Historical initial local snapshot and acceptance plan. The measurements below are preserved for that revision; statements about unrun platforms are not the current project status. See the [current platform validation record](../../docs/portable-status.zh-CN.md) and [artifact-specific downloads](../../docs/downloads.zh-CN.md).

Date: 2026-10-18 UTC. Preview revision 3; unsigned development build.

## Package and environment

- Linux x86_64, Debian 13, glibc 2.41; distro Python 3.13.5, Tcl/Tk 8.6, PyInstaller 6.16.0
- Extract the entire archive. Python/Tk are included; no Python installation is required
- External mode remains the default and requires a separately obtained Mihomo executable
- Experimental embedded mode includes the native Go engine with Mihomo v1.19.32 adapter code, complete corresponding source/vendor archive, GPL-3.0 license and dependency notices
- The embedded engine supports a deliberately restricted node schema and public node endpoints. Unsupported nodes are rejected/skipped explicitly; missing fixed nodes fail closed. See `embedded-integration.md`
- Exact distro runtime audit retains 21 component copyright files for 45 bundled ELF objects, with SHA256 inventory in `licenses/debian/runtime-manifest.json`
- Bundled ELF symbol requirements reach GLIBC_2.38. This is a minimum symbol constraint, not evidence of compatibility with every newer distribution. Host zlib (`libz.so.1`) is needed by the bootloader before extraction/loading; `libxcb.so.1`, system libc, an X11/XWayland display and usable fonts/fontconfig are also prerequisites

## Evidence

- Final Debian-runtime dual-engine package: 108 tests, 107 passed and one graphical-display test skipped locally (16.026 seconds). This includes the original 78 regression tests, 28 embedded-engine tests and two new packaged/GUI checks
- Final application executable SHA256: `90bb6f3e59aec6cde159f13a24bfcbd7586f946ff8efa6bae763f5ff01ef4590`
- Bundled native executable SHA256: `dedd5197f99f9d478086d635246944be7fc73891ba3484c76774533339461c5a`
- Real external Mihomo and the packaged Python executable passed controlled HTTP/CONNECT cold-start, idle-stop/rewake, active-tunnel protection and stdin-EOF shutdown tests
- The embedded Go engine passed 40 top-level tests / 203 cases, race detection and vet. Actual adapter tests exercise controlled HTTP and CONNECT upstreams
- Packaged embedded discovery, auto/prefer/fixed configuration handoff, private runtime cleanup, explicit error handling and refusal to silently fall back to another engine were exercised
- Original router behavior remains separately tested: 3,744 Lua assertions plus LuCI checks and four packaging tests
- CI results and subsequent final package acceptance are recorded separately with their exact commit/artifact hashes. Do not infer that a source test proves every later package

All networking tests use synthetic local providers and controlled loopback upstreams. No user subscription, credentials, real Internet exit or PlayStation traffic was used.

## Platform and device limits

Linux command-line/backend behavior is exercised locally. The external fallback package passed actual Tk/Xvfb Start/Stop/restart/close interaction in CI at commit eae3b9745992636a3fbae42cb7df928869055035, and its Windows/macOS packaged config/listener/denial/EOF/restart tests passed too. The newer unified package has separate pending CI gates; those older results do not establish the newer artifact's graphical or non-Linux behavior. This local sandbox cannot create the Xvfb sockets it needs. Crosscompiled Go binaries alone do not establish runtime support.

Physical Portal/Wi-Fi operation, real providers, node performance, other Linux distributions and hardware remain unverified. Android and iOS have separate build/test gates. iOS hosting is foreground-only; background LAN-proxy parity is not supported by the platform architecture.

No firewall, DNS, system proxy, VPN, boot service or computer settings are modified by the application or these tests.
