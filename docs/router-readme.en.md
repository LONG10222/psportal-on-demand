# StarPass router / PS Portal On-Demand

[![CI](https://github.com/LONG10222/psportal-on-demand/actions/workflows/check.yml/badge.svg)](https://github.com/LONG10222/psportal-on-demand/actions/workflows/check.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](../LICENSE)

[简体中文](../README.zh-CN.md) | English

An on-demand proxy for PlayStation Portal on OpenWrt / iStoreOS. Starts Mihomo for external requests and stops it after 60 seconds of inactivity.

- **On-demand core**: the listener starts at boot; external requests wake the proxy core.
- **Automatic fallback**: uses your own subscription, preferring Hong Kong → Japan → other regions.
- **Single client**: an IP allowlist and the Portal's manual HTTP proxy setting handle access.
- **Independent service**: separate core and configuration, with direct LAN connections. OpenClash can remain stopped.

> Node preferences and the optional authenticated legacy LuCI page require target-version OpenWrt/Mihomo/LuCI acceptance. Local mocks do not establish core compatibility. See [operations and acceptance notes (Chinese)](../docs/node-preferences.zh-CN.md).

## Desktop and mobile development builds

The router retains standalone mode and adds explicit read-only OpenClash linking. For Linux, Windows and macOS, use the [desktop app](../portable/docs/desktop.md); the optional shared native engine and mobile hosts are documented in [native/README.md](../native/README.md). Do not run the router install script on a desktop.

The default desktop engine launches a separate Mihomo. Experimental embedded mode uses the same UI and a restricted shared Go/Mihomo engine. Android hosts that engine in a foreground service; iOS defaults to foreground hosting; its iOS 26+ time-limited background experiment still needs actual OS authorization and physical-device acceptance. See [current validation and platform gates](../docs/portable-status.zh-CN.md). Native engine code is GPL-3.0; the original router/wrapper remains MIT. Complete corresponding source must accompany native binaries.

## Link an existing OpenClash installation

Use the exact draft-PR commit or its `starpass-router-source-…` Actions artifact. The older main archive does not contain this change. Run `sh install.sh --openclash`, then `portalproxy setup` and select `openclash`. No second core or subscription is copied. Existing installations keep their settings until you explicitly choose and apply the mode.

Start/configure OpenClash in its own interface first. StarPass reads effective UCI HTTP/mixed/controller ports and uses only literal loopback GET requests. It validates the authenticated runtime port. Existing enabled OpenClash UCI proxy authentication can be reused in process memory after matching runtime usernames; an explicit loopback exemption is also supported. Credentials never enter policy/cache/logs/command arguments. Node/group snapshots are optional, sanitized and observational. StarPass never starts/stops/reloads OpenClash, selects its nodes, updates its subscriptions or changes DNS/firewall/routes. Idle closes only StarPass sessions.

OpenClash controls final DNS/rules, including DIRECT; source-IP rules see the router rather than the original client. This cannot inherit standalone backend rebinding protections. Default fake-IP DNS answers are forwarded by their original public hostname, never dialed; forbidden literals and local-name answers stay rejected. HTTP/CONNECT is TCP only, not arbitrary game UDP. Controller availability is not proof of Internet or game success.

A reproducible core-free IPK is available for opkg firmware, alongside the source installer. apk firmware uses the source installer; there is no native apk/iStore release. N1 real-device results and remaining boundaries are recorded in [the 2026-10-23 validation](router-validation-2026-10-23.zh-CN.md). See [the complete linked-mode guide](openclash-linked.zh-CN.md).

## Standalone quick start

### 1. Requirements

- An OpenWrt / iStoreOS router with Lua 5.1, LuCI, and procd.
- A [Mihomo binary](https://github.com/MetaCubeX/mihomo/releases) for the router's architecture. An existing OpenClash core can be reused.
- Your own HTTPS Clash/Mihomo YAML subscription.
- A DHCP reservation for the Portal on your main router.

### 2. Install

SSH into the OpenWrt router and run as root:

```sh
cd /tmp
# Download and verify starpass-router-source.tar.gz from this development branch Actions
tar -xzf starpass-router-source.tar.gz
cd starpass-router-source
sh install.sh
portalproxy setup
```

The installer looks for an existing project binary, `/etc/openclash/core/clash_meta`, then `/usr/bin/mihomo`. To use another binary, replace the install command with:

```sh
sh install.sh --core /path/to/mihomo
```

If Lua dependencies are missing:

```sh
opkg update
opkg install lua luci-compat luci-lib-nixio luci-lib-jsonc luci-lib-base libuci-lua curl ca-bundle
# On apk firmware use apk update / apk add with matching firmware feeds.
```

### 3. Configure

Run `portalproxy setup` and follow the prompts. Replace the example addresses with your own:

| Prompt | Example |
| --- | --- |
| OpenWrt LAN IPv4 address | Router address `192.168.50.2` |
| Portal reserved IPv4 address | Portal reservation `192.168.50.30` |
| LAN DNS server | Main router `192.168.50.1` |
| Working bootstrap DNS | `192.168.50.1` |
| HTTP proxy port | `10081` |
| External idle timeout | `60` |
| HTTPS subscription URL | Your subscription; input is hidden |
| Optional local Clash/Mihomo YAML seed file | Leave empty or enter an existing configuration path |
| Outbound routing mark | `0` without OpenClash; see [coexistence settings](../docs/guide.md#openclash) |

Setup saves only. Import a seed or explicitly update the standalone subscription,
then run `portalproxy enable` to start and enable at boot. Saving never starts or
restarts the listener; apply saved settings explicitly when interruption is acceptable.

On the **Portal → Wi-Fi → current network → advanced settings**:

- Keep IP, gateway, and DNS on automatic.
- Enable the manual HTTP proxy, using the OpenWrt address and the port set above.
- For this example, use `192.168.50.2:10081`.

If no seed was imported, run `portalproxy subscription-update` before connecting. Updates are explicit, and a running core may reload the file immediately and switch routes. Viewing cached status never wakes the core.

## Commands

```sh
portalproxy status     # Show service status
portalproxy setup      # Edit configuration
portalproxy check      # Validate configuration
portalproxy restart    # Restart the service
portalproxy stop       # Stop the service
portalproxy disable    # Stop and disable at boot
portalproxy enable     # Start and enable at boot
```

Configuration: `/etc/config/portalproxy`. After editing, run `portalproxy check` and `portalproxy restart`.

## Update and uninstall

For an opkg-managed installation, upgrade with the new IPK and remove with
`opkg remove luci-app-starpass`; private configuration is retained. Source installs
use `sh install.sh`. Do not mix the source installer with package-owned files.
Neither installer automatically starts/restarts sharing. Existing configuration
is retained; private backups are stored in `/etc/portalproxy-backups/`.

```sh
sh uninstall.sh          # Uninstall, keep configuration
sh uninstall.sh --purge  # Uninstall and remove configuration
```

Disable the Portal's manual proxy setting after uninstalling.

## Documentation

- [Configuration, OpenClash, troubleshooting, and tests](../docs/guide.md)
- [Changelog](../CHANGELOG.md)
- [Security and diagnostics](../SECURITY.md)

## License

[MIT](../LICENSE). The proxy core is provided by [Mihomo](https://github.com/MetaCubeX/mihomo) under its upstream license.
