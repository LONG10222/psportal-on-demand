# Portable desktop port (development milestone)

Independent LAN HTTP/HTTPS-CONNECT proxy for Windows, macOS and Linux. The original
OpenWrt files are unchanged. This is **not a UDP/game-streaming relay** and does
not install a VPN or alter the host's system proxy, firewall, DNS or autostart.

## Run from source

Requires Python 3.10+ and a separately obtained, trusted Mihomo executable for your
OS/CPU. The backend uses Python's standard library only; the desktop UI uses
Tkinter (included in official Python Windows/macOS distributions, often a separate
package on Linux).

1. Copy `config.example.json` to a private user-owned folder as `config.json`.
2. Set your computer's RFC1918 LAN IPv4 address, the Portal's reserved address,
   absolute Mihomo path and your HTTPS subscription. Protect this file: its URL
   may contain an account token. On Windows JSON paths use `C:/...` or escaped `\\`.
3. From this directory: `python -m portalproxy --config /path/to/config.json --check`.
4. Start: `python -m portalproxy --config /path/to/config.json` or use the desktop
   launcher described in `docs/desktop.md` (when available).
5. Set the Portal's manual HTTP proxy to the computer's LAN address and port.
   Both devices must share a reachable trusted LAN. Keep the computer awake.
6. Stop with Ctrl+C or the desktop Stop button. Restore the Portal's proxy setting
   when no longer using the service.

Firewall access may require your OS's explicit approval. No automatic firewall
rule is created. Never forward this port from the Internet. The source IP allowlist
is not cryptographic authentication. The listener rejects wildcard binds. A localhost-only mode requires both
`listen_host: 127.0.0.1` and `allowed_clients: [127.0.0.1]`; this is for local
testing and is not reachable from a Portal. Loopback destinations remain denied.

## Behavior

The listener remains ready without a core. External requests serialize a single
owned Mihomo startup; established external connections prevent idle shutdown.
After all external connections close, the configured idle timer stops only the
owned process. The next external request starts it again. LAN destinations remain
direct and do not wake the core. DNS answers containing any prohibited address
fail closed. Backend reject rules prevent private-address direct bypass.

Subscription downloads require HTTPS, reject redirects, cap size at 10 MiB and
pin the TLS connection to checked public DNS addresses, enforce a transfer
deadline, and replace the provider atomically. Download errors never print the URL. Original
subscription YAML is passed as provider data only, not merged into executable
runtime settings. Mihomo `-t` validates before launch. Subscription fetches happen
on each cold start; an unavailable subscription fails startup rather than silently
using an old version. No periodic provider refresh is implemented yet. Alternatively set an absolute
`subscription_file` to your local Clash/Mihomo provider YAML/JSON; this explicitly
overrides the subscription URL and is copied into the private session on each
core start. A local file can be used without a subscription URL.

Selection modes: `auto` prefers Hong Kong, then Japan, then other nodes;
`prefer` (also accepts `preferred`) puts the exact preferred name first and
retains fallback; `fixed` allows only that exact node and rejects missing nodes.
Fixed-node selection has passed the real Mihomo v1.19.32 controlled-upstream test;
automatic/preferred health ordering still needs broader real-node validation. Fixed mode never silently switches to another node.

The controller and core proxy bind only to 127.0.0.1, with a random per-session
controller secret. A private session directory is deleted on clean shutdown.
An owner lock rejects a second instance. After an unclean crash, verify both old
launcher and core are stopped before removing the documented `owner.lock` file.
Automatic crash recovery and service installation are not yet implemented.

## Tests and release status

Run `python -m unittest discover -s tests -v` from this directory. Process tests
explicitly use `tests/fake_core.py`, a controlled local fixture, **not Mihomo**.
Network tests use loopback fixtures. Their success does not prove real Portal,
subscription, remote-node, Wi-Fi, native Windows/macOS or GUI operation.

Real Mihomo v1.19.32 has additionally passed HTTP/CONNECT, exact fixed-node
selection and active/idle lifecycle tests against a controlled loopback upstream.
This is not an Internet subscription or physical Portal test. Run it explicitly
with `MIHOMO_BINARY=/trusted/path/mihomo python -m unittest discover -s tests -p test_real_core.py`.

Native packaging/build instructions are under `packaging/` and `docs/`. Do not call
this a completed four-platform release. Remaining release gates include real
Mihomo compatibility, native desktop executable builds/runs, GUI inspection,
physical Portal end-to-end tests, and separate mobile-native implementation.

Android requires a bundled native core and a user-started foreground service;
this Python desktop process launcher is not an Android implementation. iOS cannot
host a persistent LAN proxy via a Packet Tunnel extension: an honest foreground
port must embed its core and stop on background. Android APK/iOS app, provisioning,
license compliance and device tests remain separate work. See the project port
status report for evidence and limitations.
