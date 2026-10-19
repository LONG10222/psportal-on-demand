# PSPortal Android host

Android v4 (`0.4.0-dev`, code 4) embeds pinned Mihomo in one application through
`androidcore` / `androidmobile`. No external Clash, Python, root, shell subprocess
or downloaded executable is needed. The Chinese-first simple UI retains language,
theme and subscription-usage choices.

## Choose the session

- **LAN sharing**, on by default: HTTP/HTTPS CONNECT on a specific LAN address,
  restricted to explicitly allowed client IPs. Configure the other device's manual
  HTTP proxy using the displayed address and port. This input is TCP-only.
- **Proxy this phone's apps**, off by default: optional Android `VpnService` input
  with IPv4/IPv6 TCP and supported-node UDP. Android system consent is required;
  an existing VPN conflict is shown. VPN-only opens no LAN listener.
- Both inputs can run together; both off disables Start. Granting VPN consent
  alone does not start LAN sharing. The app's own sockets are excluded/protected.
- **Rule / global / direct** applies to the selected inputs. Choose before Start.
  Full subscription profiles retain supported policy groups; unsupported required
  features are rejected. Overridden host/DNS settings are visibly identified.
- **Continue in background** is independent. Home/lock/Recents continuation is
  best effort when enabled; disabling it stops when the UI is hidden (not on
  rotation). Stop, notification Stop, network loss and VPN revocation clean up
  the selected session. Turning phone VPN off can leave LAN sharing running.

Unsupported-node UDP is rejected without silent DIRECT fallback. ICMP/ping is
not forwarded. Private/loopback destinations are currently blocked for phone VPN,
even in DIRECT mode, so local-device apps may fail until phone VPN is turned off.
The LAN HTTP input retains approved private-network direct handling. See
[FULL-CORE.md](FULL-CORE.md) for exact configuration, DNS and protocol boundaries,
and [BACKGROUND.md](BACKGROUND.md) for Doze/manufacturer limitations.

Foreground notification permission is requested from the visible Activity. The
app refuses to serve without a visible notification. There is no boot receiver,
Android always-on/lockdown support, battery-exemption prompt or wake-lock promise.

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

## Platform and build

Application ID `org.psportal.host`; min SDK 26, compile/target SDK 36; AGP 8.13.2,
Gradle 8.13 and Java language level 17. LAN sessions use connectedDevice foreground
typing; consented VPN-only sessions use systemExempted. Services are non-exported,
and the VPN service is protected by BIND_VPN_SERVICE. No storage permission is used.

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

## Build unsigned without creating credentials

Use pinned Go 1.27.2, JDK 17+ (CI uses 21), SDK platform 36, Build Tools 35.0.0 and
NDK 30.0.16248370. SDK terms must already be accepted:
https://developer.android.com/studio/terms

Set JAVA_HOME, ANDROID_HOME and ANDROID_NDK_HOME. From `native/`:

```sh
./scripts/mobile.sh tools
./scripts/mobile.sh android
cd android
./tools/test-host.sh
./tools/test-binding-config.sh
./gradlew --no-daemon :app:assembleRelease :app:lintRelease
```

The Android-only binding is `org.psportal.engine.androidmobile.Androidmobile`.
The build includes actual gVisor (`with_gvisor`), arm64-v8a and x86_64 JNI libraries,
16 KiB page alignment and full dependency notices. iOS retains its existing
`mobile` binding. Missing AAR/notices fail the build; no fake engine is substituted.

`.github/workflows/android-unsigned.yml` runs the actual build and audits compiled
manifest, exact version, service permissions, ELF/ZIP alignment and unsigned
status. It packages matching complete source, local upstream patch, vendored
source and notices. Artifacts have one-day retention. The SDK installer receives
no license-acceptance input; changed/unaccepted terms fail closed.

The original project development signing key is unavailable. No replacement is
created. CI APKs remain unsigned; install-ready signing and same-key upgrade
compatibility are not established.

## Verification boundaries

See [VALIDATION.md](VALIDATION.md) for current versus historical evidence. Local
JVM, source, Go race, captured TCP/UDP and DNS fixtures do not establish Android
VPN consent UI, actual TUN traffic, screen-off endurance, hotspot/carrier/Portal
behavior, OEM battery handling or 16 KiB hardware runtime. These require a signed
build on real devices. Prior signed build-1 emulator evidence does not validate v4.

## License

The combined application is GPL-3.0-only. Preserve the complete corresponding
source and dependency notices with distributed binaries. The original project's
MIT attribution remains separate. No app-store compatibility is claimed.
