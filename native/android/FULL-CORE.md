# Android single-app routing and optional phone VPN

## Design and scope

Android v4 links the pinned Mihomo core through `native/androidcore` and the Android-only `native/androidmobile` binding. This is separate from the existing iOS and desktop experimental adapter binding. No external Clash app, downloaded executable, public controller or second proxy app is required.

The selected routing mode is Mihomo's `rule`, `global` or `direct` mode. It applies to the inputs selected before starting:

- **LAN sharing** (default on): an explicit HTTP/HTTPS CONNECT listener restricted to the configured LAN address and client allowlist. Existing private-LAN direct handling is retained; Internet requests enter Mihomo's tunnel.
- **Proxy this phone's apps** (default off): an Android `VpnService` input, established only after the device user grants the system VPN consent. It does not mean setting a system HTTP proxy. Only one VPN can be active per Android user/profile; another active VPN must be explicitly handled, never silently replaced.
- LAN-only, phone-VPN-only and both are distinct choices. VPN-only must not open a LAN listener. Both off is not a runnable session.
- **Continue in background** is a separate policy. It is best effort within Android foreground-service, Doze and manufacturer limits, not an unconditional always-on guarantee. See [BACKGROUND.md](BACKGROUND.md) and [PHONE-VPN.md](PHONE-VPN.md).

Turning phone VPN off leaves other phone apps on their normal network. Granting VPN consent alone does not start LAN sharing. The VPN uses an Android-owned descriptor; native auto-route, redirect and interface detection are disabled. The application itself is excluded from capture, and outbound sockets are protected to prevent loops. This host does not enable Android always-on/lockdown settings or change VPN settings outside the user's explicit in-app/system consent flow.

## Configuration safety

A subscription is untrusted configuration, not permission to modify the device. Android constructs a bounded sanitized Mihomo configuration before parsing it. Supported inline proxies, groups and rule types are explicit. Unsupported required providers, geodata, file paths, process hooks and unsafe secondary endpoints fail with a clear error. Application-owned listener/controller/TUN settings replace subscription host controls; subscription DNS, hosts and sniffer settings are not imported. The UI reports these overridden setting names without displaying their values. This can change profile semantics and must not be presented as exact arbitrary-profile compatibility.

A node-list subscription has no user rule set. Generated groups/rules and node-selection behavior are identified separately from full profile-owned groups. The old adapter-specific two-round fastest hysteresis is not automatically claimed for Mihomo URLTest groups.

Manual profile selection is bounded to actual `select` groups and explicit
members from the sanitized inline configuration. Group inventory omits member
lists; one bounded list is requested when the user opens it. Native selection
rechecks membership, session lifetime, active work and phone-VPN state. The
choice is session-local and reapplied only after membership validation on idle
reload; Stop discards it. Selector reads/writes are synchronized against nested
background health checks in the recorded 0004 source patch.

Full-core routing modes are not a claim of every upstream Mihomo feature, every rule/provider format or every Android packet type. In particular, unsupported UDP must never silently fall back to DIRECT when proxy routing was requested. Final supported protocol boundaries and tests are recorded with the release's validation results.

## Pinned source and local correction

Mihomo remains pinned to v1.19.32. The complete local source derivative in
`native/third_party/mihomo` retains the upstream license and applies narrowly
reviewed concurrency/lifecycle corrections found by real race and shutdown
regressions. `PSPORTAL-PATCHES` records original-file hashes, exact patches and
provenance; the source verifier rejects unrecorded changes. These corrections
are not race-check suppressions. The corresponding-source archive includes the
complete replacement and dependency source.

## Phone VPN network boundaries

The phone input captures IPv4 and IPv6 and uses application-owned encrypted DNS
with numeric HTTPS endpoints at Cloudflare (1.1.1.1) and Google (8.8.8.8), normal
certificate verification, and no plaintext DNS fallback. This does not preserve
Android Private DNS settings. DNS answers are mapped back to hostnames for
Mihomo domain rules; apps using their own encrypted DNS or cached addresses can
remain IP-only and must be covered by IP/final rules. ICMP forwarding is disabled.

Private, loopback and other non-public destinations are currently rejected at
the phone VPN boundary, even in DIRECT mode. Local-LAN phone applications may
therefore fail while the VPN is enabled. Turning phone VPN off restores normal
phone networking. The separate explicit LAN HTTP listener retains its existing
approved private-destination direct behavior.

## Verification and distribution

Host/unit tests and controlled TCP/UDP/DNS routing fixtures have passed. Real Android compilation and artifact provenance are separate exact-revision CI gates. No physical phone, screen-off endurance, carrier/hotspot, VPN consent interaction or game compatibility is claimed solely from source compilation.

The original project development signing key is absent from this environment. No replacement identity is generated. CI APKs remain unsigned and cannot be advertised as an install-ready upgrade.

The existing Apple app and iOS binding remain unchanged. Android implementation does not solve iOS background suspension or authorize an Apple Network Extension implementation.

## Official platform references

- [Android VPN lifecycle, consent, socket protection and routes](https://developer.android.com/develop/connectivity/vpn)
- [Android foreground service types and prerequisites](https://developer.android.com/develop/background-work/services/fgs/service-types)
- [Android Doze and App Standby limits](https://developer.android.com/training/monitoring-device-state/doze-standby)
