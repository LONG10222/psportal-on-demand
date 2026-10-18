# iOS foreground-only development host

This SwiftUI app embeds the real Go/Mihomo engine in `../engine`, through
`../mobile`. A real arm64 Simulator app compiled, linked and launched under
Xcode 16.4; [CI run 39108633642](https://github.com/LONG10222/psportal-on-demand/actions/runs/39108633642)
completed 10 XCTest methods with no failures and one explicit hardware-only
Data Protection skip. Those first tests covered storage/configuration and mocked
lifecycle orchestration, **not framework HTTP/CONNECT transport**.

The next CI gate adds real framework socket fixtures, separate unsigned iPhoneOS
ARM64 compilation, and a Release simulator launch/screenshot. These additions
are pending their own successful run; see `VALIDATION.md`. No physical iPhone,
Portal session, signing, App Store acceptance or full platform parity is claimed.

## Honest execution model

- The user taps **Start** to bind one configured RFC1918 LAN IPv4 address. There
  is no start on launch, restoration, return to foreground, or push notification.
- Only allowlisted private IPv4 clients can use the HTTP/HTTPS-CONNECT listener.
  The first external request loads the HTTPS subscription and real embedded
  Mihomo outbound adapters. The core's idle timer releases the outbound pool.
- Keep the app foregrounded and the device unlocked. Scene backgrounding,
  UIKit background notification, or protected-data lock notification requests
  **Stop**, which cancels loading and closes the listener and owned connections.
- A serialized engine queue and generation checks make repeated Start taps,
  Stop during Start, and stale status callbacks safe. The UI does not report
  stopped until the native Stop returns. UIKit may still suspend or terminate
  the process; hard timing and lock/background behavior need device testing.
- A finite UIKit background assertion is requested **only while closing**
  connections. It ends on completion or expiration, is never renewed, and is
  not a background proxy service. There are no `UIBackgroundModes`, Network
  Extension targets, VPN profiles, Packet Tunnel entitlements, background audio,
  background fetch, or background keep-alive loops.
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
Mihomo logging. The UI does not expose raw native errors, node names, or status
JSON. It shows a secure URL field and an opaque cover while inactive. These
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
`.github/workflows/ios-simulator.yml` on the development PR. It defines one standard
`macos-15` public-repository job, using the runner's existing Xcode 16.4, pinned
Go 1.27.2, pinned gomobile, and official checksum-verified XcodeGen 2.46.0.
GitHub Actions themselves are pinned to full commit SHAs. The job refuses private
repositories, has no matrix, caches nothing, and cancels superseded runs.

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
no automatic restart, and idle-timer restoration. The first 11 methods ran in the linked CI above. Three new real-framework
transport methods await their own CI result.
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
