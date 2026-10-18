# Android validation record

Checked 2026-10-18. These are actual development build results, not a physical-device
or Portal release signoff.

## Passed

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
- No signing identity was generated. `apksigner verify` reports the specific
  expected unsigned result, `Missing META-INF/MANIFEST.MF`

## Artifact provenance

Final unsigned APK: `app/build/outputs/apk/release/app-release-unsigned.apk`

- Size: 75,204,521 bytes
- SHA256: `fd3820fc49408ef1d5b9902348a9377ae60bfb07e28576c44c07a4669962a50c`
- Application ID `org.psportal.host`, version `0.1.0-dev` / code 1
- min SDK 26, target SDK 36; arm64-v8a and x86_64

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

Local reports (generated, not committed): `build/final-apk-build.log`,
`build/reports/apk-audit.json`, and
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

## Runtime limitations and remaining gates

The APK is **unsigned and cannot be installed**. Installation needs a separately
authorized signing identity. Build and lint success do not establish Android
runtime behavior or real Portal compatibility.

This development environment has no `/dev/kvm`. VM-accelerated emulation is
therefore unavailable here; software emulation may be possible but slower. The
official Emulator 37.2.12 and AOSP API 36 x86_64 revision 2 use the same SDK license,
not an additional Google Play agreement. No emulator app execution, physical
phone test or real Portal test is claimed by this record.

Remaining runtime gates are listed in README: permission grant/deny/revocation,
foreground notification and Stop action, process/lifecycle transitions, real
JNI start/stop, LAN routing and allowlist, lazy wake/idle teardown, node selection,
16 KiB device execution, Wi-Fi changes and screen-off/Doze/OEM behavior.

## Optional CI

`../ci/android-unsigned.yml.example` and `tools/ci-unsigned.sh` prepare a standard
public-repository Ubuntu build with matching source/licenses and one-day artifact
retention. The template is inactive until reviewed and copied into GitHub's
workflow directory. Shell syntax and YAML structure are checked locally; no
GitHub Actions run is claimed. CI also produces only an unsigned APK.
