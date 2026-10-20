# 星渡 StarPass desktop: Windows, macOS and Linux

This is an implementation and native build path, not a signed or fully native-accepted release. One Tk desktop window can select either the established Python listener with separate Mihomo (`external`, the default), or the experimental shared native engine (`embedded`). Windows defaults to official Mihomo v1.19.32: development packages can include the pinned core with matching upstream source and license; otherwise Start sharing discovers a known stable installation or downloads and verifies the pinned Windows x64 release. No file selection is required in the normal workflow. Manual executable/experimental engine selection remains in Advanced settings. Embedded mode uses the project's native executable with Mihomo adapters linked into that one process. No installer, TUN adapter, administrator service, system proxy, router change, firewall change, or automatic startup is added by the app.

The application must remain running on an awake computer on the Portal's LAN. Normal Portal use permits only configured exact private LAN IPv4 clients. Clash product mode binds to `127.0.0.1` and requires the sole allowed client to be `127.0.0.1`; a real Portal cannot reach that loopback listener. Keep the Portal's IP stable with an existing DHCP reservation. The local Mihomo proxy and controller bind to loopback; the Portal-facing HTTP listener binds only to the configured private LAN address.

## Game, Mixed and Clash product modes

These describe listener inputs, independently of the subscription's routing rules:

- **Game** binds the selected LAN address and permits explicit device IPs, excluding
  the host's own LAN IP. LAN sharing is HTTP/CONNECT TCP, not arbitrary game UDP
- **Mixed** includes the host's own LAN IP in addition to the allowed devices.
  Configure local applications manually to use the displayed LAN address/port
- **Clash** binds only 127.0.0.1 and accepts only 127.0.0.1. Configure each local
  application to use that endpoint; LAN devices cannot reach this mode

No OS proxy, TUN, VPN, DNS, firewall or autostart setting is changed. Complete
profile behavior still requires the external Mihomo path; selecting Clash does
not make the experimental embedded adapter pool a complete Clash client.
The mode chooser preserves LAN form preferences, subscription and node choices.
Changing a mode while stopped only sets up the next run, and does not start it.
The effective bind/source policy is validated before the backend runs.
New `product_mode` records the selected use case; `product_lan_preferences`
retains the editable LAN address/list separately from an effective loopback
listener. Only explicit `product_lan_automatic: true` allows automatic subnet
lists to follow a changed network. Legacy saved allowlists are treated as manual,
not inferred to authorize access for an entire new subnet.

Start sharing reuses a saved local provider/profile only when `source_provenance`
records the same accepted subscription URL and exact file path, and revalidates the
bounded local content before launch. Editing the URL and saving does not relabel
an old file; legacy unknown provenance with a URL triggers import again. An explicit
file-picker choice records a local override, shown in the UI. Mode changes preserve
same-source node choices. Use **Refresh subscription** for an explicit refresh. Cached
accounting remains a timestamped server snapshot, not renewed by switching modes.

## Run from source on Windows

For the Windows development package, extract the entire folder and run `PSPortalProxy.exe`. Paste once to import and save a subscription. Import never opens a listener, changes LAN settings or prepares a core. Click **Start sharing** separately: it prepares a missing default core if needed, detects a supported LAN and starts the listener. A failed core download leaves the accepted subscription intact; retry Start sharing after correcting the connection. The same link is reused without another download; Refresh is explicit.

Source developers need a Tk-enabled Python 3.10–3.13 and the dependencies in `requirements-runtime.txt`; run `py -3 -m portalproxy.desktop` from `portable`. The Windows x64 GUI has the same automatic default-core fallback. Other platforms must supply their matching trusted executable in Advanced settings. CLI configuration remains explicit.

**Share existing Clash** reuses the current loopback proxy; no second Mihomo process is owned by StarPass. Only Game mode is available while linked, including configuration/start validation. Mixed and Clash remain visible but disabled. Stop sharing, then choose **Unlink and use standalone core** to restore the previous accepted subscription, node choices and mode. The original Clash is neither stopped nor reconfigured. Cached Clash quota/expiry is labelled read-only and may be absent or stale; it is separate from a directly imported subscription's accounting. Connection addresses and copy/export actions appear only after actual listener readiness.

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

Build separately on every OS and CPU architecture you intend to distribute. [PyInstaller is not a cross-compiler](https://pyinstaller.org/en/stable/operating-mode.html); a Linux build does not establish Windows or macOS compatibility. Use a clean build virtual environment with a Tk-enabled Python. The build script never installs packages or downloads Mihomo. To supply the zero-configuration Windows package, pass `--default-mihomo /path/to/official.exe --mihomo-source /path/to/mihomo-v1.19.32-source.zip`; both files must match the fixed release hashes. It retains the core, matching upstream source ZIP, license and commit notice. Without these options the Windows GUI prepares the pinned core when Start sharing is explicitly requested.

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
