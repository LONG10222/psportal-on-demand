## Unreleased: subscription and node preferences

- Persist auto/preferred/fixed intent independently, with exact-name filters and explicit REJECT sentinel
- Add optional authenticated legacy LuCI controls, root CLI and cache-only node status
- Resolve actual terminal nodes before readiness, with fixed-name equality and no direct terminal
- Explicit bounded/pinned HTTPS subscription fetch replaces automatic HTTP provider; live file reload can change routes
- Mock-only verification; actual OpenWrt/Mihomo/LuCI acceptance and deployment remain separate

# Changelog

## Unreleased

- Keep the listener responsive during core startup with a bounded readiness worker and queued external requests.
- Start the idle budget after readiness; retry failed startup and backend connection attempts without dropping LAN sessions.
- Deny loopback and special-use destinations, validate numeric/IPv6 authorities, and prevent backend DNS resolution from selecting private DIRECT routes.
- Preserve explicit RFC1918/ULA LAN access; document removed CGNAT/link-local compatibility and router-LAN management exposure.
- Add isolated listener, lifecycle, destination, and DNS regression coverage. Real OpenWrt/Mihomo acceptance remains a separate deployment check.

## 0.1.0

- Initial public source release with an explicit, single-client HTTP proxy listener.
- On-demand independent Mihomo core, private-address bypass, external idle shutdown.
- Own-subscription fallback order: Hong Kong, Japan, other regions.
- Interactive setup, staged installation, local private backups, and uninstall.
- English and Simplified Chinese setup guides; offline protocol and lifecycle tests.
