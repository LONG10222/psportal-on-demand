# iOS source validation record

Prepared 2026-10-18 on Linux. This records a source milestone, not an Apple build.

## Passed here

- `python3 native/ios/scripts/check-source.py`: 7 structural guardrail checks
- `bash -n` on all iOS shell scripts
- `python3 native/ios/scripts/check-ci-helpers.py`: simulator-selection and bounded-diagnostics fixture tests
- XML property-list parsing with Python `plistlib`
- Project YAML parsing with PyYAML and verification that both target source paths exist
- Inspected actual generated Objective-C binding at
  `native/dist/bindings/objc/src/gobind/Mobile.objc.h`: the bridge's Start/Stop/Status
  calls match the generated declarations
- Confirmed the shared native engine sets Mihomo's logging level to SILENT
- Confirmed the Apple framework helper refuses Linux before installing tools or
  attempting compilation; missing-framework verification fails closed

The structural checks assert no background modes, Network Extension target,
automatic startup, downloaded executable launcher, or subscription serialization;
they also inspect explicit background/lock Stop handling, stale-callback guards,
idle-timer restoration, private-file protection, backup exclusion, real engine
calls and bundled GPL/MIT notices. Structural checks cannot establish runtime
correctness or replace compiler validation.

## Included, not run

Eleven XCTest methods covering settings validation/payloads, sanitized status, URL
non-persistence, protected-file/backup metadata, repeated Start/Stop ordering,
background Stop, no automatic restart, and idle-timer restoration. Lifecycle
tests use a test-only recording driver; they do not validate the transport.
The physical-device Data Protection method explicitly skips on Simulator rather
than claiming hardware-backed encryption is proven there.

An inactive GitHub Actions template now exists at
`native/ci/ios-simulator.yml.example`. Its YAML, single standard public-runner job,
read-only repository permission, SHA-pinned actions and shell syntax were checked
locally. It has not run, and does not change the unvalidated Apple-build status.

## Not available and not claimed

- XcodeGen project generation on a Mac
- Apple SDK/Swift/Objective-C compilation or static framework linking
- A built XCFramework, `.app`, signed `.ipa`, simulator execution, or XCTest run
- Provisioning, signing, physical iPhone/iPad or PlayStation Portal operation
- Real iOS subscription/node traffic, permissions, power/memory, lock/background
  socket closure, crash-diagnostic privacy, backup behavior, or app-switcher UI QA
- GPL/store-terms compatibility, privacy-manifest audit, export compliance or
  distribution approval

`README.md` contains the Mac build steps and physical-device release checklist.
The shared mobile build generates complete engine dependency notices before
building; `verify-build-inputs.sh` requires both those notices and the real
XCFramework. No placeholder transport or fabricated iOS artifact is supplied.
