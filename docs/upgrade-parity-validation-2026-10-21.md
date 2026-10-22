# Upgrade parity development candidate — 2026-10-21

## Source and scope

Based on user PR #24 head `f822fdc8e3b01f3c18b230f7070375cf528f3ca1`, including PR #23 and the earlier `c1d2d3a` integration. This is a separate branch; main, user branches and the archived `starpass-test-20261020-c1d2d3a` release remain unchanged.

- Android: reject unsupported 32-bit universal APK fallback; keep retry button and cached-file state consistent after verification failure. Preserve fixed-source, hash/length/package/version/signer/provider safeguards.
- Desktop: user-initiated stable-release check and verified full-package download for Windows/macOS/Linux. Independent desktop semantic versions, architecture selection, bounded transfer and no-overwrite output. No automatic extraction, execution or program/config replacement.
- iOS: real installed version and manual official release guidance, guarded while sharing is active. No downloaded installer or lifecycle rewrite.
- Router: preflight/staging, complete private project backup, caught-file-failure restoration and symlink/concurrent-installer rejection. No automatic service restart or power-loss-atomic claim.

## Local evidence

- Baseline shared desktop: 443 tests, 48 environment-dependent skips, no failures. New shared desktop suite: 481 tests, 53 environment-dependent skips, no failures. Includes 33 updater core tests and 5 additional real-Tk tests awaiting graphical CI.
- Android: 425 JVM assertions, source/XML guards, 18 APK manifest helper tests passed. Additional Android device instrumentation source is included but not executed in this task.
- Router: 16 temporary-root packaging/installer tests passed, including missing payload, injected partial writes, backup failure and preservation. Shell syntax passed. Two independently generated source archives were byte-identical.
- Native desktop build helpers: 50 tests passed.
- iOS: 12 source guard tests (1 generated-header environment skip), 20 SDK26 guard tests, 6 CI helper tests passed. Two new XCTest cases require Apple CI.
- Real GitHub public release API returned only the existing test prerelease; no eligible production update was found. Synthetic release tests are not production download or signed-upgrade acceptance.

Final desktop additions and same-head CI results are recorded in the draft PR after the checks finish. A running or skipped workflow is not a passing build.

## Release limits

No physical Windows/Mac/Linux workstation, Android phone, iPhone, Portal or router was exercised by this task. CI/runtime fixtures and simulators are separate from real subscriptions, background/VPN/hotspot use and actual game connectivity. Android CI remains unsigned; macOS ad-hoc sealing is not notarization; iOS unsigned device output is not an installable IPA. No signing keys were created or uploaded. Do not relabel unsigned test archives as stable to make the updater detect them.

Downloads preserve existing files; manual desktop switch requires stopping and exiting first. Retaining an old app folder is not a guarantee of compatibility with future configuration migrations. Router rollback is best effort on caught errors; power loss or filesystem corruption requires manual recovery. Local router backups can contain secrets and must not be uploaded.
