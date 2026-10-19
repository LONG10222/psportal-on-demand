# Android full Mihomo engine

This package and `../androidmobile` are the Android-only runtime. Desktop and
Apple hosts continue using their existing packages. It links pinned Mihomo
v1.19.32 configuration parsing, `hub/executor` and `tunnel.Tunnel`, rather than
implementing routing modes over separately selected outbound adapters. There is
no external Clash process or controller HTTP socket.

## Session and routing

`routing_mode` is `rule` (default), `global` or `direct`. These are the actual
Mihomo tunnel modes, fixed for each Start/Stop session. `lan_enabled` defaults to
true; `phone_vpn` defaults to false. At least one is required. VPN-only sessions
do not bind the LAN HTTP listener. Ordinary phone networking is unchanged when
phone VPN is off. Phone VPN separately requires Android's system consent and a
live VpnService; no development-host VPN is created by the Go tests.

The LAN frontend remains the established exact-client-IPv4 ACL and bounded HTTP/
CONNECT parser. It supplies external streams to the full Mihomo tunnel through
in-process pipes. Its existing private-LAN direct path is preserved. It does not
provide UDP proxy service to LAN clients.

Phone VPN uses one consented TUN descriptor and the same core, with explicit
socket protection, IPv4 and IPv6 handling, and owned DNS. In this initial policy,
phone VPN rejects private/special destinations, including intentional DIRECT to
RFC1918/ULA addresses. LAN apps needing those addresses must use VPN off. This
is a deliberate compatibility limit, not a claim that every app/protocol works.
The packet path is tested using local fixtures; device acceptance is separate.

## Bounded subscription policy

The HTTPS download is public-destination-only, refuses redirects, requires HTTP
200, and is limited to 10 MiB. It is held in memory for the running session.
Supported input is an object containing 1–1000 inline proxy nodes and optionally
up to 256 inline groups and 20,000 inline rules. Parsing happens only after the
application builds a new, restricted RawConfig. The original document is never
passed wholesale to Mihomo's parser.

- Nodes: ss, ssr, socks5, http, vmess, vless, snell, trojan, hysteria,
  hysteria2, tuic and anytls, subject to the option/address restrictions
- Groups: select, fallback, url-test and load-balance with explicit inline members
- Rules: DOMAIN, DOMAIN-SUFFIX, DOMAIN-KEYWORD, IP-CIDR, IP-CIDR6, DST-PORT,
  NETWORK and MATCH; an explicit rule list must end in MATCH
- Proxy/rule providers, geodata/process/compound rules, sub-rules, provider-based
  group membership, arbitrary file/certificate reads, routing/interface overrides,
  alternate TUIC IP, XHTTP download settings and Hysteria realm/STUN settings
  are rejected with a visible error
- Subscription listeners, TUN, DNS, hosts, controller, external UI, NTP, firewall,
  profile caching, custom TLS and process settings are not imported. A bounded
  warning lists recognized overridden settings without reflecting unknown keys
- No geodata/provider downloads, external processes or subscriber-chosen service
  listeners are permitted. Owned phone DNS uses numeric HTTPS resolvers; other
  mobile app settings are untouched

Explicit node `udp: false` and group `disable-udp: true` restrictions are
preserved. Nodes without an explicit UDP setting keep the upstream default.

A proxies-only subscription gets actual Mihomo fallback, URL-test and select
policy groups. Auto uses source order, prefer uses a preferred-first fallback,
fixed uses an exact selector, and fastest uses native URL-test tolerance. These
are not the older adapter engine's geography ordering or two-round hysteresis.
A subscription that supplies groups owns its routing policy; it requires the
app's node selection mode Auto and exposes live group state without pretending
that a global node button rewrites its rule graph. Changing mode, tolerance or
preferred fallback order requires Stop/Start. A simple generated selector can
be changed only with no active connections and no running phone VPN.

## Ownership and fail-closed behavior

Mihomo has process-global state, so only one Android Engine may own it. Each
loaded profile receives an application-owned runtime guard that bounds outbound
dials to cancellation, tracks TCP/UDP sockets and rejects late health callbacks.
Startup gates dials until its resolvers are ready. Stop/idle retirement suspends
new ingress, cancels owned dials and DNS, closes connections, and joins every
queued TCP/UDP job plus spawned UDP sender/reader before clearing global state.
The pinned derivative contains explicit tunnel admission/drain APIs; opting in
permanently rejects deprecated unversioned TCPIn/UDPIn channels. Phone-only stop
also tracks its own handlers and packets while the LAN session can continue.
Phone DNS uses bounded synchronous verified HTTPS requests, without detached
refresh, singleflight workers or connection pools. Subscription failures never select a direct
fallback. Explicit DIRECT rules and Direct mode remain intentional choices.

Mihomo's ordinary rule matcher can skip an unsupported UDP adapter and default
to DIRECT. The Android wrapper makes that case a terminal rejection. It changes
existing adapter wrappers in place before workers start, preserving group and
provider references. The phone packet boundary keys UDP by session, source and
full destination, bounds pending/open flows, and owns their cancellation and
close. This prevents a later proxy-required destination from reusing an earlier
DIRECT socket on the same source port.

## Tests and license

`go test -tags=no_easytier,no_zerotier,no_tailscale,with_gvisor ./androidcore
./androidmobile` covers the sanitizer, independent LAN/VPN scopes, actual Mihomo
rule/global/direct routing through controlled HTTP adapters, normal host-network
non-interception, source failure, cancellation/restart, stale callbacks, DNS name
mapping, protected socket failures and bounded phone UDP ownership. Race tests
include 150 generations of 256 queued UDP packets, blocked pre-rule TCP/UDP
metadata, concurrent packet Send/Close, and descendant admission/drain barriers.

A separate wire fixture exercises the actual Mihomo SOCKS5 UDP-associate
handshake and captures the RFC1928 datagram at a controlled local upstream.
UDP isolation tests run actual Mihomo rule/NAT/packet-sender logic and the production phone
boundary, with test-only transports redirecting payloads to a local capture
socket. They contrast unsupported selected proxy rejection, explicit DIRECT,
and same-source DIRECT/proxy transitions in both directions. They do not prove
Android device, public subscription or every protocol compatibility.

The native combination is GPL-3.0-only and must ship the corresponding source,
license and dependency notices. See `../LICENSE`, `../THIRD_PARTY_NOTICES.md` and
any pinned upstream patch provenance accompanying this source release.
