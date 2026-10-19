# iOS development host with experimental timed background sharing

Mobile uses subscription-link import and its own embedded engine. Default sharing remains foreground-only. An opt-in iOS 26+ **timed background experiment** requests a real continued-processing task for 15/30/60 minutes. Simulator and older SDK/system builds cannot grant it. This is not unlimited keepalive, and physical-device LAN/background/lock behavior remains unverified. See [mobile requirements and API feasibility](MOBILE-REQUIREMENTS.md).

Latest local validation (2026-10-20): Xcode 27 arm64 Simulator, **38 XCTest total: 37 passed, one hardware-only Data Protection skip**; eight source guardrails passed. Five added lifecycle tests use an injected scheduler and prove orchestration only. Historical validation below describes earlier revisions.

This SwiftUI app embeds the real Go/Mihomo engine in `../engine`, through
`../mobile`. [CI run 39110679850](https://github.com/LONG10222/psportal-on-demand/actions/runs/39110679850)
compiled and linked actual arm64 Simulator and unsigned iPhoneOS apps with
Xcode 16.4. Simulator XCTest completed **13 passed, one explicit hardware-only
Data Protection skip, zero failures**. Three tests exercise real generated-
framework HTTP/CONNECT direct fixtures, client/destination denial and Stop/
restart socket behavior; the others cover storage/configuration and mocked
UI lifecycle. The Release simulator app separately launched and was captured
in a rendered, stopped-state screenshot.

No physical iPhone, real Portal session, subscription/encrypted-node routing on
iOS, signing, App Store acceptance or full platform parity is claimed. The
unsigned iPhoneOS app is **not installable as supplied**. Simulator cannot prove
local-network privacy permissions or hardware Data Protection. See
`VALIDATION.md` for exact source provenance, hashes and remaining release gates.

The subsequent bounded resource audit found missing required-reason privacy
metadata in that immutable development package. This source revision adds the
file-metadata/timer manifest and exact bundle/import checks; its Apple CI result
must be recorded before treating the correction as built. See `PRIVACY-AUDIT.md`.

## 2026-10-19 mobile sharing update

The app now has Share, Nodes and Devices tabs with immediate Chinese/English switching. Share highlights listener state, actual device/connection counts, subscription accounting and manual Wi-Fi proxy instructions. The default port remains 10081 unless unavailable. Wi-Fi/cellular uplink detection does not pretend to prove that Personal Hotspot is enabled: an actual private bridge and explicit confirmation are still required. A quick-start interface/address/mask change stops the listener.

Nodes controls only our embedded adapter pool: Load nodes explicitly downloads and tests the subscription, latency tests show successful health-request round trips, and tapping a healthy node pins new connections without fallback. Lowest-latency mode sorts healthy adapters by measured delay, retaining fallback among healthy nodes and retesting on the existing health interval (default five minutes). Failed probes never become zero-latency winners or change the selection policy. Existing connections retain their adapters. Automatic maintenance does not wake an idle pool. Policies stay in process memory across idle teardown and reset when sharing stops. Complete Clash groups/rules and other applications' controllers are not imported.

Devices lists actual allowlisted source IPs, active sockets, accepted connection totals and last activity. It does not scan the LAN or collect destination browsing history. Recent records expire after five minutes and clear on Stop. Listener connections include direct LAN requests and are distinct from outbound pool leases; neither alone proves Internet success. Request-error and denied-client counters aid diagnosis.

The actual simulator XCFramework was rebuilt and linked locally. XCTest: **21 total, 20 passed, one hardware-only Data Protection skip**; this includes actual bridge telemetry and command ABI, real HTTP/CONNECT, denied clients, Stop/restart and UI model checks. Shared Go engine/mobile tests passed under the race detector. Manual UI inspection verified all three tabs and hot language switching in iOS 27.0. No real subscription, encrypted public-node route, game console, physical hotspot or background-serving acceptance is claimed by these fixtures. The prior source a18d25d completed all six GitHub workflows; this update requires its own CI.

## Honest execution model

- The user taps **Start** to bind one configured RFC1918 LAN IPv4 address. There
  is no start on launch, restoration, return to foreground, or push notification.
- Only allowlisted private IPv4 clients can use the HTTP/HTTPS-CONNECT listener.
  The first external request loads the HTTPS subscription and real embedded
  Mihomo outbound adapters. The core's idle timer releases the outbound pool.
- Without a real unexpired continued-processing grant, background and lock notifications request **Stop**. A grant permits only the finite experiment; system expiry/cancellation, session deadline and network changes still stop sharing. The scheduler uses immediate-failure submission, unique identifiers and a five-second grant timeout; no queued restart or renewal.
- A serialized engine queue and generation checks make repeated Start taps,
  Stop during Start, and stale status callbacks safe. The UI does not report
  stopped until the native Stop returns. UIKit may still suspend or terminate
  the process; hard timing and lock/background behavior need device testing.
- A finite UIKit background assertion is requested **only while closing**
  connections. It ends on completion or expiration, is never renewed, and is
  not a continuing-service mechanism. The only `UIBackgroundModes` entry is `processing`, with the app-specific continued-task identifier prefix. There are no Network Extension targets, VPN profiles, background audio/location or automatic renewal loops.
- Optional keep-awake is off by default. It applies only to the active app while
  starting/listening, and restores the previous idle-timer value on Stop,
  startup failure, backgrounding, or temporary inactivity. It consumes battery
  and cannot make the app run in the background.
- This is an HTTP/CONNECT proxy, **not a UDP/game-streaming relay**. Actual
  PlayStation Portal behavior must be tested; a listener or simulator build is
  not evidence that a complete Remote Play session works.

Apple's [TN3120](https://developer.apple.com/documentation/technotes/tn3120-expected-use-cases-for-network-extension-packet-tunnel-providers)
identifies proxy-server hosting as an unsupported Packet Tunnel use. This app
does not try to work around that restriction.

## Configuration and privacy

1. Connect the host device and Portal to the same reachable, trusted Wi-Fi LAN.
2. In iOS Settings, find this device's current Wi-Fi IPv4 address. Enter it in
   the app with a port such as `10081` and the Portal's reserved IPv4 address.
3. Enter the HTTPS subscription URL in the secure field and select auto,
   preferred-with-fallback, or fixed-without-fallback mode. Preferred/fixed mode
   requires the exact node name.
4. Tap Start and allow local-network access if iOS requests it. In the Portal's
   manual HTTP proxy settings, use this host's address and port.
5. Leave the app open. Stop before leaving it, and restore the Portal's proxy
   setting when finished. A changed Wi-Fi address requires stopping and editing.

There is deliberately no automatic LAN scanning or copied clipboard access. The
`NSLocalNetworkUsageDescription` explains direct LAN communication. Denied local
network access, client isolation, unreachable interfaces, and address changes
need device-specific diagnosis. This app does not change system proxy, DNS,
firewall, network permissions, or router settings. An IP allowlist is not
cryptographic authentication; never port-forward this listener to the internet.

**The subscription URL is never saved.** It is excluded from `ProxySettings`'
Codable keys, is supplied to the native engine only in memory, and must be
re-entered after relaunch. Start does not save settings. Save writes only the
other settings, using atomic complete-file-protection writes in the private
Application Support directory, with `0700` directory/`0600` file permissions.
Backup exclusion is set on the directory before writing and on the file after
every save. Do not add the subscription to UserDefaults, state restoration,
analytics, logs, document exports, crash reports, or backupable caches.

The native adapter pool retains credentials only in process memory and disables
Mihomo logging. The UI does not expose raw native errors or raw status JSON. Node names and
client IPs are shown only in the corresponding local panels, marked privacy-sensitive,
and are not saved to logs or settings. It shows a secure URL field and an opaque cover while inactive. These
reduce accidental exposure but are not screenshot/recording protection, memory
zeroization, or a guarantee about operating-system crash diagnostics. Forget
removes saved settings/runtime files and clears the fields, only after stopping.

## Build prerequisites on a Mac

Use an existing authorized macOS/Xcode environment with its license already
accepted. No script installs Xcode, accepts agreements, creates signing
credentials, uploads artifacts, or requests a signing team.

- Full Xcode with iOS and iOS Simulator SDKs, selected by the owner
- Go satisfying `../go.mod` (currently Go 1.26), with dependency network access
- Python 3 for dependency-license collection
- [XcodeGen](https://github.com/yonaskolb/XcodeGen) 2.43 or newer from its official
  repository or documented Homebrew formula (`brew install xcodegen`)

XcodeGen is an explicit project-generation dependency. `project.yml` is the
source of truth; no generated `.xcodeproj` is supplied or claimed validated.
The only native engine input is the real `PSPortalEngine.xcframework`; there is
no mock or fallback transport in the application target.

### Public GitHub Apple build/test CI

`../ci/ios-simulator.yml.example` is the maintained template for the reviewed
`.github/workflows/ios-simulator.yml` on the development PR. Its full-app validation uses one standard
`macos-15` public-repository job, using the runner's existing Xcode 16.4, pinned
Go 1.27.2, pinned gomobile, and official checksum-verified XcodeGen 2.46.0.
GitHub Actions themselves are pinned to full commit SHAs. The job refuses private
repositories, has no full-app matrix, caches nothing, and cancels superseded runs.

A separate compile-only matrix uses the runner's existing Xcode 26.3 to compile
unchanged `BackgroundSharingSession.swift` for iPhoneOS and Simulator, using
Swift 5 language mode and iOS 16 deployment settings. It requires compiler 6.2+,
SDK 26+ and defined `SystemBackgroundSharing.begin` / `finish` implementation
symbols, and retains source, toolchain and object-hash evidence for one day.
It does not build/link the full app, execute a background task or validate a
physical device. The Xcode 16.4 full-app/XCTest job remains unchanged. Availability
is checked against the [official ARM64 runner inventory](https://github.com/actions/runner-images/blob/main/images/macos/macos-15-arm64-Readme.md#xcode);
a missing SDK is a failure, never a silent older-SDK fallback or SDK download.

The job builds the runner's simulator architecture and iPhoneOS ARM64 by setting
`IOS_TARGET` on the shared mobile recipe, runs native Go fixture tests, generates
the Xcode project, builds a Release simulator app with `CODE_SIGNING_ALLOWED=NO`,
and runs XCTest on an installed iPhone runtime no newer than the SDK (at least
iOS 16). Real bridge tests bind controlled direct-route HTTP/CONNECT fixtures to
an existing RFC1918 interface; no loopback-destination bypass or interface alias
is introduced. The subscription stays unused. An unsigned iPhoneOS build/link
gate follows; no tests execute on physical hardware. Finally, the Release
simulator app is launched separately and a screenshot is captured. The Data
Protection hardware test explicitly skips there; other test failures fail CI.
No signing account, key, provisioning profile, physical device, or new Xcode
license is requested. A failure is a blocker to diagnose, not a pass.

Only after all build and test gates pass does the job create separate simulator
and unsigned-device ZIPs with the `.app`, GPL/dependency notices, corresponding
source+vendor archive, build/source-commit information, and content/ZIP SHA-256
manifests. The unsigned device app is **not installable as supplied**. It also retains build
up to 20 MiB of log tails and a complete `.xcresult` only when it is at most
50 MiB plus a screenshot of at most 5 MiB; the report records omissions.
The combined app/source ZIPs are capped at 200 MiB. Artifacts have one-day retention to limit storage; GitHub's
normal account storage limits still apply. This is not an `.ipa` and
cannot be installed on a physical iPhone. A successful simulator run will not
establish real Portal, Wi-Fi, lock/background, power, signing, or distribution
readiness.

Official references checked for the template:
[standard public runners](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job),
[macOS 15 runner/Xcode image](https://github.com/actions/runner-images/blob/main/images/macos/macos-15-arm64-Readme.md),
[Go downloads](https://go.dev/dl/),
[XcodeGen 2.46.0 assets and checksums](https://github.com/yonaskolb/XcodeGen/releases/expanded_assets/2.46.0).

From `native/ios`:

```sh
./scripts/build-engine.sh
./scripts/generate-project.sh
xcodebuild -project PSPortalHost.xcodeproj -scheme PSPortalHost \
  -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build CODE_SIGNING_ALLOWED=NO build
```

The build helper installs the exact `golang.org/x/mobile` version recorded in
`native/go.mod` into task-local `.tools/bin`, initializes gomobile, and invokes
`native/scripts/mobile.sh ios`. The shared recipe includes adapter build tags
`no_easytier,no_zerotier,no_tailscale`, device/simulator slices by default, deployment target
iOS 16, and dependency notices. It statically links the resulting framework;
the app never downloads or launches executable code. Optional protocols removed
by those tags are unavailable, rather than replaced by fake implementations.

The generated ObjC contract was inspected on Linux using real `gobind` output:

```objc
BOOL MobileStart(NSString *configJSON, NSError **error);
NSString *MobileStatus(void);
void MobileStop(void);
```

`PSPortalEngineBridge` calls these exact functions through the framework umbrella
header and provides explicit Swift names. This verifies the binding **source
contract only**, not Apple compilation or linking. Go's
[gomobile documentation](https://pkg.go.dev/golang.org/x/mobile/cmd/gomobile)
requires macOS and Xcode for Apple framework builds.

For physical-device installation, an owner must select an existing signing team
and an appropriate bundle ID in Xcode, explicitly enable code signing, and use
their own authorized provisioning. Signing is disabled in the checked-in spec.
No signing, provisioning, device registration, export compliance declaration,
new Apple agreement, or App Store submission is performed by this project.

## Checks and remaining release gates

Linux-only structural checks:

```sh
python3 scripts/check-source.py
bash -n scripts/build-engine.sh scripts/generate-project.sh scripts/verify-build-inputs.sh
```

These check metadata, privacy/lifecycle guardrails and the binding source
contract. They are not a Swift compiler, SDK, simulator, or transport test.
XCTest source is included for settings validation, non-persistence of the URL,
file protection/backup flags, duplicate Start, Stop-during-Start, background Stop,
no automatic restart, and idle-timer restoration. All 14 methods ran in the linked CI above: 13 passed and the physical Data
Protection method skipped. Three methods use the actual framework and sockets.
After producing the real framework/project on a Mac, choose an available
simulator and run:

```sh
xcodebuild -project PSPortalHost.xcodeproj -scheme PSPortalHost \
  -destination 'platform=iOS Simulator,id=YOUR_AVAILABLE_SIMULATOR_ID' \
  -derivedDataPath build CODE_SIGNING_ALLOWED=NO test
```

Before calling this a usable release, establish all of the following:

- XcodeGen generation, Swift/ObjC compilation, all native adapter architectures,
  static framework linkage, unit tests, and resource bundling
- Signed installation and UI inspection on actual supported iPhone/iPad devices
- Real subscription and encrypted node routing, HTTP and CONNECT, exact fixed
  node behavior, allowed/denied clients, direct LAN destinations, pool idle/wake
- Real Portal end-to-end behavior, Wi-Fi isolation, address changes and reconnects
- Local-network permission grant/denial, lock/unlock, Home/app-switcher, calls,
  control-center interruptions, repeated Start/Stop and Stop during subscription
  download; confirm the listener closes and no automatic restart occurs
- Idle-timer restoration, power/heat/memory impact, data-protection and backup
  behavior, app-switcher privacy cover, and sanitized crash/log output
- Complete third-party notices/corresponding source and independent review of
  GPL/store terms, required-reason APIs/privacy manifests, privacy disclosures,
  app icon, signing, and all distribution requirements

## License

This native app embeds Mihomo v1.19.32 and is **GPL-3.0-only**, not MIT-only. The
full GPL and original project's MIT notice are bundled with third-party notices.
The shared mobile build collects dependency texts into
`PSPortalHost/Resources/Licenses/ENGINE-NOTICES.txt`; build verification refuses a
missing real framework or required notices. License texts appear in the app's
Licenses screen. Preserve matching source and build instructions with any
distribution; see `../THIRD_PARTY_NOTICES.md` and `../scripts/source_release.py`.

No GPL/Apple store-terms compatibility determination is made. This is a
development build pending the remaining hardware, privacy, signing and
distribution gates above.
