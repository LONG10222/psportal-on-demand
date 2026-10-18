# PSPortal native engine

An actual Windows/macOS/Linux executable and the shared in-process engine for
Android/iOS. GPL-3.0-only because it embeds **Mihomo v1.19.32**. The repository's
original OpenWrt/Lua implementation remains separate with its original license.

## Run on Linux first

Extract the matching release, copy `config.example.json` to `config.json`, and set:

- `listen_host`: this machine's specific RFC1918 LAN IPv4 address
- `allowed_clients`: exact PlayStation Portal/client LAN IPv4 addresses
- `subscription_url`: your final HTTPS proxy subscription URL

Then run:

```sh
./psportal -config config.json -check
./psportal -config config.json -status-interval 10s
```

Windows uses `psportal.exe`; macOS uses the Darwin archive matching its CPU.
Builds are unsigned. Cross-compilation does not prove operation on those systems.
This native CLI and the shared-core desktop mode are experimental until protocol/device
parity is validated. The existing separate-core desktop mode remains the fallback.

No administrator privileges, system proxy changes, TUN, routing, DNS-service,
firewall modifications or unrelated proxy process management are performed.
A host firewall may need a user-approved LAN inbound exception. Never expose this
listener on the Internet. IP allowlisting is not cryptographic client identity;
use only on a trusted LAN. `127.0.0.1` with the sole allowed client `127.0.0.1` is
also supported for local diagnostics. Wildcard listening is deliberately rejected.

Configure the client with this host's LAN IP and `listen_port` (10081 by default).
The host and client must remain on the same reachable LAN. This is an HTTP/CONNECT
TCP proxy, not a general VPN or UDP relay. Platform/game/client proxy support must
be checked on the actual device; the code cannot force applications to honor a
proxy setting.

## Behavior

- Starting binds the front listener only. Approved RFC1918/ULA destinations are
  resolved fail-closed and connected directly to a pinned numeric IP
- External traffic downloads a subscription over HTTPS with public-only DNS,
  no environment proxy, no redirects, a 20-second download deadline and 10 MiB cap
- Only proxy-node data is imported; top-level listeners, routes, DNS, scripts,
  external controllers and provider configuration are never imported
- Real Mihomo protocol adapters run in this application, not a separately running
  full Mihomo hub. `backend_port` and `api_port` are reserved compatibility fields;
  no listeners are created for them
- Client destinations are independently resolved and every answer must be public
  before entering an adapter. Numeric destinations are encoded in the encrypted
  protocol; original HTTP Host and TLS SNI bytes remain intact. This protects
  against remote DNS rebinding, with the tradeoff that a locally blocked or
  unavailable resolver cannot be bypassed through remote DNS. Ambiguous IPv4-mapped
  results from pure-Go hosts-file aliases fail closed; normal DNS A records and
  numeric approved addresses work
- Exact allowlists, strict HTTP framing/Host checks, bounded headers/concurrency,
  hop-header removal, streaming request bodies and CONNECT are supported
- `auto` prefers healthy Hong Kong, Japan, then other nodes in subscription order
- `prefer` tries the exact preferred node first, then the same fallback ordering
- `fixed` only uses the exact preferred node; absent/unhealthy nodes fail closed
- Health probes require HTTPS HTTP 204. Default target is Google's generate_204;
  change `health_url` if it is inappropriate for your provider/network
- No successful adapter means failure; external requests never fall back DIRECT
- Active external streams protect the pool. After `idle_seconds` without an active
  stream, owned adapters close. The next external request fetches nodes afresh
- Stop cancels requests and startup, closes the listener/streams, then closes owned
  adapters. Native callbacks are synchronous; invoke mobile Start/Stop off the UI
  thread. Upstream adapter cancellation/close behavior requires device testing
- Desktop can supply an absolute `subscription_file` instead of `subscription_url`
  (exactly one); it is read as a bounded regular-file snapshot in memory. Mobile
  bindings accept HTTPS URLs only. Subscriptions and node credentials stay in memory. `data_dir` is accepted for
  host compatibility but unused. Sanitized status excludes URLs and credentials;
  Mihomo diagnostic printing is silenced

Supported node families: ss, ssr, socks5, http, vmess, vless, snell, trojan,
hysteria, hysteria2, tuic, anytls. Node-specific transport options depend on the
pinned upstream adapter. Mesh/VPN nodes (WireGuard, Tailscale, ZeroTier, EasyTier),
routing aliases, custom certificate/private-key files and interface/routing-mark
or dialer-proxy overrides are deliberately excluded. Application UDP is disabled;
QUIC-based encrypted transports can still use outbound UDP to a pinned server peer;
port hopping and server migration to another peer are not supported. Raw SOCKS5/HTTP
upstreams are only encrypted when their own TLS configuration enables it.

## Build and test

Use Go 1.26+ (verified toolchain: Go 1.27.2) and Python 3.10+. Native config is a separate strict format: Python `core_path` is not accepted; native `subscription_file` is optional on
desktop and mutually exclusive with `subscription_url`. Use the native example when migrating.

Module versions and
checksums are pinned in `go.mod`/`go.sum`. Build flags disable unused mesh engines.

```sh
go test -tags no_easytier,no_zerotier,no_tailscale ./...
go test -race -tags no_easytier,no_zerotier,no_tailscale ./engine
python3 scripts/build.py --target linux/amd64
python3 scripts/build.py --all
python3 scripts/source_release.py
```

`dist` contains standalone archives, checksums and license notices. No installer,
service registration, OS permission changes, signing or publication is performed.
Tests use only local fixtures; the Mihomo SOCKS5 adapter is exercised end-to-end
for actual HTTP and CONNECT data paths. A test-only dialer maps a synthetic public
node to a loopback fixture; production has no such bypass. No real subscription
credentials or provider access are needed for tests.

For distribution, include the corresponding-source archive (including vendored
exact dependency source), GPL text and dependency notices with the executables.
`source_release.py` creates this source archive; it does not publish anything.
Review third-party terms and app-store GPL compatibility before distribution.

## Mobile bindings

The `mobile` package exports:

```go
Start(configJSON string) error
Stop()
Status() string
```

Status JSON contains `running` (front listener), `state` (adapter pool), `active`,
`selected_node`, `nodes` with name/healthy, `error`, and `stats`. Errors do not echo
subscription URLs, credentials or unsafe provider data. Desktop hosts can run `--desktop-child`: one JSON `event: ready` message signals
a bound listener; stdin EOF triggers Stop, so normal parent-process death closes
the owned listener. It does not require `--status-interval`.

Lifecycle calls serialize;
stop the previous instance before starting new configuration. Repeated Stop is safe.

`android/` is a real foreground-service host using the generated AAR, and `ios/`
is a real foreground-only host using the generated XCFramework. See their READMEs
and `scripts/mobile.sh`. They require platform SDKs and licenses to build; source
integration and generated binding headers are not an APK/IPA or device test.
iOS is foreground-only because a general TCP listener cannot promise continued
execution after app suspension. No remote dashboard substitute is used.

## Native platform CI

`ci/native-desktop.yml.example` is an inactive template for native Linux,
Windows and macOS runtime tests on both x64 and ARM64. It runs all Go tests, actual
CLI readiness/policy/stop/restart smoke tests, and Linux/macOS race checks, then
packages the tested host binary with matching vendored source, notices and evidence.
See `ci/README.md` for exact run provenance and verification limits. Native CI
has passed on all six targets: Linux x64/ARM64, Windows x64/ARM64 and macOS
Intel/Apple Silicon. These are loopback fixture and CLI runtime checks; physical
Portal, live provider, LAN-device, GUI, signing and notarization acceptance are
separate. Preparing a template or cross-compiling a binary alone is not evidence
of native execution.
