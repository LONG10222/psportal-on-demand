# Portable desktop app: Linux-priority preview, Windows and macOS build paths

This is an implementation and native build path, not a signed or fully native-accepted release. One Tk desktop window can select either the established Python listener with separate Mihomo (`external`, the default), or the experimental shared native engine (`embedded`). External mode still uses a separately supplied trusted Mihomo executable with `-post-up` readiness support (tested with official v1.19.32). Embedded mode uses the project's native executable with Mihomo adapters linked into that one process. No installer, TUN adapter, administrator service, system proxy, router change, firewall change or automatic startup is added by the app. An explicit automatic-setup action can download checksum-pinned official Mihomo v1.19.32 on Windows x64; opening the app never downloads or starts it.

The application must remain running on an awake computer on the Portal's LAN. Normal Portal use permits only configured exact private LAN IPv4 clients. An optional development-only mode binds to `127.0.0.1` and requires the sole allowed client to be `127.0.0.1`; a real Portal cannot reach that loopback listener. Keep the Portal's IP stable with an existing DHCP reservation. The local Mihomo proxy and controller bind to loopback; the Portal-facing HTTP listener binds only to the configured private LAN address.

## Run from source on Windows

1. Install a current supported Python 3.10–3.13 from [python.org](https://www.python.org/downloads/windows/) with the Python launcher and Tcl/Tk components.
2. Obtain Mihomo for this machine's architecture from its [official upstream releases](https://github.com/MetaCubeX/mihomo/releases), verify its published integrity information, and extract it to a local folder. A Windows machine needs the Windows executable, not an OpenWrt/Linux binary.
3. Extract this project. Double-click `portable/launchers/windows.cmd`, or open a terminal in `portable` and run `py -3 -m portalproxy.desktop`.
4. Use **Paste link** or paste into the subscription field. One paste replaces the previous field contents, imports and privately saves a local snapshot; it never starts a listener. If typing manually, press Enter to import. Repeating the same accepted link does not download again. Use **Refresh subscription** explicitly to update the snapshot and quota metadata.
5. Choose the trusted Mihomo executable using the visible home-page control, then click **Start sharing** in the fixed footer. It detects the physical LAN once and validates configuration before launching. Stop/restart and reopening the window reuse the saved snapshot. A changed link must be imported before its old snapshot can be used to start. Advanced settings retain exact IP allowlists, local file selection, **Save / validate**, and **Start listener** for manual configurations. Wait for the listener's actual ready state before configuring devices.
6. In the Portal's current Wi-Fi advanced settings, keep automatic IP/gateway/DNS and set its manual HTTP proxy to this computer's LAN IPv4 and the configured proxy port, normally `10081`.
7. If Windows prompts for firewall access, review it yourself. Permit only the required application/inbound listener on your trusted private network, ideally scoped to the Portal's address. Do not allow public-network access. The app never changes firewall policy.

Use **Stop** before leaving. Closing the window asks to stop the listener and its owned core. Closing the controller's stdin also signals shutdown if its desktop parent disappears. If shutdown takes longer than expected, keep the window open and check the native acceptance steps. Repeated Start cannot launch a duplicate child from the same window. External mode separately locks its runtime directory; both modes fail if their listener address/port is already in use.

An imported subscription is saved as a private draft even before choosing a core
or configuring the LAN. It still must pass full validation on Start. A fingerprint
binds the accepted URL to the selected snapshot; it does not replace profile/core
validation. Account metadata from another Clash installation is shown only in
explicitly linked mode. Import failures stay inline and do not move the current
page. Refresh failures retain the previous snapshot. This GUI cache behavior does
not change URL-only CLI configurations, which still fetch on a cold core start.

## Choose an engine in the same app

- **external** remains the default for existing and new configurations. Choose your trusted Mihomo executable. Its existing Python listener, renderer, local-provider behavior and process lifecycle remain available as the fallback. No automatic engine switching occurs on failure
- **embedded** is experimental. Choose a matching trusted `psportal` native executable in **Embedded engine executable**, or use a package that explicitly includes the shared engine. The app never searches PATH or downloads a binary. An optional bundled binary is resolved only from `native/psportal-native` (`psportal-native.exe` on Windows) beside the packaged app executable or inside its internal bundle
- Stop before switching engines. The subscription URL/local provider, exact client allowlist, node selection and idle settings stay in the same configuration. A nonempty local-provider path overrides the URL in either mode. The native handoff omits that unused URL rather than copying its token
- Embedded mode opens only the Portal-facing listener. The separate local core/controller port values are retained for configuration compatibility but do not create sockets. No controller secret or separate Mihomo child is needed

Embedded mode currently allows the `ss`, `ssr`, `socks5`, `http`, `vmess`, `vless`, `snell`, `trojan`, `hysteria`, `hysteria2`, `tuic` and `anytls` adapter types. It excludes mesh/WireGuard, direct/bypass nodes, and arbitrary certificate/file/network overrides. Unsupported or unsafe nodes are ignored; a missing/unsupported fixed node fails closed rather than selecting another. Node endpoints must resolve only to allowed public addresses, unlike the separate-core fallback's ability to use administrator-configured local node endpoints. Do not assume every full Mihomo subscription behaves identically. Runtime adapter and physical Portal compatibility remain release gates.

The native schema also requires integer timing values, no more than 256 unique client addresses, a maximum of 4096 connections, and HTTPS subscription/health URLs on port 443. These additional limits apply only to embedded mode. `Save / validate` checks local fields without running the native binary or fetching a subscription; Start requires matching JSON readiness before showing **Listening**. A native launch error stays in embedded mode and does not silently change a fixed-node or engine choice.

CLI users can use the same configuration and command, `python -m portalproxy --config /absolute/path/config.json`. Set `"engine_mode": "embedded"` and `"native_path": "/absolute/path/to/psportal"` to dispatch to the shared engine; omit `engine_mode` or set `external` for the existing backend. `--check` also runs the native schema check in embedded mode without binding a listener or fetching a provider. A packaged app exposes the same CLI with `--backend`.

## macOS and Linux source launch

- macOS: use a Tk-enabled Python from [python.org](https://www.python.org/downloads/macos/), then run `python3 -m portalproxy.desktop` in `portable`, or open `launchers/macos.command`. Use a Mihomo macOS binary matching Apple Silicon or Intel.
- Linux: use your distribution's Python 3.10+ with its Tk package (commonly `python3-tk`), then run `./launchers/linux.sh` or `python3 -m portalproxy.desktop`. Use a Linux Mihomo binary matching the CPU; it needs executable permission.
- Linux without a graphical desktop: use `python3 -m portalproxy --config /absolute/path/config.json`. There is no requirement for Tk in CLI-only operation.
- An unsigned build may be blocked by operating-system trust controls. Review the source and build provenance or obtain a properly signed/notarized release. This guide does not tell you to disable security protections or bypass a warning.

Do not use public Wi-Fi or a network with untrusted clients. Guest-network isolation may prevent the Portal from reaching this computer. Wake/sleep and changing the computer's LAN address can interrupt operation; reconnect after correcting the address and restarting. The application is an HTTP/CONNECT proxy, not a VPN; native Portal behavior and traffic that ignores the configured HTTP proxy must be checked on the real device.

## Configuration and secrets

Default configuration locations:

- Windows: `%LOCALAPPDATA%\PSPortalProxy\config.json`
- macOS: `~/Library/Application Support/PSPortalProxy/config.json`
- Linux: `$XDG_CONFIG_HOME/PSPortalProxy/config.json`, or `~/.config/PSPortalProxy/config.json`

Pass `--config /absolute/path/config.json` to the GUI or use **Choose config…** to open an existing JSON configuration. The app validates before atomically saving, preserves advanced keys that are not in its form, and rejects a symlink as a save target. Stop the listener before editing or selecting another configuration. Create an alternate configuration by supplying a new `--config` path at launch.

The subscription URL is saved as plaintext in this local file so the proxy can use it. The GUI does not upload it to a management server. On POSIX systems files created by the GUI are mode `0600`; on Windows protection depends on the chosen folder's inherited ACLs. Use your private user directory, avoid shared folders and sync destinations, and do not share this file. Runtime provider/configuration files also contain secrets. Logs deliberately omit URLs and known tokens, but review any diagnostic before sharing it.

Embedded launch creates one temporary allowlisted JSON configuration in a private session directory, mode `0700` with a `0600` file on POSIX. It omits Python-only settings, unknown fields and the unused subscription URL when a local provider is selected. The temporary file is removed after failed launch or observed child exit. Stopping or closing the app cooperatively stops the native child before cleanup. A hard crash or forced OS termination can leave the private temporary directory behind; verify the child is stopped before removing a stale `psportal-native-*` directory. The child stops when its parent's stdin pipe closes, including parent disappearance. Neither mode sends subscription tokens on the command line.

The GUI displays sanitized live listener/core state, distinct active source IPs, connection counts and node controls over its child process pipes. Displaying status does not wake the core; explicit preparation and latency tests can. Owned direct-subscription controls support manual and measured fastest selection; linked Clash continues to manage its own nodes. See [live runtime controls and resource limits](runtime-controls.md). Real-node behavior still needs validation with the intended subscription and network.

## Build a native executable

Build separately on every OS and CPU architecture you intend to distribute. [PyInstaller is not a cross-compiler](https://pyinstaller.org/en/stable/operating-mode.html); a Linux build does not establish Windows or macOS compatibility. Use a clean build virtual environment with a Tk-enabled Python. The build script never installs packages or downloads Mihomo.

Windows, from `portable` in PowerShell:

```powershell
py -3.12 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv-build\Scripts\python.exe scripts/fetch_yaml_sources.py
.\.venv-build\Scripts\python.exe build.py
```

macOS/Linux, from `portable`:

```sh
python3 -m venv .venv-build
.venv-build/bin/python -m pip install -r requirements-build.txt
.venv-build/bin/python scripts/fetch_yaml_sources.py
.venv-build/bin/python build.py
```

The exact PyInstaller build dependency is pinned in `requirements-build.txt`; review and update intentionally before release. Its dependency installation requires access to the official package registry. The separate source-preparation command fetches the exact SHA-pinned public PyYAML/LibYAML source archives into the generated build cache; unchanged cache files can be reused offline. `build.py` never downloads them and fails if they are missing or modified. Do not package real configuration or subscription data.

`build.py` runs the unit tests, creates a one-folder application, checks bundled imports with `--smoke-test`, then writes an archive under `release/`. This is a bundling smoke test, not real GUI or device acceptance. Test skips are not passes. The intentionally available `--skip-tests` option is only for investigating build problems.

- Windows: `dist/PSPortalProxy/PSPortalProxy.exe`; distribute the entire folder/archive, including `_internal`. The executable hides its own console for normal desktop use. `PSPortalProxy.exe --backend --config C:\path\config.json --check` runs the bundled CLI check.
- macOS: `dist/PSPortalProxy.app`; distribute its `.tar.gz` archive so executable modes and bundle symlinks are preserved. The build applies a final outer ad-hoc seal after assembly, preserves nested binary bytes, and requires strict code-signature verification. The unified CI also verifies and launches the app extracted from the final archive. This is not Developer ID signing or Apple notarization; those remain separate release requirements. The executable inside is `PSPortalProxy.app/Contents/MacOS/PSPortalProxy`.
- Linux: `dist/PSPortalProxy/PSPortalProxy`; distribute the whole `.tar.gz` folder. Build on the oldest supported target distribution and test its libc/Tk compatibility.

In external mode a frozen app re-executes its own executable with `--backend`; source mode uses the same Python interpreter with `-m portalproxy`. In embedded mode the desktop launches the chosen native executable directly with an argument array and a private temporary configuration. Both stop through stdin EOF and are launched with argument arrays. The external
Mihomo core additionally uses a fixed, nonce-only `-post-up` readiness hook in its
private session directory, as documented in [runtime controls](runtime-controls.md#external-core-startup-readiness); no user data is interpolated into that hook. The default build includes Python and Tk and excludes both Mihomo and the optional native engine. An explicitly prepared dual-engine package may also include the native binary, its complete license notices and corresponding source; see that package's release manifest. Never bundle real subscription data, code-signing identities or credentials. Preserve all supplied license and third-party notices with the package.

`ci/portable-build.yml.example` is an inactive workflow draft. It is outside `.github/workflows`, has not been published or run, and uploads no artifacts. Activate it only after review. Every platform still needs the [native acceptance checklist](native-acceptance.md), including real Portal and real Mihomo testing.

### Implementation references

- [PyInstaller usage and console options](https://pyinstaller.org/en/stable/usage.html)
- [PyInstaller executable/runtime paths](https://pyinstaller.org/en/stable/runtime-information.html)
- [PyInstaller external-process environment guidance](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application)
- [Python subprocess process/pipe handling](https://docs.python.org/3/library/subprocess.html)


## Automatic Windows setup

The desktop keeps an explicitly configured core, then searches its managed versioned core directory, a frozen app sibling Mihomo and known Clash Verge stable-core install locations. It never chooses alpha builds or searches arbitrary PATH entries. Missing explicit paths are reported instead of silently replaced. “Set up automatically” repairs the choice, reusing a known stable executable first; otherwise Windows x64 downloads the official compatible v1.19.32 archive and verifies pinned SHA-256 before an atomic install. Other systems open the official release page. Download failure keeps the previous executable, gives inline retry/manual-selection guidance, and never starts sharing.

With no imported or pending subscription, Start sharing automatically reuses a detected loopback system HTTP proxy. Every linked restart re-detects its current port. A pending new subscription is never replaced by this automatic choice. Existing Clash retains its core and node controls. “Open Clash” opens the installed Windows Clash Verge, or its official releases if unavailable.

A separate existing-client card refreshes read-only Clash Verge subscription cache data every 10 seconds off the UI thread, including upload/download, used/total/remaining quota, expiry, remaining days and cache timestamp. It remains visible during sharing and cannot overwrite an independent subscription's accounting. Cache figures are explicitly not live traffic rates; other Clash distributions may not provide this cache format. Direct subscription accounting also remains visible after starting.
