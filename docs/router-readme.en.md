# StarPass · Router

[Game and accelerator workspaces](router-workspaces.en.md)

On-demand HTTP proxy sharing for compatible devices on OpenWrt / iStoreOS.

[简体中文](router-readme.zh-CN.md) · English · [Project home](README.en.md) · [Acceptance record](router-validation-2026-10-23.zh-CN.md)

## Choose a mode

| Mode | Core and nodes | When idle |
| --- | --- | --- |
| Standalone | StarPass manages its own Mihomo, HTTPS subscription and selection policy | Its core stops; an external request wakes it again |
| OpenClash linked | Reuses the running proxy; subscriptions, nodes, rules and latency tests stay in OpenClash | Only StarPass sessions close; OpenClash keeps running |

Both modes allow one device IPv4. Defaults are port `10081` and a `60`-second idle timeout. Installation and Save prepare settings; Start explicitly enables sharing and boot startup.

## Download

- [Validated code 5da0753 build](https://github.com/LONG10222/psportal-on-demand/actions/runs/39958952749): download the `starpass-router-source-5da075302716ec1199bdefcb110d6ae43aff1d46` artifact and unpack its outer ZIP.
- [Current branch builds](https://github.com/LONG10222/psportal-on-demand/actions/workflows/check.yml?query=branch%3Afix%2Frouter-install-validation-20261023): check the exact commit's successful checks. Documentation updates do not repeat device acceptance.
- [Complete matching source](https://github.com/LONG10222/psportal-on-demand/archive/5da075302716ec1199bdefcb110d6ae43aff1d46.zip) · [Draft PR #27](https://github.com/LONG10222/psportal-on-demand/pull/27).

Actions downloads may require login and expire after their retention period. Rebuild the corresponding commit using the instructions below when needed. Older Releases do not contain this router update.

| File | Purpose |
| --- | --- |
| `luci-app-starpass.ipk` / `.sha256` | Core-free opkg LuCI package and checksum |
| `starpass-router-source.tar.gz` / `.sha256` | Source installer, tests, documentation and checksum |

The IPK declares Lua/LuCI dependencies and contains no Mihomo binary. Firmware using apk uses the source installer; no native OpenWrt APK or iStore listing is supplied.

## Install

### opkg firmware

Copy the IPK and its checksum file to `/tmp` on the router, then run as root over SSH:

```sh
cd /tmp
sha256sum -c luci-app-starpass.sha256
opkg install ./luci-app-starpass.ipk
```

Use the firmware's matching feeds for dependencies. Open **Services → StarPass / 星渡**. The legacy CBI page requires `luci-compat`; installation checks the existing environment and does not start sharing.

### Source-managed installation

For source-managed installations or apk firmware, first prepare the firmware's Lua, LuCI/procd, nixio, jsonc, UCI Lua, curl and CA dependencies. Do not mix package managers or feeds. The opkg dependency names are:

```sh
opkg update
opkg install lua luci-compat luci-lib-nixio luci-lib-jsonc luci-lib-base libuci-lua curl ca-bundle
```

Copy the source tar and checksum file to `/tmp`, then run:

```sh
cd /tmp
sha256sum -c starpass-router-source.sha256
tar -xzf starpass-router-source.tar.gz
cd starpass-router-source
sh install.sh --openclash
```

For a new standalone installation use `sh install.sh`, optionally with `--core /trusted/path/mihomo`. A missing core still permits installation and configuration, but standalone startup checks for an executable core. Known installed paths `/usr/bin/mihomo` and `/etc/openclash/core/clash_meta` can be discovered. Linked mode reuses the running OpenClash endpoint.

Use IPKs to upgrade an opkg-managed installation; the source installer refuses to overwrite package-managed files. Existing mode settings are retained rather than changed by an installer flag.

## Connect a device

1. Prepare the upstream: configure and start OpenClash in its own interface, or prepare a trusted matching Mihomo and your HTTPS subscription for standalone mode.
2. Expand **接入设置** (Connection settings), choose the mode and enter addresses. Reserve a stable DHCP address for the allowed device. These are examples only:

   | Field | Example |
   | --- | --- |
   | Allowed device IPv4 | `192.168.50.30` |
   | Router IPv4 | `192.168.50.2` |
   | Proxy port | `10081` |
   | LAN DNS | A working LAN resolver, e.g. `192.168.50.1` |

3. Select **保存配置** (Save). In standalone mode, enter the hidden subscription field, save, then explicitly **更新订阅** (Update subscription). Blank input preserves the saved URL; local seed import remains available through the CLI.
4. Select **启动共享** (Start sharing). Configure the device's manual HTTP proxy as `192.168.50.2:10081`, preserving its existing IP, gateway and DNS settings.
5. Check a webpage before testing the intended game/streaming feature. Finish with **停止共享** (Stop sharing) and turn off the device's manual proxy.

Overview keeps status, the saved endpoint and Start/Stop visible. Settings, historical node/group snapshots and Help are collapsed; long lists scroll and node names can be filtered locally. Advanced settings contain idle timeout/bootstrap DNS.

| Action | Behavior |
| --- | --- |
| Save | Validate and save; no download or service action |
| Apply saved settings | Restart an enabled listener; a stopped listener stays stopped |
| Start / Stop | Start and enable boot startup / Stop and disable boot startup |
| Refresh snapshot | Read a ready core; never wake it or run latency probes |
| Update subscription | Explicit standalone download; a running core may reload nodes and interrupt connections |

Unsaved edits request Save first; Stop remains usable. Standalone supports regional fallback, preferred-with-fallback and fixed-node selection using exact names. A missing/unavailable fixed node rejects traffic forwarded by StarPass. Linked node selection and latency tests stay in OpenClash.

## Validation and limits

N1 / iStoreOS 24.10.8 ARM64 was exercised with actual LuCI actions, opkg install/upgrade, real HTTP/HTTPS, concurrency, idle reactivation and procd recovery. All 28 static files in the installed `5da0753` package matched; its CI/local packages were identical.

A temporary Android 15 application on MuMu used the system proxy for HTTP 200/HTTPS 204 and recovered after sharing restarted. With sharing stopped, that client fell back to direct connections. Manual proxy settings are not a kill switch. Each round restored the original emulator proxy settings and removed the test application.

HTTP/HTTPS CONNECT carries TCP. Physical PS Portal/Quest game or streaming behavior, physical Wi-Fi quality, target N1 whole-device reboot, long-duration operation and standalone live-subscription recovery remain unverified. Listener readiness, connections and snapshots do not prove Internet/game success. [Full evidence](router-validation-2026-10-23.zh-CN.md).

## Update, rollback and uninstall

Stop sharing and retain the old package/source and configuration before updating. Upgrade opkg installations with `opkg install /tmp/new.ipk`, source installations with the matching `sh install.sh`. Both retain configuration and private local upgrade backups in `/etc/portalproxy-backups/`; backups can contain subscription credentials and must stay private.

Upgrades never start sharing automatically. An opkg `portalproxy-opkg` file is a separate new default; do not replace your configuration with it. For rollback, stop sharing and verify the backup and old package before restoring matching versions. The source installer attempts recovery from caught write failures; its backup is not a system snapshot or power-loss guarantee.

```sh
opkg remove luci-app-starpass  # opkg: retain configuration/provider/private backups
sh uninstall.sh               # source: retain configuration
```

To explicitly delete retained configuration, remove the opkg package first, then use matching source `sh uninstall.sh --purge`; independent backups remain. Disable the device's manual proxy afterward. External OpenClash remains independently managed.

## Commands and troubleshooting

```sh
portalproxy setup                  # Interactive configuration; save only
portalproxy check                  # Validate configuration/dependencies
portalproxy enable                 # Start and enable boot startup
portalproxy disable                # Stop and disable boot startup
portalproxy apply                  # Apply saved settings
portalproxy status                 # Status, not an Internet test
portalproxy nodes                  # Local node snapshot
portalproxy nodes-refresh          # Explicit refresh; never wake
portalproxy prefer preferred 'JP A' # Save an exact preference
portalproxy subscription-update    # Standalone subscription update
portalproxy logs                   # Sanitized application events
portalproxy diagnose               # Configuration check, status and logs
```

After editing `/etc/config/portalproxy`, use `portalproxy check`, then explicitly `portalproxy apply`. Keep subscriptions, authentication headers, private keys and backups out of logs/screenshots submitted to Issues.

## Build matching source

From the complete repository source root, using Python 3:

```sh
python3 scripts/build-router-ipk.py luci-app-starpass.ipk --version 0.1.0+git5da075302716-1
python3 scripts/build-router-source.py starpass-router-source.tar.gz
```

Check the SHA-256 printed by the builders. [Advanced configuration/tests](guide.md) · [OpenClash details](openclash-linked.zh-CN.md) · [Changelog](../CHANGELOG.md) · [Security](../SECURITY.md). Router wrapper: [MIT](../LICENSE); Mihomo retains its [upstream license](https://github.com/MetaCubeX/mihomo).
