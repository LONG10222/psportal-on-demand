# User guide

[Back to README](../README.md) | [简体中文](guide.zh-CN.md)

## Configuration

Settings are stored in `/etc/config/portalproxy`. Use `portalproxy setup` to edit the common options.

| Option | Default | Description |
| --- | --- | --- |
| `enabled` | `0` before setup | Set to `1` by the wizard |
| `listen_ip` | required | Existing OpenWrt LAN IPv4 address |
| `client_ip` | required | The single allowed client IPv4 address |
| `local_dns` | required | DNS server for LAN names |
| `bootstrap_dns` | `local_dns` | DNS for subscription/node bootstrap; space-separated IPv4 addresses |
| `subscription_url` | required | HTTPS Clash/Mihomo YAML subscription |
| `subscription_user_agent` | `clash.meta` | Subscription request user agent |
| `listen_port` | `10081` | Portal's manual proxy port |
| `backend_port` | `18680` | Internal HTTP port, loopback only |
| `api_port` | `18681` | Core API port, loopback only |
| `dns_port` | `18653` | Core DNS port, loopback only |
| `idle_seconds` | `60` | External inactivity timeout, 10–3600 seconds |
| `wakeup_timeout` | `12` | Core startup wait, 3–60 seconds |
| `health_interval` | `60` | Node check interval, seconds |
| `health_timeout` | `5000` | Node check timeout, milliseconds |
| `health_url` | `https://connectivitycheck.gstatic.com/generate_204` | Check endpoint returning HTTP 204 |
| `selection_mode` | `auto` | auto, preferred, fixed |
| `preferred_node` | empty | Exact saved node name |
| `doh_url` | `https://1.1.1.1/dns-query` | External DNS through the selected node |
| `routing_mark` | `0` | Outbound socket mark |
| `core_path` | `/usr/libexec/portalproxy/mihomo` | Independent core executable |

All four ports must be distinct. After changing `listen_port`, update the Portal's proxy setting as well.

```sh
portalproxy check
portalproxy restart
```

## Lifecycle and fallback

The listener runs at boot; the core starts on demand. A complete external HTTP request or HTTPS CONNECT wakes it. Private-address requests connect directly. After 60 seconds without external client bytes, the core stops and idle external tunnels close. LAN requests and node health checks do not reset the timer.

LAN bypass is limited to RFC1918 IPv4 and ULA IPv6. Loopback, link-local, CGNAT,
mapped IPv6 and other special destinations are denied. Router RFC1918/ULA LAN
addresses remain reachable; protect management services separately. See the
[destination policy and compatibility limits](destination-policy.md).

Portal background requests, keepalives, and failed retries also count as activity.

A Mihomo `fallback` group selects Hong Kong first, Japan second, and other regions last. Nodes within each region keep their subscription order. Region matching uses node names: Chinese names, HK/JP tags, flags, Hong Kong, and Japan. Requests fail when no node is available.

Health checks run only while active. Subscription downloads are now explicit via `portalproxy subscription-update`, with pinned HTTPS/public IPv4 and a file provider. A running core may reload changed files immediately. See [node preferences](node-preferences.zh-CN.md).

## OpenClash

The core, configuration, provider cache, and management API are separate from OpenClash. Installation copies an existing binary and does not depend on the OpenClash process.

Some OpenClash builds bypass mark `6666` or group `nogroup`. The wizard suggests `6666` when OpenClash is detected. With that value, both project processes use primary group `nogroup`, and core/provider outbound connections receive the mark. Use `0` without OpenClash.

Check the bypass mark against your rules if using custom TUN or policy routing. This project adds no firewall rules.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Installer cannot find a core | Specify an executable with `sh install.sh --core /path/to/mihomo` |
| Portal cannot reach the proxy | Check the router IP/port and whether the Portal's current IP matches `client_ip` |
| First request times out or returns 503 | Check direct subscription access, DNS, and node availability; retry or increase `wakeup_timeout` |
| Core stays active or wakes repeatedly | Check for Portal background requests and keepalives |
| Internet works but PS5 connection fails | Check PS5 remote-play settings, pairing, and LAN isolation |

```sh
portalproxy status
cat /tmp/portalproxy/events.log
```

The listener handles explicit HTTP/HTTPS proxy requests. Local PS5 UDP streaming follows the existing network path; use away from home requires a reachable home proxy address. The client allowlist checks source IP. Run the service on a trusted LAN.

Redact subscription and device information before sharing logs; see [SECURITY.md](../SECURITY.md).

## Files and backups

| Path | Contents |
| --- | --- |
| `/etc/config/portalproxy` | UCI settings |
| `/etc/portalproxy/` | Generated configuration, provider cache, API secret |
| `/etc/portalproxy-backups/` | Local upgrade backups |
| `/tmp/portalproxy/status.json` | Runtime state |
| `/tmp/portalproxy/events.log` | Lifecycle events |

`portalproxy stop` stops the current service. `portalproxy disable` also disables it at boot. Uninstall keeps configuration by default; `--purge` removes configuration and cache. Both preserve the backup directory.

## Development

Local tests:

```sh
lua5.1 tests/unit.lua
lua5.1 tests/access.lua
lua5.1 tests/dns.lua
lua5.1 tests/lifecycle.lua
lua5.1 tests/ownership.lua
python3 tests/packaging.py
```

Offline integration tests on OpenWrt:

```sh
sh tests/router-smoke.sh
sh tests/core-config.sh /path/to/mihomo
IDLE_SECONDS=60 sh tests/router-smoke.sh
```

Integration tests use loopback ports `21081`–`21084` and temporary procd services.
They check loopback destination rejection for HTTP and CONNECT, client rejection,
external wake, idle shutdown, and a second wake. The fixture intercepts the
external test target `1.1.1.1`; no Internet request is made. Keep those ports free
and run one copy at a time. RFC1918/ULA LAN bypass and concurrent lifecycle
behavior are covered by the fake-runtime regression tests; this loopback-only
router test does not establish real LAN reachability. `core-config.sh` parses a
fixture with the real core without starting a proxy service.
