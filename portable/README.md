# Portable desktop port (development milestone)

Independent LAN HTTP/HTTPS-CONNECT proxy for Windows, macOS and Linux. The original
OpenWrt files are unchanged. This is **not a UDP/game-streaming relay** and does
not install a VPN or alter the host's system proxy, firewall, DNS or autostart.

The same desktop app now has an experimental `embedded` engine option alongside
the default `external` Python/separate-Mihomo fallback. Choose the shared native
engine executable in the window; no binary is downloaded and no failure silently
switches engines. Existing configurations remain external unless explicitly
changed. See [engine selection and compatibility limits](docs/desktop.md#choose-an-engine-in-the-same-app).

## Run from source

Requires Python 3.10+ and a separately obtained, trusted Mihomo executable for your
OS/CPU in default external mode. Embedded mode instead needs the matching shared
native executable, configured as `native_path` with `engine_mode: embedded`.
The fallback backend uses Python's standard library only; the desktop UI uses
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

The process/controller details below describe default external mode. Embedded
mode keeps the listener but wakes and idles adapters inside its single native
process; it has no separate core/controller sockets. Its protocol and safety
limits are documented in the desktop guide.

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

Opt-in desktop/native dispatch and clean-shutdown checks use
`PSPORTAL_NATIVE_BINARY=/trusted/path/psportal python -m unittest discover -s tests -p test_embedded.py -v`.
Set `PSPORTAL_DUAL_BINARY` to a rebuilt packaged desktop executable to include
the frozen embedded CLI test. These checks exercise actual native config/readiness,
restricted destinations, empty local-provider failure, stdin EOF and restart;
they do not establish real-node traffic, GUI appearance or device compatibility.

Native packaging/build instructions are under `packaging/` and `docs/`. Packaged
Windows x64, Linux x86_64 and macOS arm64 builds now have revision-specific
runtime evidence, alongside native CLI tests on six OS/architecture combinations.
See the [current platform record](../docs/portable-status.zh-CN.md) and
[downloads](../docs/downloads.zh-CN.md) for exact artifacts, tested environments,
signing status and remaining device/provider acceptance. Local fixture tests
alone do not establish those platform results.

Actual Android and iOS hosts are in `native/android` and `native/ios`; the Python
process launcher is desktop-only. Android uses a bundled native core and a
user-started foreground service. iOS is foreground-only and stops on background;
a Packet Tunnel extension cannot be repurposed as a persistent LAN proxy.
Physical Portal/phone tests, encrypted-node end-to-end acceptance, Android Doze
and device provisioning remain separate gates. Do not describe the project as
a fully accepted cross-platform production release.
