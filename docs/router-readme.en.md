# PS Portal On-Demand

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

The original router implementation below is unchanged. For Linux, Windows and macOS, use the [desktop app](../portable/docs/desktop.md); the optional shared native engine and mobile hosts are documented in [native/README.md](../native/README.md). Do not run the router install script on a desktop.

The default desktop engine launches a separate Mihomo. Experimental embedded mode uses the same UI and a restricted shared Go/Mihomo engine. Android hosts that engine in a foreground service; iOS supports foreground hosting only. See [current validation and platform gates](../docs/portable-status.zh-CN.md). Native engine code is GPL-3.0; the original router/wrapper remains MIT. Complete corresponding source must accompany native binaries.

## Quick start

### 1. Requirements

- An OpenWrt / iStoreOS router with Lua 5.1, LuCI, and procd.
- A [Mihomo binary](https://github.com/MetaCubeX/mihomo/releases) for the router's architecture. An existing OpenClash core can be reused.
- Your own HTTPS Clash/Mihomo YAML subscription.
- A DHCP reservation for the Portal on your main router.

### 2. Install

SSH into the OpenWrt router and run as root:

```sh
cd /tmp
curl -fL https://github.com/LONG10222/psportal-on-demand/archive/refs/heads/main.tar.gz -o portal-source.tar.gz
tar -xzf portal-source.tar.gz
cd psportal-on-demand-main
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
opkg install lua luci-lib-nixio luci-lib-jsonc luci-lib-base libuci-lua curl ca-bundle
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

Setup starts the listener and enables it at boot.

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

Download the new source, run `sh install.sh`, then `portalproxy restart`. Existing configuration is retained; upgrade backups are stored in `/etc/portalproxy-backups/`.

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
