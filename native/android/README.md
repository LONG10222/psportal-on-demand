# PSPortal Android host

Native Android host for the shared Go/Mihomo adapter engine in `../mobile`.
The Activity edits a per-run configuration; an explicitly started foreground
service owns the embedded JNI engine. There is no Python runtime, VPN service,
root requirement, shell subprocess or downloaded executable in the app.

**Current source (0.3.0-dev / code 3):** Chinese-first simple home, hot language/theme
controls, one-click LAN setup, subscription accounting and live native node controls.
168 JVM assertions, Android Java/resource compilation and three Java-to-Go config
round-trips pass. A fresh AAR/APK build and device UI validation remain pending.

**Historical baseline (2026-10-18, build 1):** the real arm64/x86_64 engine AAR and
APK built successfully. Compilation, release lint, 90 JVM assertions, Java-to-Go
configuration round-trip and 16 KiB ELF/APK alignment checks pass. An explicitly
authorized project-only development signing identity was used for isolated
emulator tests; ordinary Gradle/CI builds remain unsigned.

That historical signed candidate passed actual Android 8 / API 26 installation, Activity
and JNI startup, controlled LAN HTTP/CONNECT, source-IP filtering, background
continuation and Recents teardown. That runtime test found and verified a fix for
an idle service left behind after task removal. Android 16 / API 36 ATD also passed
installation, visible notification permission denial/grant, connected-device
foreground-service enforcement, real JNI startup and Activity Stop. ATD cannot
establish full notification/Recents UI or Doze behavior. See
[VALIDATION.md](VALIDATION.md) for exact artifacts and test boundaries. Physical Portal,
arm64/16 KiB hardware, external subscription and screen-off/OEM behavior remain
unverified; this is a development build, not a parity or release signoff.

## Runtime behavior

1. Connect phone and device to a trusted reachable Wi-Fi/Ethernet LAN. Client
   isolation must not separate them.
2. Paste your HTTPS proxy-provider subscription. Automatic preparation uses the
   real /24–/30 subnet; Advanced retains explicit client IP and port configuration.
3. Tap **Prepare & start** while the Activity is visible. Android 13+ notification
   permission is requested if needed. This app refuses to serve without a visible
   notification, although Android technically permits some foreground services
   without notification permission.
4. Set the Portal's manual HTTP proxy to that address and port (default 10081).
   Public HTTP/CONNECT requests wake the embedded adapters on demand. The native
   engine, not this UI, owns node selection, allowlisting, direct LAN routing and
   idle teardown. In Android's `RuntimeStatus`, `running` means listener active,
   `state=listening` means waiting for device traffic, and `core_state=stopped`
   means the idle adapters are released. These states can coexist normally.
   The legacy `Status` binding retains its core-state meaning for existing iOS.
5. Stop from the Activity or persistent notification. Removing the app from
   Recents also requests a complete stop. Restore the Portal's proxy setting when
   no longer using the host.

The app never starts at boot, never uses sticky service restart, and never resumes
an old session after process death. Start/Stop/status operations share a single
process-owned executor; live node probes use a separate owned executor so Stop
can cancel a probe without waiting behind it. New starts are rejected until both
native teardown and the old probe finish; queued starts canceled by Stop never
open a listener. Native work runs off the UI thread.
The foreground notification remains while normal teardown runs. The service also
stops when the configured LAN address disappears, notifications are disabled, or
required local-network permission is revoked. An OS force-stop/process kill may
skip callbacks; the OS then closes process sockets.

This is an HTTP / HTTPS-CONNECT proxy, **not a UDP/game-streaming relay**. No system
proxy, Wi-Fi configuration, routing, DNS or firewall setting is changed. No wake
lock, battery-optimization exemption, always-on VPN or boot receiver is installed.
Foreground service status does not guarantee uninterrupted Wi-Fi during Doze,
OEM battery controls or thermal pressure. Background and screen-off behavior
still requires physical-device tests. The source-IP allowlist is not strong
client authentication; never expose the listener to the Internet.

## Private data

The subscription field is masked, excluded from view-state/autofill persistence,
cleared after Start, and not written to preferences. The Activity is marked secure
to prevent screenshots/Recents previews containing credentials. Non-secret fields
are stored in app-private preferences. Backups and device-transfer extraction are
disabled. Engine data lives under the app-private `files/runtime` directory.
Native subscriptions/providers contain credentials; native cleanup and caching
behavior must be audited alongside the engine. Logs/UI never display Java
exception messages from the engine. URL tokens are not passed to notifications.
There is no telemetry or crash-upload integration.

## Android platform choices

- Application ID: `org.psportal.host`
- min SDK 26, compile/target SDK 36
- Android Gradle plugin 8.13.2, Gradle 8.13, Java language level 17
- Service type: `connectedDevice`, for an external Portal over a network
- `FOREGROUND_SERVICE_CONNECTED_DEVICE`, `FOREGROUND_SERVICE` and `INTERNET`
  are declared. `CHANGE_NETWORK_STATE` satisfies the documented connected-device
  foreground-service prerequisite; this app does not invoke network-changing APIs
- `POST_NOTIFICATIONS` is requested only from the visible Activity
- No boot receiver, exported service, `VpnService`, storage permission or installer

### Android 17 / target SDK 37

The current official guidance explicitly says apps targeting SDK 36 or lower must
not declare/request `ACCESS_LOCAL_NETWORK`; `INTERNET` grants compatibility access
on Android 17. Therefore this target-36 manifest deliberately omits it.

Before increasing target SDK to 37:

1. Upgrade compile SDK and AGP to a combination supporting API 37.
2. Add `android.permission.ACCESS_LOCAL_NETWORK` to the manifest.
3. Update the project guardrail test to match the new target and declaration.
4. The existing `Permissions.requiresLocalNetwork()` runtime branch then enables
   the visible Activity explanation, system permission request, denial handling
   and service permission gate. Do not start native listening before grant.
5. Test grant, first denial, permanent denial, settings revocation during a run,
   and return from background on Android 17. Verify any newer platform changes.

Official references (checked 2026-10-18):

- https://developer.android.com/develop/background-work/services/fgs/service-types#connected-device
- https://developer.android.com/privacy-and-security/local-network-permission
- https://developer.android.com/build/releases/agp-8-13-0-release-notes
- https://developer.android.com/develop/background-work/services/fgs/launch

## Build without generating signing credentials

Use a JDK 17+ (JDK 21 works), Go matching `../go.mod`, Android SDK platform 36,
Build Tools 35.0.0, and a modern NDK with 16 KiB page support (tested r30,
30.0.16248370). Install only after accepting the applicable SDK terms yourself or
explicitly authorizing acceptance:

https://developer.android.com/studio/terms

The build scripts do not run `sdkmanager --licenses`, write fabricated license
acceptance files, or auto-download Android SDK components. `android.builder.sdkDownload`
is disabled. Missing SDK/NDK is a real build blocker, not a reason to package a
fake native engine. Install paths may be task-local; Android Studio is unnecessary.

Set `JAVA_HOME`, `ANDROID_HOME`, `ANDROID_NDK_HOME` and add the JDK/Go tools to PATH.
Build the actual `../mobile` package with the engine's pinned tool workflow:

```sh
# From native/; choose a task-local GOBIN and place it on PATH:
./scripts/mobile.sh tools
./scripts/mobile.sh android
```

The Android build uses `-target=android/arm64,android/amd64 -androidapi=26`,
`-javapkg=org.psportal.engine`, the engine's supported mobile feature tags and
16 KiB linker alignment. It collects and copies full dependency licenses with
`ENGINE-NOTICES.txt` and writes `android/app/libs/psportal-engine.aar`. It requires
an already installed/licensed SDK and NDK and never accepts agreements itself.

The generated Java API is `org.psportal.engine.mobile.Mobile.start(String)`
(throws Exception), `.stop()` and `.status()`. The native implementation is called
directly. The AAR must include `classes.jar` and `jni/arm64-v8a/libgojni.so`. The
Gradle build fails before compilation if it or ENGINE-NOTICES.txt is missing. An x86_64 slice is useful
for emulator testing; real arm64 hardware remains required.

Collect the native dependency license notices with the engine's
`../scripts/licenses.sh` release workflow, preserve the full release notice
folder, and copy its text notices into `app/src/main/assets/licenses/` before
distribution. `GPL-3.0.txt`, `NATIVE-NOTICES.txt` and original project MIT attribution
are already included. See **License** below.

```sh
./tools/test-host.sh
./tools/test-binding-config.sh  # JDK + Go; validates JSON with the actual Go engine
./gradlew --no-daemon :app:lintRelease :app:assembleRelease
python3 tools/audit-apk.py app/build/outputs/apk/release/app-release-unsigned.apk \
  --sdk "$ANDROID_HOME" --report build/reports/apk-audit.json
```

Result on a successful build:
`app/build/outputs/apk/release/app-release-unsigned.apk`.

For smaller standalone downloads, opt into normal Gradle ABI splits:

```sh
./gradlew --no-daemon -PpsportalAbiSplits=true :app:assembleRelease :app:lintRelease
python3 tools/audit-apk.py app/build/outputs/apk/release/app-arm64-v8a-release-unsigned.apk \
  --sdk "$ANDROID_HOME" --abis arm64-v8a --report build/reports/arm64-apk-audit.json
python3 tools/audit-apk.py app/build/outputs/apk/release/app-x86_64-release-unsigned.apk \
  --sdk "$ANDROID_HOME" --abis x86_64 --report build/reports/x86_64-apk-audit.json
```

Each per-ABI APK is a complete standalone app, not an install-together split
package. Choose arm64-v8a for compatible phones and x86_64 for compatible emulators.
Both contain the same Java code, resources, licenses and corresponding native
library as the universal build. Without the property, the default remains the
universal APK. Preserve a tested artifact before switching output modes.

Both debug and release signing configurations are explicitly null; these commands
must not create an Android debug keystore. Unsigned APKs cannot be installed.
Signing requires a separately authorized existing key or explicit permission to
create one. No signing keys or passwords are included in this project. The isolated test
identity is stored outside the source tree and must never be added to CI or public
artifacts. Google accounts and Play Console configuration are not required.

Before any release, inspect ELF segment alignment (16 KiB), APK zip alignment,
ABI contents, AAR dependency licenses and corresponding source. The Gradle wrapper
is from Gradle v8.13.0, with its JAR verified against the official wrapper SHA256
`81a82aaea5abcc8ff68b3dfcb58b3c3c429378efd98e7433460610fecd7ae45f`.
The distribution is checksum-pinned in `gradle-wrapper.properties`.

## Optional unsigned CI

`../ci/android-unsigned.yml.example` is an inactive, manually activated GitHub
Actions template for a standard public-repository `ubuntu-24.04` runner. Review
and copy it to `.github/workflows/android-unsigned.yml` to enable it. It builds
the real AAR, runs JVM/configuration tests, assembles/lints/audits the unsigned APK,
and uploads the APK together with exact vendored corresponding source, licenses,
checksums and diagnostics. Artifacts are retained for one day. It has read-only
repository permissions and never creates signing credentials.

The helper `tools/ci-unsigned.sh` uses the runner's installed licensed SDK/NDK.
Pull requests install missing exact packages under the runner's existing accepted
SDK license; manual runs expose an install toggle. In either case `sdkmanager`
receives no license-acceptance input. A missing or changed agreement therefore
fails closed instead of being auto-accepted.
The template has also been activated in the public development PR; successful
run links are recorded in [VALIDATION.md](VALIDATION.md). CI does not make an
unsigned APK installable or replace device tests.

## Tests and device release gates

`tools/test-host.sh` uses `javac` and the installed JVM. A JRE-only host can set
`ECJ_JAR` to an approved Eclipse compiler JAR; the script never downloads tools.
The 90 JVM assertions cover config validation/JSON escaping, duplicate Start,
Stop before/during Start, stale status, multiple Stop callers, restart sequencing,
error redaction and failed teardown. Python structural checks cover manifest,
resources, direct JNI imports, unsigned builds, the task-removal cleanup guard
and no boot/VPN/subprocess paths.
The fake Java engine is confined to tests and is never bundled in the app.

Required device matrix:

- Android 8+ base flow; Android 13 notification permission grant/deny; Android 14+
  connected-device FGS restrictions; Android 16 and Android 17 with current target
- Physical arm64 phone with real bundled Mihomo AAR; 16 KiB page-size runtime
- Open UI, rotate, background, return, double Start, Start then immediate Stop,
  repeated Stop, notification Stop, Recents removal, process kill, clean restart
- Invalid/unassigned address and occupied port; Wi-Fi disconnect/roam/address
  change; notification/channel disable and future local-network revocation
- No packets before Start; only allowlisted Portal admitted; LAN requests do not
  wake remote adapters; one cold wake on concurrent requests; idle stop; next wake
- Fixed-node failure remains fail-closed; no private-network upstream bypass
- Screen-off/Doze/OEM battery tests and real Portal login/HTTPS behavior
- Confirm no UDP/game-streaming parity claim; no credentials in logs, saved state,
  backups, notification contents or screenshots

## License

This Android host and the combined embedded-Mihomo app are **GPL-3.0-only**; see
`LICENSE` and `../THIRD_PARTY_NOTICES.md`. The original repository's MIT attribution
is preserved separately. A binary release must include required dependency
licenses and provide corresponding source/build instructions. Google Play and
other store compatibility has not been established. Nothing is uploaded or
published by these scripts.

## Current simple-home parity update (PR4 baseline 49a8467)

This update uses the current Mac/iOS simple-home layout as its reference: Chinese
by default, dark by default, language choice in the header, grouped network,
subscription, live status and device setup cards, with manual configuration under
Advanced. Language/theme switches update the existing views without recreating
the Activity or restarting the native listener.

- **Prepare & start** selects an observed physical Wi-Fi/Ethernet private IPv4 and
  its actual /24–/30 prefix, builds up to 253 explicit client addresses, and keeps
  the chosen port (10081 initially) if free. A conflict selects a free alternative.
  Multiple usable addresses require the user to choose. VPN/cellular/unknown
  interfaces are excluded from automatic setup; manual explicit configuration
  remains available. The app never guesses hotspot addresses or changes networking.
- Preparation fetches only the server's subscription accounting headers. It does
  not claim the proxy nodes have been verified. The existing adapter engine loads
  nodes on demand, or when the user explicitly chooses **Load & test nodes**.
- Accounting is a non-live snapshot, uses KiB/MiB/GiB, keeps missing/invalid fields
  unknown, and caps remaining allowance at zero when over quota. The subscription
  is masked with an explicit `PasswordTransformationMethod` after `setSingleLine`,
  excluded from saved state/autofill, and cleared on Start or leaving the Activity.
- The current runtime status binding distinguishes preparing, listening, waking,
  forwarding and error. Active devices use the backend's distinct connected source
  IP count; they are never inferred from connection counts or all Wi-Fi devices.
- Advanced live controls load/test nodes, show real nullable measured delays and
  current selection, fix a selected node without silent fallback, and enable
  lowest-latency selection with an explicit improvement threshold. Existing auto
  (HK→JP→others), prefer and fixed modes remain. These are adapter capabilities,
  not desktop full-profile rules or control over another Clash application.
- Node probes run on a separate process-owned lane, allowing native Stop to cancel
  in-flight work. A restart waits for both native teardown and the old probe to
  retire, so stale UI actions cannot affect a new session.

The established foreground-service, notification Stop, task-removal cleanup,
notification/network revocation checks and unsigned build defaults are preserved.
New Java/resource compile checks and host assertions are source-level evidence;
this UI update still needs an actual APK build and device visual/lifecycle checks.
See `VALIDATION.md` for the exact local evidence and boundaries.

### Dummy-only UI regression on a test device

`app/src/androidTest/.../SimpleHomeInstrumentation.java` checks the actual password
transformation (not just input flags), secure window/autofill flags, and unchanged
subscription/session during hot language/theme changes. It uses only an invalid
example URL and never taps Start. With separately authorized signing and test
APKs installed on an isolated emulator/device, run:

```sh
adb shell am instrument -w org.psportal.host.test/org.psportal.host.SimpleHomeInstrumentation
```

No new signing key is needed or generated by this source check. The test requires
an idle app with no running proxy; it is not a replacement for transport, Doze,
notification or physical-device acceptance.
