# Router workspace validation — 2026-10-26

## Target and source

N1 ARM64, iStoreOS 22.03.6 / fw3. Router changes are based on the reviewed router implementation at `6429056`; the combined branch retains the desktop accelerator source at `905ecc5`. Only public source, example configuration and reproducible package builders belong in this change.

## Observed behavior

- One-button game sharing and direct game/accelerator workspace tabs were installed and exercised in LuCI. Preferences and enabled game-listener boot state persist.
- With OpenClash disabled, game mode reads its existing subscription metadata and borrows its core executable. Network, DHCP, firewall and OpenClash configuration hashes stayed unchanged.
- An allowed physical Portal generated external requests after the replacement. That proves use of the listener; no game frame-rate, session duration or complete Remote Play acceptance was supplied.
- A selected Hong Kong node was verified through the core API as Hysteria2. Preferred-with-fallback was saved locally using its exact name. Private node names and subscription settings are excluded from this record. This is one-node preference, not automatic protocol discovery.
- An authenticated official Xianniu console Hong Kong project started and renewed. A separate LAN test client sent HTTPS through the native HTTP relay to PlayStation and received HTTP 302. Transparent routing remained disabled. The session stopped with official confirmation, and account time was confirmed paused. Original device/profile settings and the refreshed login were retained.
- The installed BusyBox rejected fractional `sleep 0.1` in the accelerator shutdown wait. The adapter now waits in one-second steps for at most 25 seconds. A regression test exercises an integer-only shell sleep and verifies cleanup happens after waiting.

## Checks

- Fourteen Lua test entry points passed, including auth/CSRF/POST, subscription import, workspace ownership and lifecycle tests.
- Xianniu: 70 unit/package tests passed after the shutdown fix.
- Router installer and packaging: 20 tests; macOS runs use a real workspace temporary directory because the installer rejects symlinked ancestor paths.
- Older replacement tests established concurrent HTTPS, 60-second idle shutdown, second wake and procd recovery. They are historical evidence, not newly repeated acceptance of every scenario in this commit.

- Remaining-time UI: monotonic per-second estimate, official 60-second reconciliation, cache-age handling, stale-response rejection, pause/resume and zero-clamping are covered by the shared JavaScript component test.

- MAC-keyed notes: migration, changed IP, old IP reuse, profile preservation and invalid identities covered by four added tests. Two physical devices were named locally; the LuCI save action passed after reloading rpcd ACLs.

- On-device countdown acceptance: after official resume, two page observations showed decreasing remaining time without manual refresh. Official pause was confirmed and the displayed balance then stayed fixed.

## Remaining limits

The current workspace is mutually exclusive: selecting accelerator stops the game listener. Entry ports may differ. No combined routing or automatic proxy chaining is implemented.

A proxy on Portal does not capture PS5 game traffic. Full console TCP/UDP interception is unavailable through the fw3 adapter; the existing transparent backend requires fw4/nftables and traffic routed through the soft router. No PS5 game-server UDP, NAT behavior, whole-router reboot or long-duration gaming result is claimed.

Earlier Steam API and compressed-store transfers completed; a large uncompressed store response ended with a partial body. Increasing the timeout did not resolve it and was reverted. This remains an experimental transport limitation.

Private predecessor files and rollback archives remain on the device. They are not in this repository.
