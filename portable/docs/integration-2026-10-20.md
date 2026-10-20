# StarPass integration test candidate — 2026-10-20

This isolated draft combines Android PR #20 (`4eb54314`) and shared desktop
PR #21 (`a107defa`) on the original anime navigator baseline (`e28e197`).
The earlier UI/platform work is inherited, not reapplied. Native macOS/iOS
application sources and the approved character icons are unchanged.

## Integration fixes

- Frozen simple-home UI tests follow the explicit **Start sharing** action;
  advanced listener controls retain their existing label.
- Core installation rejects managed/configuration symlinks before directory
  creation. Only macOS's exact OS `/var` and `/tmp` aliases are recognized.
- Windows origin audit pins the actual CPython `_wmi.pyd` and its Microsoft
  `VCRUNTIME140_1.dll` dependency rather than weakening a numeric count.
- The official Windows x64 compatible Mihomo v1.19.32 binary and upstream ZIP
  are checksum-pinned. CI retains the matching upstream license, full upstream
  source, and `go mod vendor` dependency closure without changing go.mod/go.sum.
  Distribution inventory and final ZIP checks require this core and source.
- Windows unified CI runs real core fixtures using the very bundled compatible
  executable. No first-launch core download is needed in this audited package.
- All platform workflows check out the PR's exact head, not an implicit merge
  snapshot. Changes to the workflow files intentionally trigger full regression.

## Scope of acceptance

Offline startup means the core executable is present; it does **not** mean
subscription import, subscription refresh, or Internet/game traffic works offline.
Linux/macOS default core packaging is not changed by this Windows-specific work.
The embedded native engine remains an experimental separate option.

A green build is integration evidence, not signed production readiness. Windows
and Android outputs remain unsigned, iOS simulator/device builds do not establish
distribution signing, and macOS is not Developer ID signed/notarized. Physical
Portal, real user subscriptions, game UDP/TUN behavior, Android VPN conflict /
background / hotspot endurance, and signed upgrades need separate acceptance.
The HTTP/CONNECT TCP proxy is not a universal game accelerator.
