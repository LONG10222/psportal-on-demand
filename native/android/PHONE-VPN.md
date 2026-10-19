# Optional Android phone routing

## Product contract

- LAN explicit proxy defaults **on**; phone-app routing defaults **off**. A run may select either or both. Both off is rejected.
- Phone routing requires the Android `VpnService.prepare` consent flow before the session starts. A detected existing VPN is reported as a conflict. No always-on, boot start, sticky restart or VPN security setting is enabled.
- `rule`, `global` and `direct` apply to the selected session. Changes require Stop and a new Start. Turning phone routing off during a combined run leaves LAN sharing active; turning it off in a phone-only run ends the session. Notification Stop stops all selected options.
- The host application's own package alone is excluded from the VPN to avoid bootstrap and pre-existing-socket loops. New embedded-core and owned-DNS sockets must also pass `VpnService.protect`; false or failed protection rejects the socket.
- IPv4 and IPv6 default routes are installed by the consented Android service. TCP and supported-node UDP use the embedded core. Unsupported UDP targets fail rather than falling through to DIRECT. ICMP forwarding is disabled. Phone private/LAN/loopback destinations are blocked in every mode; this differs from the separate explicit-LAN-proxy policy.
- The tunnel is not an always-on kill switch. Revocation, network loss, Stop and startup failure remove the tunnel; Android resumes its ordinary networking. No automatic resume occurs.

## DNS and ownership

The service advertises IPv4 and IPv6 tunnel DNS addresses. An app-owned handler captures TCP/UDP port 53, limits concurrent work to 64, limits incoming frames to 4096 bytes, snapshots the resolver service, and joins all queries and TCP handlers on Stop.

DNS uses verified HTTPS to numeric Cloudflare `1.1.1.1` and Google `8.8.8.8` endpoints. Each query has a synchronous, separately owned HTTP/1.1 TLS connection. There is no background refresh, detached singleflight worker, connection pool, system-DNS fallback or imported subscription DNS policy. The resolver has its own 64-operation cap and closes and joins its sockets/dials before core teardown. The entire HTTP wire response is bounded at 80 KiB, with a separate 65535-byte DNS-body bound. DNS ID/question checks, certificate verification and destination/protection checks are enforced.

Mihomo DNS mapping associates observed A/AAAA answers with domain rules. Apps using their own encrypted DNS or cached addresses may supply only IP destinations; this does not promise domain-rule visibility for every app. Android Private DNS settings are not imported. Initial subscription/bootstrap resolution still uses the host app's ordinary OS resolver before the packet tunnel is established. The DNS providers can see queried domains.

Each UDP flow has a session-and-destination-specific NAT key, so a phone socket changing from a DIRECT destination to a proxy destination cannot reuse the first route. Pending and open UDP flows share a 256-flow budget. TCP ingress is capped at 256 handlers. Cancellation, late result rejection, socket closure, and upstream ingress joins retire a generation before global routing state can be cleared or replaced. The vendored upstream sender admission/close and ingress-lifetime patches are essential to this guarantee; see its patch provenance.

Java owns the original consented packet descriptor. Go duplicates it with close-on-exec and owns only the duplicate. External-FD mode does not configure interfaces or routes; `EXP_DisableDNSHijack` explicitly disables upstream shell/system-DNS restoration. Native DNS/packet work is stopped before Java closes its descriptor and releases socket protection. A stable process-local socket dispatcher restores its previous logical behavior after the engine owner retires.

## Source and fixture validation

These checks operate on source and controlled local fixtures, without activating a host VPN:

- State-generation tests cover stale startup, Stop, cleanup and repeated stop; host structural checks cover consent, service declarations, defaults, separate options and callback gates.
- Real core routing fixtures cover TCP rule/global/direct. UDP fixtures capture actual local datagrams and exercise unsupported-node rejection, supported-node routing, same-source DIRECT-to-proxy and proxy-to-DIRECT transitions, and SOCKS5 UDP-associate wire format.
- A/AAAA wire-DNS fixtures demonstrate DNS mapping followed by a DOMAIN-rule TCP route.
- Resolver fixtures use verified local TLS and reject untrusted certificates, redirects, mismatched DNS IDs/questions, oversized headers/body and failed socket protection. Blocked query, dial and connected TLS tests prove cancel/join behavior.
- Phone ingress fixtures block a real rule match, saturate a UDP sender, request Stop, then release matching and restart. TCP fixtures prove phone-only Stop cancels pending dials and joins handlers. Upstream fixtures cover queued child lifetimes and serialized sender shutdown.
- Offline Go tests run under the race detector. Android/arm64 source compilation uses `with_gvisor`; host tests never create a TUN. Generated gomobile interfaces have been inspected for descriptor/protector signatures.

Example offline checks from `native/`:

```sh
GOPROXY=off go test -race -tags=no_easytier,no_zerotier,no_tailscale ./androidcore ./androidmobile
GOOS=android GOARCH=arm64 CGO_ENABLED=0 GOPROXY=off go build -tags=no_easytier,no_zerotier,no_tailscale,with_gvisor ./androidcore ./androidmobile
```

These are not Android device/emulator acceptance results. APK/AAR/JNI integration, OS consent/conflict/notification behavior, actual IPv4/IPv6 packet capture, revocation, underlying-network loss and foreground-service eligibility still require Android CI/device validation. No host VPN was activated and no replacement signing key was created.
