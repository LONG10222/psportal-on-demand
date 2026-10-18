# Client destination policy

The source-IP allowlist does not authenticate the Portal. Run the listener only
on a trusted LAN and do not expose it to the WAN. Destination checks add another
layer; they do not turn the service into an isolation boundary from the router
administrator or a compromised allowed client.

## Allowed LAN destinations

The launcher connects directly only to canonical IPv4 addresses in RFC1918
(`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) and IPv6 unique-local addresses
(`fc00::/7`). Ordinary LAN names can use approved addresses returned by the
configured local DNS server. Valid bracketed IPv6 authorities work with or
without an explicit port; the usual HTTP/CONNECT defaults are 80/443.

The router's RFC1918 or ULA LAN address remains reachable. This preserves LAN
web services, but also means the allowed client can reach router management
services listening on that LAN address. The policy does not discover all router
interface addresses, filter destination ports, or infer subnet-directed
broadcast addresses. Restrict sensitive LAN services with their own
authentication and firewall rules. Never bind the internal proxy or controller
to a LAN address; their loopback bindings and the controller secret still matter.

## Denied destinations and compatibility changes

Client destinations are denied for IPv4 loopback, unspecified/this-network,
link-local (including common cloud metadata addresses), shared CGNAT,
multicast/broadcast, reserved, documentation, benchmarking, and selected
protocol-assignment ranges. Localhost names, including subdomains, are denied.
Only four-part decimal IPv4 without leading zeros is accepted. Integer, octal,
hexadecimal, shortened and otherwise ambiguous numeric forms are rejected.

IPv6 loopback, unspecified, link-local, multicast, obsolete site-local,
IPv4-mapped/compatible/translation forms, 6to4, Teredo and other special-use
addresses are denied. ULA is allowed locally; external literals are limited to
`2000::/3` excluding `2001::/23`, `2001:db8::/32`, `2002::/16` and `3fff::/20`.
This is deliberately conservative: some globally reachable special-purpose
addresses are excluded too. Zone identifiers are unsupported.

Earlier releases classified loopback, CGNAT and link-local addresses as LAN.
Those exceptions are removed. Listener and allowed-client IPv4 addresses must
now be RFC1918. Networks using CGNAT or link-local addresses need an RFC1918 LAN
configuration; there is no automatic exception. Use a native RFC1918 or ULA
address rather than an IPv4-mapped IPv6 spelling.

## DNS and the backend

The launcher must apply the same destination classification to every inspected
DNS address, reject a response containing a denied destination, and connect
directly to the checked numeric LAN address. A denied answer must never become
an external fallback. Cached denials remain denied. The complete response, echoed
question, record bounds and CNAME chain are validated. Truncated/malformed
responses, nonzero DNS response codes (including NXDOMAIN), and unsupported
record classes fail closed. The launcher currently queries A records for names;
ULA access is available through IPv6 literals, not an AAAA lookup fallback.

Generated Mihomo rules reject special and LAN destinations before the external
fallback, with IP-rule DNS resolution enabled. There are no client `DIRECT`
rules: approved LAN traffic belongs to the launcher. This prevents the backend
from gaining a direct router-local route when it resolves a name differently.
Subscription/provider bootstrap and health traffic use the administrator's
configuration and are not client destination requests. A remote proxy and DNS
operator remain trusted parties; these checks do not control services or DNS
behavior at a remote exit or prevent every possible DNS-rebinding scenario.

Policy changes in generated core rules take effect only after regenerating the
local configuration and restarting through the normal deployment process.
Editing this repository alone does not change an installed router.

The loopback-only router smoke test checks that client loopback HTTP/CONNECT
requests are rejected, while a fake backend intercepts its external target
without Internet access. It does not test real RFC1918/ULA connectivity. Pure
policy and fake-runtime tests cover address classification and LAN routing;
real-router acceptance remains a separate deployment check.

References: [IANA IPv4 special-purpose registry](https://www.iana.org/assignments/iana-ipv4-special-registry/),
[IANA IPv6 special-purpose registry](https://www.iana.org/assignments/iana-ipv6-special-registry/),
and [Mihomo IP rules and DNS resolution](https://wiki.metacubex.one/en/config/rules/#no-resolve).

简要说明：仅 RFC1918 和 ULA 地址可走局域网直连。回环、链路本地、CGNAT、
IPv4 映射 IPv6 等特殊地址不再允许。路由器自身的 RFC1918/ULA LAN 地址仍可访问，
敏感管理服务需单独认证和防火墙保护。源码修改不会自动更新已安装的路由器配置。
