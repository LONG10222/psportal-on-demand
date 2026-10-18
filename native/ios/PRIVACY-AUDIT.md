# Bounded iOS privacy/resource audit

Reviewed 2026-10-18. This is a source and artifact review, **not** an Apple
validation result, complete data-flow audit, privacy policy or App Store approval.

## Exact previously delivered artifacts

Run [39110679850](https://github.com/LONG10222/psportal-on-demand/actions/runs/39110679850),
head `7a6837e0c9070a861f2718e71cb155454ce1ea24`, checked-out merge
`f5375adc87dd4808d5ae07bb2376ffecc697af2a`, app version 0.1.0 (1):

- Simulator executable SHA-256:
  `5c7269339092dc677cee07399f8e1ee78d3a2bbe5b98eee0f7e230f39eca24d9`
- Unsigned device executable SHA-256:
  `7d59284d82fc24edf3524c7ca6ae812f028e000fa542b9ae98b1dd10b2558f19`

Both real Mach-O external-symbol tables import `_stat`, `_fstat`, `_fstatat`,
`_lstat` and `_mach_absolute_time`. Neither delivered app has a
`PrivacyInfo.xcprivacy`. Those development artifacts remain byte-identical and
their transport/build results remain valid; they are not distribution-ready.

Both contain the complete GPL, original MIT, third-party and generated engine
notices, local-network usage description, no background modes, no file sharing,
no extension bundle, and no device provisioning profile. Neither declares an
app icon. The icon and complete distribution assets remain open release work.

## Narrow correction in this revision

The app now includes `PrivacyInfo.xcprivacy` in its root resources with only:

- `NSPrivacyAccessedAPICategoryFileTimestamp`, reason `C617.1`: app-container
  file metadata. `PrivateSettingsStore` reads its own settings size, sets file
  attributes and manages only its private Application Support directories.
  The linked Go runtime/library filesystem primitives account for the C imports.
  The mobile API rejects local subscription files; subscription credentials are
  not persisted. There is no document picker or external file-metadata feature.
- `NSPrivacyAccessedAPICategorySystemBootTime`, reason `35F9.1`: elapsed time and
  timers. The engine uses `time.Now`, deadlines, context timeouts, idle/health
  timers, and connection time budgets; the Go Darwin monotonic clock links
  `mach_absolute_time`. The app does not expose or transmit device boot time.

Apple's [API categories and allowed reasons](https://developer.apple.com/documentation/bundleresources/app-privacy-configuration/nsprivacyaccessedapitypes/nsprivacyaccessedapitype)
identify these APIs/reasons. Its [manifest placement guidance](https://developer.apple.com/documentation/bundleresources/adding-a-privacy-manifest-to-your-app-or-third-party-sdk)
places an iOS app manifest at the bundle root. The reason codes describe these
specific uses; they are not permission to collect unrelated metadata.

No speculative UserDefaults, disk-space, keyboard, tracking or collected-data
declaration has been added. A broader review must consider actual app and
dependency data flows, user-configured subscription/proxy providers, required
privacy disclosures and Apple's then-current SDK requirements before release.
An imported-symbol scan is not a proof that all Objective-C selectors, dynamic
calls, transitive SDK behavior or all data collection have been identified.

The source guardrail validates exact reasons. A new XCTest checks the actual
host bundle's manifest and four license resources. CI audits both Release apps'
root manifest, imported symbols, metadata and notices, records hashes, and
rejects newly detected unsupported categories instead of inventing reasons.
The manifest is included in each content-hash list. Full Apple build/runtime
validation of this correction is pending its next CI run; only then does the
new source/app pair supersede the prior package for this resource requirement.

## Final archive and signature boundary

CI also extracts the completed Simulator/device ZIPs, verifies their content
manifests, compares every app member's bytes and Unix permission modes with the
built app, and checks that corresponding source remains beside the app. It
rejects unexpected nested frameworks/dylibs, which would need their own audit.
The framework is currently statically linked. It records both `codesign
--display --verbose=4` and `codesign --verify --strict --verbose=4` outcomes on
the extracted apps. Nonzero unsigned/unsealed outcomes are recorded as such,
not described as successful signature verification. No identity signing is
performed. Device code signatures/profiles are forbidden by the gate.

The Simulator linker may create an executable code signature despite
`CODE_SIGNING_ALLOWED=NO`; that alone is not a bundle resource seal or trusted
distribution signing. The exact archive-extracted Simulator app is installed,
launched, checked alive and screenshotted after these checks. It remains a
development-only Simulator build. A passing resource/launch gate does not turn
an unsigned device app into an installable one.

## Integrated encrypted-node lifecycle boundary

The shipped gomobile API exposes only Start/Stop/Status. It directly constructs
the production core. Subscription fetch requires public DNS and valid HTTPS;
adapter creation uses the production protected public dialer. Existing native
fixture dialers are only in Go `_test.go`, absent from the shipped framework.
The current real iOS TCP tests use permitted LAN destinations, intentionally
leave the outbound pool asleep, and do not prove encrypted-node wake/idle/rewake.

Testing that exact mobile binary successfully requires an authorized reachable
public HTTPS subscription and public proxy endpoint. Neither controlled endpoint
is available in this task environment. No production bypass, new hosted service,
account or arbitrary public proxy is introduced. A separately tagged test
framework would be a different binary and would not prove the delivered public
subscription path. Existing Go real-adapter tests use a controlled SOCKS5 fixture;
they must not be described as an encrypted-node iOS integration test.

Physical iPhone permissions, lock/background behavior, hardware Data Protection,
backup effects, energy use and Portal sessions still require owner-authorized
hardware/signing validation. See `README.md` and `VALIDATION.md`.
