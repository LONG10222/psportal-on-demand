# Windows desktop validation — 2026-10-19

This change is based on PR #5, `feat/cross-platform-ui-parity`, at
`f02fe4c402e9559c951823391afa2c4bbac68fdc`. It fixes the desktop's private
control pipes and adds Windows source/window/frozen regressions.

## Reproduced defects and fixes

- The desktop writes and reads UTF-8, but its Python child inherited the
  redirected-stream encoding. With `PYTHONIOENCODING=cp1252` or `ascii`, a
  Chinese/emoji selection command failed to decode. A GBK child could silently
  interpret UTF-8 as different node names. Configure stdin, stdout and stderr as
  strict UTF-8 for `--desktop-child`, before validation and worker threads start.
  Ordinary CLI output keeps the user's selected encoding.
- Invalid UTF-8 could terminate only the stdin reader, leaving the listener
  running after the desktop control channel was lost. The reader now always
  requests shutdown on EOF, oversized input, decode failure or pipe failure.
  A new test reproduced the previous hang and now checks clean exit and removal
  of the ownership lock/session for both source and frozen executables.

## Local environment and evidence

- Windows 11 x64, build 26300; Python 3.12.14; Tcl/Tk 8.6.12.
- PyInstaller 6.16.0 and PyYAML 6.0.3 from the repository's requirements.
- Official Mihomo v1.19.32 Windows AMD64 compatible binary. Download ZIP SHA-256:
  `974a4d7ad69aed27aa2e8f91d61113573c14dadb14562c63e58effabf59816f0`.
- Baseline: 318 tests, 271 passed, 47 conditional skips, with real Mihomo enabled.
- Final: 323 tests, 282 passed, 41 conditional skips, with real Mihomo, source Tk
  windows, the rebuilt frozen executable, and native frozen-window checks enabled.
- Actual source Tk checks cover start/stop, language switching, node selection,
  active device counts, an existing CONNECT tunnel, and child cleanup. The new
  Unicode scenario selects `香港 🌏` in `选择 🚀` with a legacy child encoding.
- Frozen checks cover window visibility and normal close, configuration validation,
  listener restart, HTTP/CONNECT, idle shutdown/rewake, EOF cleanup, Unicode node
  selection through the real core and malformed control input.

The tested local external-mode executable SHA-256 is
`6ae43f36a485a9f17c147eb686a832912ce24b0ac0c212ebef5c58b83fc60d5b`.
This identifies a local development build, not a signed or audited public release.
The existing strict runtime provenance/release gates remain required for public
binary distribution. No local executable or runtime archive is committed.

## Reproduce from PowerShell

Use a Tk-enabled Python 3.10+ installation. From `portable/`, create an isolated
environment, install the pinned dependencies, and point at a separately verified
native Mihomo executable:

```powershell
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r requirements-build.txt
$env:MIHOMO_BINARY = 'C:/absolute/path/to/mihomo.exe'
& ./.venv/Scripts/python.exe scripts/fetch_yaml_sources.py
& ./.venv/Scripts/python.exe build.py
$env:PSPORTAL_BINARY = (Resolve-Path dist/PSPortalProxy/PSPortalProxy.exe).Path
$env:PSPORTAL_TK_TEST = '1'
$env:PSPORTAL_FROZEN_WINDOW_TEST = '1'
$env:PYTHONUTF8 = '1'
& ./.venv/Scripts/python.exe -m unittest discover -s tests -v
```

The encoding regressions explicitly override the child's encoding, so the final
`PYTHONUTF8=1` setting cannot conceal them. Tests use temporary private profiles
and loopback fixtures, without reading a user subscription or sending game traffic.

The 41 skips cover POSIX-only fixtures, macOS/Linux acceptance, missing optional
embedded/native binaries, and display tests for other platforms. They are not
passes. No Go/mobile/OpenWrt changes were made or revalidated here. Physical Portal,
PS5, Wi-Fi/firewall reachability and Internet subscriptions still need separate
device acceptance; local loopback results do not establish those outcomes.
