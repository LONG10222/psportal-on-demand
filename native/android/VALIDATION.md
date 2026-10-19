# Android validation record

## 2026-10-19 startup-callback and notice correction

The current correction preserves Android v4 (`0.4.0-dev`, code 4), its phone
network policy and unsigned distribution. It separates accepted session identity
from Android's newer start IDs for ignored duplicate commands. Completion is
checked when dispatched, so Stop/restart and failed-start retry suppress stale
callbacks without suppressing the still-current phone-VPN launch.

- 243 JVM assertions: 220 host/config/lifecycle, 8 background, 15 phone-state
- Deterministic real `SessionController` queue regressions cover duplicate Start,
  failure cleanup, delayed completion after Stop/restart/retry and Stop during
  native startup; source guards verify `ProxyService` uses the newest start ID
- These are JVM/controller and source-wiring checks, not Android service-delivery
  instrumentation or a physical-phone VPN test
- 17 compiled-manifest/notice tests, including missing/stale notice rejection;
  the real APK audit compares its short native notice to this exact source
- 17 source/license/upstream-patch tests and complete patch provenance pass
- Go/Android SDK are unavailable in this local verification environment; no
  dependency-fetch retry was made. Full core/race, Java-to-core binding, actual
  APK/lint/alignment and source gates run in the authorized exact-revision CI

The earlier v4 results below describe the base implementation. Do not treat
them as fresh execution of those stages for this correction. Signing and all
physical-device limits remain unchanged.


## Current v4 full-core / optional VPN source

Version 0.4.0-dev / code 4 has these local source-level results, separate from
all historical builds below:

- 229 JVM assertions and 36 Java-to-real-Android-core configuration round trips
- 32 Android core tests repeated three times with the race detector
- Real Mihomo TCP rule/global/direct fixtures and actual SOCKS5 UDP_ASSOCIATE wire
  capture; unsupported UDP and explicit UDP opt-outs never silently use DIRECT
- Same-source/different-destination UDP isolation; bounded flow and DNS ownership;
  protected sockets; cancellation; dual-stack DNS-to-domain-rule mapping
- 150 generations ×256 queued UDP packets during Stop/restart, plus deterministic
  blocked TCP/UDP metadata/rule work and sender saturation/close regressions
- Patched upstream log and tunnel regressions; focused standard-library queue
  concurrency regression. Full upstream queue package needs dependency sources
  unavailable locally and is included in the normal CI gate
- 17 license/source/patch tests, 10 compiled-manifest parser regressions, complete
  upstream source/patch verification and fresh real Java/Objective-C bindings
- Android arm64 source compilation with actual gVisor selected, not its stub;
  existing adapter/CLI race tests and eight unchanged iOS source guards pass

These are local sockets and synthetic data, not actual Android TUN/device tests.
No public subscription, host VPN or system network setting was used. Native SDK,
Java/resource, APK, alignment, complete vendored source and artifact provenance
are checked by the exact-revision Android CI run; inspect that run's result and
packaged audit rather than inheriting a prior revision's green checks.

Local vendored archive generation was blocked by uncached dependency sources
under an offline policy; no partial archive success is claimed. CI uses its
normal explicitly authorized dependency build flow. The original development
signing key is absent; no substitute identity is made. Same-key upgrade and
signed installation cannot be verified here. Physical Android, screen-off/Doze,
carrier/hotspot, Portal and game acceptance remain unverified.

## Previous v3 baseline

PR #5 exact head `a0dcf23336f91e4e9b4e6bd163731a90d1ccd05f` passed Android
unsigned build/audit in run `39187047377`. Its APK and complete source were checked
for artifact provenance. It has no optional phone VPN and uses the older adapter
entrypoint. Its CI success must not be reused as v4 validation.

**Historical evidence follows.** Build 1 hashes, signed candidates and emulator
runs below belong to the earlier implementation, not current v4. No evidence
here establishes physical-device or Portal release signoff.

## Historical baseline: passed

- 90 JVM configuration/lifecycle assertions with the real `HostConfig` and
  `SessionController`; fake native engine is test-only
- Tests compiled/run with Eclipse compiler 3.41.0 and Microsoft OpenJDK
  21.0.12.1; Android-generated JSON accepted by the real Go `engine.ParseConfig`
- Real shared Go/Mihomo engine cross-compiled into `psportal-engine.aar`, containing
  arm64-v8a and x86_64 JNI libraries and the actual `Mobile` Java bindings
- Full native dependency license notices packaged in application assets
- `:app:assembleRelease :app:lintRelease`: successful, including real Android
  Java/resource compilation, DEX conversion and APK packaging
- Release lint: **0 errors, 1 warning**. The remaining warning only reports a newer
  Gradle version; the checksum-pinned, AGP-compatible Gradle 8.13 is intentional
- Final APK audit: correct package/SDK/ABIs, required license assets, native ELF
  PT_LOAD alignments of 16,384 bytes and `zipalign -c -P 16 -v 4` all pass
- Manifest/XML/resource guardrails, direct JNI linkage, no VPN/boot/subprocess
  paths, and both build variants' explicitly null signing configurations
- Ordinary Gradle/CI builds generate no signing identity. The unsigned APK audit
  requires the specific expected `Missing META-INF/MANIFEST.MF` verifier result
- Separately authorized project-only development signing: APK signature schemes
  v2/v3 verify; 16 KiB ZIP alignment still passes; every original unsigned ZIP
  payload entry is byte-identical in the signed APK

## Artifact provenance

Historical build 1 unsigned APK: `app/build/outputs/apk/release/app-release-unsigned.apk`

- Size: 75,204,521 bytes
- SHA256: `7a66562bd24716f823e139155bf2d12278f563ccd7074dfee4692071c03eb35f`
- Application ID `org.psportal.host`, version `0.1.0-dev` / code 1
- min SDK 26, target SDK 36; arm64-v8a and x86_64

Development-signed test APK: `app/build/outputs/apk/release/psportal-android-development.apk`

- Size: 75,229,056 bytes
- SHA256: `4327d921988cbca20b520ff32ba8f57085e327567ca7ab17420faad0d53f3c62`
- Public signing certificate SHA256:
  `7239e963e690e62a50bbd14939c15b749b51e14b7e3454795ef379ec12c5ec60`
- The dedicated private key and password remain outside the source tree. They
  are not included in source, CI, artifacts or corresponding-source archives
- This is a test identity, not a store/release identity

### Smaller standalone ABI downloads

The opt-in `-PpsportalAbiSplits=true` build also passed release assembly, lint and
all 90 JVM/structural checks. It emits complete standalone APKs, each containing
only its selected native ABI. Both were signed with the same authorized project
test key and passed signature v2/v3 verification and 16 KiB ZIP/ELF alignment.
Every non-signature payload entry, including DEX, manifest, resources, licenses
and the selected native library, is byte-identical to the tested universal APK.

- arm64-v8a APK: 35,976,308 bytes; SHA256
  `8f1c22953c4d0315bb02d9a111c803074f8b7c29629240caf5ac4a247be67762`
- arm64-v8a download ZIP: 12,256,831 bytes; SHA256
  `6bcf07f9bd5ff3003d96c701bcfbae284fbe2ccaad0ae738a96dc0988cb0d9ac`
- x86_64 APK: 39,466,097 bytes; SHA256
  `224d5181a9d3717ad906f2fbb312e6bea435f7d7f485aeb3ff8f6dbeef86a489`
- x86_64 download ZIP: 13,400,879 bytes; SHA256
  `ecc793f732f46b04da44b609cdf5d4b2eda4721a3cbbefc6faf937f8c4baad1f`

These packaging checks do not establish arm64 device execution. The runtime
sections below identify the tested universal candidate explicitly; direct
x86_64 standalone installation/testing is separate pending evidence. The build
defaults and ordinary CI remain universal and unsigned.

Real AAR: `app/libs/psportal-engine.aar`

- SHA256: `5955295615e6e8646c36f035d975783332965cdc6f47fb43693d933c6ef69286`
- Native source manifest `../dist/ENGINE-SOURCE-MANIFEST.json` SHA256:
  `bb416f76b141266769a294e49816f4dc7580c17f111cd966a6ca46fbd4b93080`
- Manifest remained unchanged through the successful AAR build
- Go 1.27.2; Mihomo v1.19.32; x/mobile
  `v0.0.0-20261011034528-197770444867`
- Mobile feature tags: `no_easytier,no_zerotier,no_tailscale`

The dependency inventory includes a warning for `github.com/RyuaNerin/testingutil`,
a graph-only dependency used by dependency tests. It is absent from linked app
imports and vendored corresponding-source files; no license has been invented
for it. Preserve the inventory warning alongside the bundled runtime licenses.

Local reports (generated, not committed): `build/task-removal-build.log`,
`build/reports/apk-audit.json`, `build/reports/development-apk.json`,
`build/reports/signing-payload-audit.json`, and
`app/build/reports/lint-results-release.{html,xml,txt}`.

## Toolchain and agreement

The Android SDK agreement was explicitly approved and accepted on 2026-10-18:
https://developer.android.com/studio/terms

Official task-local tools were installed in the isolated development environment:

- Android command-line tools 22.0 (`15859902`), platform API 36 revision 2,
  Build Tools 35.0.0, NDK r30 / `30.0.16248370`
- Android Gradle plugin 8.13.2 and Gradle 8.13
- Microsoft OpenJDK 21.0.12.1+1, Java source/target level 17
- Command-line tools ZIP SHA256:
  `4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583`
- Microsoft JDK archive SHA256:
  `4c0c7f5cd0b6bb81109d01f13a1678ee0f73f36c1020080d97c4de3ce3cac207`
- Official Gradle wrapper JAR and distribution SHA256 verified and pinned

Only the disclosed `android-sdk-license` was accepted through SDK Manager.
No blanket `sdkmanager --licenses`, fabricated acceptance hash, paid service or
installation on the user's computer was used. Future builds still require their
own properly licensed SDK; the repository does not auto-accept agreements.

## Actual Android 8 / API 26 runtime

AOSP `system-images;android-26;default;x86_64`, revision 1, ran under official
Emulator 37.2.12 with software CPU emulation. Framework boot completion was real;
no boot properties were forced. The guest uses 4 KiB pages. The final signed APK
above was installed successfully and its Activity launched successfully.

Verified on that final APK:

- Visible Activity configuration starts the actual embedded JNI listener and
  foreground service; configuration is not injected through a raw native API
- Phone/listener: existing `wlan0` address `192.168.232.2:10081`
- Synthetic client: existing `radio0` address `192.168.200.2`, explicitly bound
  by the guest socket client; normal `HostConfig` requires the two IPs to differ
- Kernel socket evidence confirms the allowlisted source reaching the listener
- HTTP absolute-form requests return the controlled LAN HTTP fixture body
- CONNECT returns `200 Connection Established` and the controlled TCP echo body
- A client bound to the non-allowlisted Wi-Fi source receives no proxy response;
  the controlled upstream fixture receives no additional request
- Direct-LAN tests leave the UI reporting `Core: stopped`, with zero active
  external connections: no subscription or remote adapter is needed for them
- Home leaves the foreground service and listener active
- Removing the Activity from Recents removes both the listener and the service

These are synthetic, same-emulator peer tests. Both private addresses existed
before testing; no addresses or network settings were changed. Upstream fixtures
ran on the isolated task host, reached through emulator alias `10.0.2.2`.
The HTTPS subscription field contained only `https://example.com/unused-fixture.yaml`.
This does not establish remote-phone/Portal LAN reachability or subscription
compatibility.

An immediately preceding APK also verified the visible notification **Stop**
action removing the listener and service, and the UI rejecting equal phone and
Portal addresses. Its only subsequent application-code change was the Recents
cleanup fix below. The final APK re-ran the start/protocol/Home/Recents sequence.

### Runtime-found regression, fixed and re-tested

Before the fix, Recents removal closed sockets and the notification but left an
idle ServiceRecord. Android 8's task-removal path assigns another internal start
ID without calling the service's `onStartCommand`; consequently the previously
recorded ID is too old for `stopSelfResult`. The task-removal completion now calls
`stopSelf()` after native teardown, while first checking the captured start ID
against the latest delivered command so an older completion cannot stop a newer
run. Normal Stop paths retain `stopSelfResult`.

See the [official Android 8 ActiveServices source](https://android.googlesource.com/platform/frameworks/base/+/android-8.0.0_r1/services/core/java/com/android/server/am/ActiveServices.java).
A structural regression guard and actual emulator re-test cover this fix.
Generated evidence: `build/emulator/api26/fixed-lifecycle-result.json`,
`protocol-results.json`, `allowlisted-peer-netstat.txt`, `allowlisted-http.txt`,
`allowlisted-connect.txt`, `fixed-running-status.json`, and
`fixed-recents-stop-result.txt` in the same directory.

## Actual Android 16 / API 36 ATD runtime

The final signed APK was installed successfully on official AOSP API 36 ATD
x86_64 revision 1 under Emulator 37.2.12. Real framework boot completed without
forcing boot properties. On this image the normal Activity verified:

- Notification permission denial leaves no service or listener
- Explicit permission grant through the platform UI permits startup
- Android 16 creates a foreground service with `connectedDevice` type `0x10`
- The actual embedded JNI listener binds the configured `10.0.2.16:10081`
- Activity **Stop** removes the service and listener

The ATD image intentionally omits SystemUI and other platform apps; it cannot
verify the real notification shade or Recents UI. See
[Android's ATD documentation](https://developer.android.com/studio/test/managed-devices).
Positive protocol tests were not established on ATD; the API 26 synthetic tests
above remain separately identified. A first standalone UI-automation command
exited 137, while a compressed retry succeeded and the app stayed alive. No cause
for that command's exit is asserted.

The bounded screen-off attempt stopped before any power key was sent: the guest's
Wi-Fi address `10.0.2.16` had disappeared, leaving existing `eth0` address
`10.0.2.15`. The Activity correctly rejected the now-unassigned configured address
and opened no service or listener. No network settings were changed. Screen-off
survival is therefore **not established**. ATD also reports
`mLightEnabled=false` and `mDeepEnabled=false`, so it cannot establish Doze
behavior. Platform Doze defaults were not modified.

Generated evidence: `build/reports/android-runtime.json` and
`build/emulator/api36-atd/{runtime-result.json,runtime-completion.log,notification-denied.txt,connected-device-fgs-confirmed.txt,app-stop-result.txt,restart-ui-diagnostic.txt,restart-network-diagnostic.txt,power-test-capabilities.txt}`.

## Full-system emulator and remaining gates

This development environment has no `/dev/kvm`; hardware-accelerated emulation
is unavailable. Full AOSP API 36 x86_64 revision 2 genuinely completed its first
boot, but its emulator exited with status 137 during APK installation. No app
execution was established by that attempt, and its exit cause is unproven. A
serialized retry is separate work and is not counted as a pass in this record.

Host-to-guest emulator console TCP redirection reset connections against both
the proxy and an independent netcat fixture. It was not used to claim a proxy
allowlist failure or successful remote-peer path. Screenshot capture was not
usable: the app intentionally uses `FLAG_SECURE`, and an emulator-side capture
showed software-rendering artifacts. No fabricated or cleaned-up UI image is
presented as test evidence.

Remaining gates include notification/channel revocation during a run, full-system
modern notification/Recents behavior, API 37 local-network permissions, physical
arm64 and 16 KiB execution, Wi-Fi loss during a run, screen-off/Doze/OEM behavior, external
subscription wake/idle and node selection on Android, and a real Portal session.
Shared-engine fixture/unit tests do not replace these device checks.

## Public unsigned CI

`../ci/android-unsigned.yml.example` remains a reusable inactive template; a copy
was explicitly activated in the public development PR using a standard Ubuntu
runner. Actual build, JVM/configuration tests, lint, APK audit and matching
source/license artifact upload all passed in these runs:

- [39107122283](https://github.com/LONG10222/psportal-on-demand/actions/runs/39107122283)
- [39107706917](https://github.com/LONG10222/psportal-on-demand/actions/runs/39107706917)
- [39108633524](https://github.com/LONG10222/psportal-on-demand/actions/runs/39108633524)

The runtime-found Recents fix also passed the full public CI pipeline in
[39109675657](https://github.com/LONG10222/psportal-on-demand/actions/runs/39109675657),
head `4ef16d63a16fa9783e26cef5b69c488f5be5d80a`. Its separate unsigned APK SHA256 is
`9bf6f8b78b5b0c6eab96c88330e4f84bb2a2ea6b8e7efcdd9eebd895e5306132`.
CI artifacts expire after one day and contain unsigned APKs. They are not an
installable or durable release.

## Current simple-home source validation, 2026-10-18

Based on PR4 `49a8467702e949bd517f9abc9da27c922cf73bdf`, preserving current Mac/iOS
files and existing native adapter/service behavior. Reference images inspected:
`evidence/simple-home-zh.png` and `evidence/ios-simple-home-zh.png`.

This run used the cloud Linux workspace, not a user computer or Android emulator.
The Java 21 runtime contains the compiler module but no `javac` launcher or Java
17 release metadata. ECJ 3.39.0 from Maven Central was used for the JVM suite.
Official Google Android SDK platform 36 r02 and Build Tools 35.0.0 were downloaded
to a task-local directory under the already approved SDK terms and verified
against Google's repository SHA-1 checksums. No SDK license acceptance files,
signing identities, system networking changes or fake native APIs were created.

- 168 JVM assertions pass, covering original config/session lifecycle plus bounded
  subnet allowlists, interface filtering, port conflict choice, missing accounting,
  overflow, quota/expiry formatting, real-state presentation, live node operations,
  cancellation, Stop during probes and restart isolation
- Python structure/XML/privacy guards pass, including explicit password
  transformation after single-line input configuration
- Android app and dummy-only instrumentation Java sources compile against actual
  API 36 classes and freshly generated current native/mobile Java bindings
- aapt2 compiles and links the actual resources and merged namespace manifest
- Java configuration output is accepted by the real current Go engine.ParseConfig
- The dummy-only instrumentation is added and source-compiled, but has NOT been
  executed on a device in this run
- Full Gradle release lint/APK/native AAR rebuild, visual Android validation,
  physical device/hotspot/Portal, notification behavior and Doze tests have NOT
  been run for this UI change; historical results above do not establish them

Source/resource check (requires installed licensed SDK and pinned current bindings):

```sh
ANDROID_JAR=/path/to/platforms/android-36/android.jar \
AAPT2=/path/to/build-tools/35.0.0/aapt2 \
MOBILE_JAVA=/path/to/current-gobind-output/java \
./tools/check-ui-compile.sh
ECJ_JAR=/path/to/ecj-3.39.0.jar ./tools/test-host.sh
```

The resource-link output is intentionally not an app artifact: it contains no
compiled native engine and must never be distributed as an installable build.
