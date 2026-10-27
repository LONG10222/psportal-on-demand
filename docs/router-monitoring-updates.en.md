# Traffic, subscription usage and in-page updates

Available in the StarPass router plugin 0.4.0. Upgrade an existing opkg installation once to get the in-page updater.

## Traffic

Game and StarPass show the shared explicit-proxy entry's upload/download rates and totals, split into public and private LAN destinations. The page refreshes every two seconds. Upload is device-to-destination; download is destination-to-device.

Only traffic through the manual HTTP proxy is measured. Public destinations include both direct and proxied connections: public does not mean every request used a subscription. Counters include HTTP/TLS data, exclude link-layer overhead and retransmissions, and reset when the entry restarts, including an upgrade. Changing tabs does not reset them. These are entry statistics, not whole-router or whole-household statistics.

Reading the dashboard does not scan devices, run speed tests or wake a sleeping game core. Missing/stale entry data shows a dash rather than a previous rate.

## Subscription usage

The panel shows the selected subscription's name, account upload/download usage, allowance, remaining quota, expiry and days left. Game uses its selected source; StarPass matches the active OpenClash configuration. If the configuration name cannot be matched, enabled OpenClash subscriptions are listed separately, without combining allowances.

**Refresh subscription information** reads `Subscription-Userinfo` from the saved HTTPS subscription. It does not replace nodes, change switches or start a core. Requests for a subscription are limited to one per 30 seconds. The private cache survives restarts; a failed refresh retains previous numbers and displays the error state. Normal polling only reads local data.

Missing fields remain unavailable. A reported `total=0` means unlimited allowance and `expire=0` means no expiry; an absent expiry is not treated as permanent. Account usage may include other devices and differs from entry counters. Dates use router/browser clocks.

## Update from LuCI

1. Click **Check for updates** at the upper right.
2. When a matching stable router release is found, click **Install update**.
3. Wait for download, integrity checks, backup, dependency preflight and installation, then refresh the page.

The task runs on the router and survives a browser reload. It updates only `luci-app-starpass` and its paired `xianniu-router` package through opkg. It does not update the firmware, unrelated plugins or the OpenClash core.

Proxy endpoints, subscriptions, MAC-based notes and saved modes are preserved. Enabled Game/StarPass services resume their saved state. An active local Xianniu session is stopped, and paid-session suspension must be confirmed before replacement. With no active session, a valid account is not required and other clients’ account clocks are untouched. Paid acceleration is not resumed afterward. Existing connections briefly disconnect.

A failed update reports an error and retains a private backup at `/etc/portalproxy-backups/update-*`. Source installations and apk-based firmware continue to use their original installation procedure.

## Release contract

A stable, non-draft GitHub Release tagged `starpass-router-vX.Y.Z` must contain:

- `luci-app-starpass_X.Y.Z_all.ipk`, matching the release version.
- `xianniu-router_X.Y.Z_all.ipk`, with its own paired version.
- Matching sources, licenses and checksum files for review and rebuilding.

The updater verifies GitHub asset SHA-256 and size, then package identity, version and architecture. Dependency downgrades are rejected. Desktop packages, preview archives and assets without digests are ignored. Network failures are never reported as already up to date.
