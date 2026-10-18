# PS Portal On-Demand

[简体中文](README.zh-CN.md) · English

An explicit HTTP proxy for PlayStation Portal on OpenWrt and iStoreOS. A small Lua listener stays available on the LAN. It starts a separate Mihomo process when the configured Portal sends an external HTTP request or HTTPS tunnel request, then stops that process after 60 seconds without client traffic through external sessions.

The listener accepts one configured client IP. Private-address requests go directly to the LAN. The proxy uses your own Clash/Mihomo subscription, preferring Hong Kong, then Japan, then other regions. OpenClash does not need to be running.

This repository contains the service, installer, configuration wizard, and tests. It includes no subscription, proxy credentials, Mihomo binary, or production network configuration. The addresses below are examples.

## How it works

```text
Portal → manually configured HTTP proxy → Lua listener
                                         ├─ private destination → direct LAN connection
                                         └─ external destination → start Mihomo → own subscription
                                                                     HK → Japan → other regions
                                         60 s without external client bytes → stop Mihomo
```

- Boot starts the listener. The proxy core remains stopped until an external request arrives.
- Opening a socket without sending a complete proxy request does not start the core.
- Local traffic and node health checks do not reset the external idle timer.
- Idle external tunnels are closed when the core stops. A later request starts it again.
- Region selection uses a Mihomo `fallback` group with ordered filters. Within a region, the provider's order is retained. It is availability based, not lowest-latency selection.
- Health checks and subscription refresh run only while the core is running. An available higher-priority node can be selected again after a later check.

“Idle” means no bytes received or sent through external client sessions. Portal background requests and application keepalives count as activity. The service cannot infer whether someone is actively playing. The first request, a failed connection attempt, or repeated background retries can wake it. This is lifecycle control, not traffic concealment or a guarantee of zero network activity.

## Requirements

- OpenWrt/iStoreOS with `procd`, UCI, Lua 5.1, and LuCI Lua libraries. The runtime was exercised on iStoreOS 22.03.6; other releases need verification.
- A reachable, stable LAN IPv4 address for the router running this service.
- A reserved IPv4 address for the Portal, assigned by your existing DHCP server.
- A working Mihomo binary for the router's CPU and an HTTPS subscription returning Clash/Mihomo YAML (`proxies:`). Plain Base64 node lists are not supported.
- Working direct DNS and HTTPS access to the subscription server. The subscription is downloaded directly to avoid a bootstrap dependency on its own nodes.

On an `opkg` based release, missing dependencies can usually be installed with:

```sh
opkg update
opkg install lua luci-lib-nixio luci-lib-jsonc luci-lib-base libuci-lua
```

Use packages matching the installed firmware. The installer checks the required Lua modules before writing files. `curl` and `jsonfilter` are needed for the optional integration test, not the normal listener.

Use a current stable [Mihomo release](https://github.com/MetaCubeX/mihomo/releases). The configuration requires ordered filters, provider health checks, and per-URL proxy health history. See the upstream [proxy group](https://wiki.metacubex.one/en/config/proxy-groups/) and [provider](https://wiki.metacubex.one/en/config/proxy-providers/) documentation. The project does not download or update Mihomo automatically.

## Install

Run these commands in an SSH session on the OpenWrt router, as root:

```sh
cd /tmp
git clone https://github.com/LONG10222/psportal-on-demand.git
cd psportal-on-demand
sh install.sh
portalproxy setup
```

If Git is unavailable, download and extract the repository instead:

```sh
cd /tmp
curl -fL https://github.com/LONG10222/psportal-on-demand/archive/refs/heads/main.tar.gz -o portal-source.tar.gz
tar -xzf portal-source.tar.gz
cd psportal-on-demand-main
sh install.sh
portalproxy setup
```

The installer reuses an existing project binary, `/etc/openclash/core/clash_meta`, or `/usr/bin/mihomo`, in that order. It copies the binary into the project's private directory. To choose a different binary:

```sh
sh install.sh --core /path/to/mihomo
```

Installation alone starts no services. Setup validates the inputs, enables the listener at boot, and starts it. The core's own boot entry stays disabled.

### Example setup

Suppose the main router is `192.168.50.1`, the OpenWrt host is `192.168.50.2`, and the Portal's reserved address is `192.168.50.30`. Replace these with addresses from your network.

| Wizard prompt | Example / meaning |
| --- | --- |
| OpenWrt LAN IPv4 address | `192.168.50.2`, an address already assigned to this router |
| Portal reserved IPv4 address | `192.168.50.30`, reserved on the existing DHCP server |
| LAN DNS server | `192.168.50.1`, used to identify names resolving to private addresses |
| Working bootstrap DNS | `192.168.50.1`, or space-separated reachable DNS IPv4 addresses |
| HTTP proxy port | `10081`, unused on this router |
| External idle timeout | `60` seconds |
| HTTPS subscription URL | Your own provider's Clash/Mihomo subscription; input is hidden |
| Optional YAML seed | An existing local Clash/Mihomo YAML file, or leave empty |
| Outbound routing mark | `0` normally; see OpenClash compatibility below |

Reserve the Portal's address **before** configuring the allowlist. This project neither creates DHCP reservations nor changes the router's LAN address. The wizard can detect an existing LAN address, but does not assign one.

The optional seed is copied locally as the initial provider cache. It can reduce first-start delay when the same subscription is already available on the router. Use YAML from a trusted source. It is not uploaded or committed anywhere. Without a seed, the first wake must download the subscription; if the Portal times out, wait briefly and retry.

### Configure the Portal

1. Connect the Portal to the normal home Wi-Fi. Keep IP, gateway, and DNS on automatic if your network normally uses DHCP.
2. In that network's advanced settings, enable the manual HTTP proxy.
3. Enter the OpenWrt host address and the configured listener port. For the example above, use `192.168.50.2` and `10081`.
4. Run the Portal's connection test, then connect to the PS5 and try a game.

The Wi-Fi association must already work. An HTTP proxy cannot fix a wrong Wi-Fi password, incompatible wireless encryption, weak signal, guest isolation, or a DHCP failure. Your PS5 does not need this proxy setting. A successful Internet test also does not prove that game streaming is working.

## Operation

```sh
portalproxy status     # listener/core state, idle timer, request counters
portalproxy check      # validate saved configuration without starting the core
portalproxy restart   # reload own configuration; active proxy sessions disconnect
portalproxy stop      # stop listener and core for this boot
portalproxy start     # start the configured listener
portalproxy disable   # stop and disable listener at boot
portalproxy enable    # enable and start the listener
portalproxy setup     # edit setup interactively; empty subscription keeps the old URL
```

Expected sequence: listener running / core stopped → Portal external request → core running → no external client bytes for 60 seconds → core stopped. The loop checks at roughly 250 ms intervals; service shutdown adds a small delay.

`stop` does not remove the boot setting. Use `disable` to keep it stopped after reboot. Stopping the service does not remove the Portal's manual proxy setting; disable that setting on the Portal if you want to use the ordinary network path again.

### OpenClash compatibility

The service uses its own configuration, provider cache, management secret, process, and copied binary. Starting or stopping OpenClash does not directly start or stop this service.

Some OpenClash builds bypass traffic marked `6666` or sent by group `nogroup`. The wizard suggests that mark when it detects `/etc/init.d/openclash`; you can enter `0` or another mark. With `6666`, both project processes run with primary group `nogroup`, and the generated core/provider outbound sockets receive the mark. This uses an existing bypass convention; it does not add firewall rules.

A custom global TUN, policy route, DNS interception, or different firewall implementation can still affect outbound traffic. Verify the bypass behavior on your firmware. Do not assume that every OpenClash mode or future release is isolated merely because the two services have different names.

## Configuration reference

The saved UCI file is `/etc/config/portalproxy`. Use `portalproxy setup` for initial configuration. For advanced changes, edit that file locally, then run `portalproxy check` and `portalproxy restart`.

| Option | Default | Purpose |
| --- | --- | --- |
| `enabled` | `0` before setup | Setup changes it to `1` |
| `listen_ip` | required | Existing private LAN IPv4 address; no wildcard bind |
| `client_ip` | required | The single permitted client IPv4 address |
| `local_dns` | required | IPv4 DNS server for private-name classification |
| `bootstrap_dns` | `local_dns` | Space-separated reachable DNS IPv4 addresses for subscription/node bootstrap |
| `subscription_url` | required | Own HTTPS Clash/Mihomo YAML subscription |
| `subscription_user_agent` | `clash.meta` | Subscription request user agent |
| `listen_port` | `10081` | LAN HTTP proxy listener |
| `backend_port` | `18680` | Internal HTTP proxy, loopback only |
| `api_port` | `18681` | Internal management API, loopback only with generated secret |
| `dns_port` | `18653` | Core DNS listener, loopback only |
| `idle_seconds` | `60` | External inactivity timeout; allowed range 10–3600 |
| `wakeup_timeout` | `12` | Maximum listener warmup wait; allowed range 3–60 |
| `health_interval` | `60` | Node check interval while active, in seconds |
| `health_timeout` | `5000` | Node check timeout, in milliseconds |
| `health_url` | Google connectivity-check HTTPS URL | Must return HTTP 204 through the selected node |
| `subscription_interval` | `21600` | Active-core provider refresh interval, in seconds |
| `doh_url` | `https://1.1.1.1/dns-query` | External target DNS via the selected proxy |
| `routing_mark` | `0` | Optional outbound socket mark |
| `core_path` | `/usr/libexec/portalproxy/mihomo` | Independent local Mihomo executable |

All four ports must be distinct and unused. Changing `listen_port` also requires updating the Portal's proxy setting. None of these ports is a public server endpoint.

The provider is refreshed only during core uptime; this is not a six-hour wall-clock scheduler while the core is off. Node names determine the region preference: Chinese names, HK/JP word tags, country flags, Hong Kong, and Japan are recognized. Unrecognized names remain in the final “other regions” group. If every node is unavailable, requests fail rather than silently falling back to direct Internet access.

## What traffic is covered

Only HTTP proxy requests and HTTPS `CONNECT` tunnels sent to this listener are covered. There is no transparent interception, TUN interface, SOCKS listener, UDP forwarding, or per-device default-gateway change. Local PS5 video/audio streaming may use direct UDP and follows your normal LAN path. This project does not improve Wi-Fi radio quality or guarantee remote-play performance.

Private IPv4 ranges, loopback, link-local, CGNAT, IPv6 ULA/link-local literals, and `::1` are classified as local. Names resolving only to private IPv4 addresses through `local_dns` can also bypass the core. This is an address-based decision, not a guarantee that a name is physically in your home. Private destinations across routed networks are still private destinations. IPv6 client binding and IPv6-only LAN DNS answers are not supported by this version.

The client allowlist checks the source IPv4 address, not the MAC address. Keep the DHCP reservation correct and use a trusted LAN. Do not forward the listener port from WAN or publish it on an untrusted network.

The manually configured private proxy address works only while reachable from the Portal. A different Wi-Fi network outside home needs its own reachable network arrangement; this service does not create remote access to the home router.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Wi-Fi itself cannot connect | Fix Wi-Fi/DHCP first; this proxy is above that layer |
| Connection refused | `portalproxy status`, configured LAN IP/port, and whether the listener started |
| Client rejected | Portal's current IPv4 address matches `client_ip`; reserve it on the DHCP server |
| First request fails with 503 | Subscription download, node availability, health URL, bootstrap DNS; retry or raise `wakeup_timeout` |
| Core keeps running | Background external requests/keepalives may be resetting the timer |
| Core wakes repeatedly | Look for Portal background activity; the service starts for attempted external requests too |
| Node works elsewhere but not here | Correct subscription format, current Mihomo, direct subscription access, mark/firewall compatibility |
| Internet works but PS5 cannot connect | PS5 remote-play settings, account pairing, LAN isolation, NAT and ordinary streaming path |
| Wrong region is preferred | Provider node names and health-check reachability; names are not geolocation verification |

Runtime state is in `/tmp/portalproxy/status.json`; lifecycle events are in `/tmp/portalproxy/events.log`. The listener does not log request URLs or subscription URLs. Mihomo/procd errors in the system log may include provider or connection details. Inspect logs locally and redact them before sharing.

## Upgrade, backup, uninstall

Re-run `sh install.sh` from a newer checkout, then run `portalproxy restart`. Existing project configuration is kept. Before replacing an existing installation, the installer saves its configuration, cache, and program directory to a root-only archive in `/etc/portalproxy-backups/`. Those archives may contain subscription tokens and node passwords. They stay on the router.

```sh
sh uninstall.sh          # remove own services/programs; keep configuration/cache/backups
sh uninstall.sh --purge  # also remove own saved configuration/cache; backups remain
```

After uninstalling, turn off the manual proxy on the Portal. The scripts manage only `portalproxy` and `portalproxy-core`; they do not rewrite network, DHCP, DNS, firewall, Wi-Fi, or OpenClash configuration.

## Development and tests

```sh
lua5.1 tests/unit.lua
python3 tests/packaging.py
```

The unit tests cover parser boundaries, private-address classification, configuration validation, and region-order rendering. Packaging tests exercise a staged install, preserved configuration, private permissions, backups, and uninstall. CI runs both on Ubuntu.

For an offline integration test on a disposable or supervised OpenWrt system:

```sh
sh tests/router-smoke.sh
# Check generated YAML with the actual core (configuration test only):
sh tests/core-config.sh /path/to/mihomo
# Optional full-duration idle check:
IDLE_SECONDS=60 sh tests/router-smoke.sh
```

This uses loopback-only fixtures on ports `21081`–`21084` and temporary `procd` service names. Those ports must be free. It checks local HTTP/CONNECT bypass, rejection of a second source IP, external-request wake, idle shutdown while LAN requests continue, and a second wake. It does not use a real subscription or test a real proxy node. Do not run multiple copies concurrently. The test removes its temporary services on exit.

## Privacy and license

Runtime files and backups are deliberately outside the source tree. Subscription input is hidden in the setup terminal and is not passed in command-line arguments. Local UCI/runtime configuration is root-only. No telemetry or automatic uploads are implemented. Credentials embedded in your provider's node definitions retain that provider's semantics; review their TLS settings yourself.

See [SECURITY.md](SECURITY.md) before sharing diagnostics. Source code is MIT licensed. Mihomo is a separate upstream project with its own license; no core binary is distributed here. This is an independent project, unaffiliated with Sony or PlayStation.
