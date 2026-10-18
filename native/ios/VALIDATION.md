# iOS validation record

Updated 2026-10-18. Simulator success is not physical-device or Portal proof.

## Final complete build/test/package gate

[Run 39110679850](https://github.com/LONG10222/psportal-on-demand/actions/runs/39110679850)
completed **successfully** on PR head
`7a6837e0c9070a861f2718e71cb155454ce1ea24`, checked-out merge
`f5375adc87dd4808d5ae07bb2376ffecc697af2a`.

- Real device/simulator XCFramework, Release Simulator app, Debug XCTest bundle
  and unsigned Release iPhoneOS ARM64 app all compiled and linked
- All three real bridge/socket tests below passed again; full XCTest suite:
  **13 passed, 1 explicit physical Data Protection skip, 0 failures**
- Existing simulator explicitly booted after XCTest; Release app independently
  installed/launched, still alive after three seconds, screenshot captured
- Screenshot inspected: rendered foreground-only UI, stopped state, empty
  configuration. This is limited launch/layout evidence, not complete UI QA
- Full source/vendor, GPL/dependency notices, app platform and content hashes
  verified before packaging. No account, signing key or profile was used

GitHub combined artifact 12130836609 SHA-256:
`571df1cdc78b9a78751c2bb0642bc0495363ff0e323dfbffc7a94804d9151554`.
Original simulator ZIP:
`703000eda93ee4aec7d237e71d3587111c315fd57d75aa76250d32309ec56f7a`.
Original unsigned-device ZIP:
`24381178e95f2a19013e1d1b3298b4e07d6e486b871e2ba7c617b11e0a763e65`.
Both exact source archives are byte-identical; all 7,704 tar member records and
file hashes also match. Matching source SHA-256:
`c5f9b4baaf84603044be962eac1deb370e488e14ecfc66c153820771d725bad9`.
Diagnostics artifact 12130697488 SHA-256:
`ff77075496be0cb80d79e6e3b41b2e586480a8f966f1346114a5e5fd3effdcec`.

For delivery limits, source was separated from two app ZIPs. Each retains all
500 original non-source members and Unix file modes, unchanged executable,
239 verified original content hashes, notices and explicit companion guidance:

- Simulator app ZIP: 12,539,619 bytes,
  `fb0a525dec6d83965831c2baf4a41f6046f45a188cc0548c96f9414843ce90ae`
- Unsigned-device app ZIP: 12,279,809 bytes,
  `d04077afad998a7ec8783aabb49265f3755ecbdf55e6801c0db19043f3756ffa`
- Shared complete corresponding source: 15,822,310 bytes, hash above

Keep the matching source companion and notices with either binary. The unsigned
physical-device build was never installed or executed. Simulator does not
implement local-network privacy; physical grant/denial remains untested.

## Earlier milestones and resolved failures

## Verified actual macOS/Simulator run

[Run 39108633642](https://github.com/LONG10222/psportal-on-demand/actions/runs/39108633642)
used PR head `a63600dab81aba38f5b4fecb35fab92289d0582f`, checked-out merge
`c76e17462f3d0da3d611ef149b711e63110c0a45`, macOS 15 arm64, Xcode 16.4,
iOS Simulator SDK/runtime 18.5, Go 1.27.2, pinned gomobile and XcodeGen 2.46.0.

- Real embedded simulator XCFramework compiled, Xcode project generated
- Swift/Objective-C Release app and Debug test bundle compiled and linked
- Actual app launched successfully after fixing a navigation-container crash
- XCTest: 10 passed, 1 explicit physical Data Protection skip, 0 failures
- Simulator platform metadata, executable and four bundled notices verified
- Complete matching source/vendor and dependency license archive packaged

Passed XCTest methods:

- `PrivateSettingsStoreTests.testSaveOmitsSubscriptionAndIsExcludedFromBackupThenForgotten`
- `ProxyLifecycleTests.testBackgroundStopsAndForegroundNeverRestarts`
- `ProxyLifecycleTests.testRepeatedStartIsIgnoredAndImmediateStopWins`
- `ProxyLifecycleTests.testSavedSettingsNeverAutoStart`
- `ProxyLifecycleTests.testStopRestoresPriorIdleTimer`
- `ProxySettingsTests.testClientListAndSelectionValidation`
- `ProxySettingsTests.testOnlyCanonicalRFC1918AddressesAreAccepted`
- `ProxySettingsTests.testPayloadMatchesSharedGoContractAndExcludesUIPreferences`
- `ProxySettingsTests.testStatusDoesNotDisplayNativeErrorOrNodeSecrets`
- `ProxySettingsTests.testSubscriptionAndPortsFailClosed`

`testCompleteDataProtectionOnPhysicalDevice` skipped explicitly. Lifecycle tests
use `RecordingDriver`, so this first green run does **not** prove real framework
HTTP/CONNECT, encrypted outbound routing, or physical background socket closure.
The native Go fixtures passed on macOS separately.

Artifact 12128764511: GitHub outer ZIP SHA-256
`8ad0b87aa3c9c0b985479c8f19b0eb723f54cb41a9ff880dfb175ab29acce7c9`.
Inner simulator ZIP (28,307,559 bytes):
`5c8f96bf6bd20225fdc624bef9fbcfe03b9d4d85293e4f9608b85db0aaa3cca3`.
Corresponding-source archive:
`9be8878e0c3ea7cc44a516f907e0b391e3f9d66c5745d454a77728ceb634d102`.
Bundled ENGINE-NOTICES:
`7d17847fa0b85799d19bca8202711f4d478b2d063c3d112ca704bb72578b0cb5`.
Diagnostics artifact 12128764515 includes complete XCTest results.

## Real framework transport and unsigned-device build verified

[Run 39109675540](https://github.com/LONG10222/psportal-on-demand/actions/runs/39109675540)
on head `4ef16d63a16fa9783e26cef5b69c488f5be5d80a` compiled the actual
simulator/device XCFramework and passed all three `EmbeddedTransportTests`:
`testRealFrameworkHTTPAndCONNECTDirectTraffic`,
`testRealFrameworkRejectsNonAllowlistedPeer`, and
`testRealFrameworkStopClosesOpenSocketAndCanRestart`.
Total XCTest: **13 passed, 1 hardware Data Protection skip, 0 failures**.
Unsigned iPhoneOS ARM64 app compilation/linking and iPhoneOS metadata checks
also passed. These tests use real TCP sockets and generated-framework calls.

The overall job failed only afterward: the selected simulator was shut down
following XCTest, so the independent Release-app install/screenshot returned
CoreSimulator error 405. The next script boots and waits for that existing
simulator before installation. The final successful run above resolved that step and completed packaging; no
physical device ran.

### Transport coverage

`EmbeddedTransportTests` calls the shipped generated-framework bridge directly,
without a fake engine/dialer or policy override. Three methods cover:

- Real direct HTTP forwarding/origin-form rewriting and proxy-header stripping;
  real CONNECT payload echo and half-close
- Stop closes an accepted partial-request socket; listener refuses connections
  after Stop; restart works; loopback destinations still return 403
- A real peer excluded by the listener allowlist receives 403

Tests require an existing RFC1918 interface for controlled in-process direct
fixtures. They fail with an explicit blocker if unavailable; they never change
interfaces or permit loopback destinations. No subscription or encrypted node
traffic is exercised by these direct fixtures.

The final successful CI also recorded separate Release simulator launch/
screenshot and exact per-file source/notice/executable hashes.
Physical-device testing, provisioning and signing remain separate.

## Linux source checks

Seven structural guardrails (six plus one generated-header skip on a clean
checkout), four CI-helper fixture tests, all shell syntax, YAML and plist parsing
passed locally. These checks do not replace Apple compiler/runtime evidence.

## Not claimed

- Physical iPhone/iPad or real Portal operation, signed IPA, provisioning/signing
- Real subscription/encrypted node traffic on iOS, local-network permissions,
  power/memory, hardware lock/background behavior, backup/Data Protection,
  crash-diagnostic privacy or full UI acceptance
- GPL/store-terms compatibility, privacy-manifest audit, export compliance,
  distribution approval or feature parity with Linux/Android

See `README.md` for build instructions and remaining device release gates.
