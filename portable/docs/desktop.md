# Portable desktop app: Windows first, macOS and Linux

This is an implementation and native build path, not a signed or fully native-accepted release. The backend uses Python's standard library; the optional local desktop window uses Tk. Mihomo is a separate executable supplied by the user. No installer, TUN adapter, administrator service, system proxy, router change, firewall change, automatic startup, or downloaded core is added by the app.

The application must remain running on an awake computer on the Portal's LAN. Normal Portal use permits only configured exact private LAN IPv4 clients. An optional development-only mode binds to `127.0.0.1` and requires the sole allowed client to be `127.0.0.1`; a real Portal cannot reach that loopback listener. Keep the Portal's IP stable with an existing DHCP reservation. The local Mihomo proxy and controller bind to loopback; the Portal-facing HTTP listener binds only to the configured private LAN address.

## Run from source on Windows

1. Install a current supported Python 3.10–3.13 from [python.org](https://www.python.org/downloads/windows/) with the Python launcher and Tcl/Tk components.
2. Obtain Mihomo for this machine's architecture from its [official upstream releases](https://github.com/MetaCubeX/mihomo/releases), verify its published integrity information, and extract it to a local folder. A Windows machine needs the Windows executable, not an OpenWrt/Linux binary.
3. Extract this project. Double-click `portable/launchers/windows.cmd`, or open a terminal in `portable` and run `py -3 -m portalproxy.desktop`.
4. Fill in this computer's private LAN IPv4, the Portal's private IPv4, the Mihomo executable path and your own HTTPS subscription URL. Node selection is `auto`, `prefer` or `fixed`; the latter two require the exact node name. The URL is hidden in the form. Alternatively choose a local Clash/Mihomo provider YAML file (maximum 10 MiB); a nonempty file path takes precedence over the URL and avoids a subscription download. Clear it to resume using the URL.
5. Select **Save / validate**, then **Start listener**. Read the status log: a running process is not proof that the listener is ready; wait for `Proxy ready ...`. Save validates local configuration without fetching the subscription. A real external request triggers the core and either the subscription fetch or local provider copy.
6. In the Portal's current Wi-Fi advanced settings, keep automatic IP/gateway/DNS and set its manual HTTP proxy to this computer's LAN IPv4 and the configured proxy port, normally `10081`.
7. If Windows prompts for firewall access, review it yourself. Permit only the required application/inbound listener on your trusted private network, ideally scoped to the Portal's address. Do not allow public-network access. The app never changes firewall policy.

Use **Stop** before leaving. Closing the window asks to stop the listener and its owned core. Closing the controller's stdin also signals shutdown if its desktop parent disappears. If shutdown takes longer than expected, keep the window open and check the native acceptance steps. Repeated Start cannot launch a duplicate child from the same window; the backend separately prevents two owners of the same runtime directory.

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

The GUI's log reports listener lifecycle and sanitized diagnostics, not live node/core telemetry. It does not query the controller or wake a core to display status. `auto`/`prefer` fallback and real node health depend on the selected Mihomo release and subscription; check actual behavior before relying on it.

## Build a native executable

Build separately on every OS and CPU architecture you intend to distribute. [PyInstaller is not a cross-compiler](https://pyinstaller.org/en/stable/operating-mode.html); a Linux build does not establish Windows or macOS compatibility. Use a clean build virtual environment with a Tk-enabled Python. The build script never installs packages or downloads Mihomo.

Windows, from `portable` in PowerShell:

```powershell
py -3.12 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv-build\Scripts\python.exe build.py
```

macOS/Linux, from `portable`:

```sh
python3 -m venv .venv-build
.venv-build/bin/python -m pip install -r requirements-build.txt
.venv-build/bin/python build.py
```

The exact PyInstaller build dependency is pinned in `requirements-build.txt`; review and update intentionally before release. Its dependency installation requires access to the official package registry. Do not package real configuration or subscription data.

`build.py` runs the unit tests, creates a one-folder application, checks bundled imports with `--smoke-test`, then writes an archive under `release/`. This is a bundling smoke test, not real GUI or device acceptance. Test skips are not passes. The intentionally available `--skip-tests` option is only for investigating build problems.

- Windows: `dist/PSPortalProxy/PSPortalProxy.exe`; distribute the entire folder/archive, including `_internal`. The executable hides its own console for normal desktop use. `PSPortalProxy.exe --backend --config C:\path\config.json --check` runs the bundled CLI check.
- macOS: `dist/PSPortalProxy.app`; distribute its `.tar.gz` archive so executable modes and bundle symlinks are preserved. Code signing and Apple notarization are separate release steps and are not configured here. The executable inside is `PSPortalProxy.app/Contents/MacOS/PSPortalProxy`.
- Linux: `dist/PSPortalProxy/PSPortalProxy`; distribute the whole `.tar.gz` folder. Build on the oldest supported target distribution and test its libc/Tk compatibility.

A frozen app re-executes its own executable with `--backend`; source mode uses the same Python interpreter with `-m portalproxy`. No shell is involved in backend/core launch. The build includes Python and Tk but deliberately excludes Mihomo, subscription data, code-signing identities and credentials. Preserve the supplied license and third-party notices with the package.

`ci/portable-build.yml.example` is an inactive workflow draft. It is outside `.github/workflows`, has not been published or run, and uploads no artifacts. Activate it only after review. Every platform still needs the [native acceptance checklist](native-acceptance.md), including real Portal and real Mihomo testing.

### Implementation references

- [PyInstaller usage and console options](https://pyinstaller.org/en/stable/usage.html)
- [PyInstaller executable/runtime paths](https://pyinstaller.org/en/stable/runtime-information.html)
- [PyInstaller external-process environment guidance](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application)
- [Python subprocess process/pipe handling](https://docs.python.org/3/library/subprocess.html)
