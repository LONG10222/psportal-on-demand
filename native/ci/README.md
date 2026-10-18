# Native validation workflows

These `.yml.example` files are inactive. A repository maintainer must review and
copy the selected template into `.github/workflows/` to run it. This directory does
not modify an existing release workflow.

## Desktop

`native-desktop.yml.example` uses standard public-repository runners:

- `ubuntu-24.04`: Linux x64
- `windows-2025`: Windows x64
- `macos-15`: macOS Apple Silicon

Runner labels and their architectures are documented by
[GitHub](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
The actual host architecture and operating-system version are recorded in each
artifact's `VALIDATION.json`. Linux ARM64, Windows ARM64 and Intel macOS are not
runtime-tested by this three-runner template; existing cross-built files must not
be described as runtime-tested on the strength of these jobs.

Each job runs module verification, every Go test, `go vet`, and an actual host-built
CLI smoke test. Linux/macOS also run the engine race detector. Windows uses the
portable stdin-EOF stop contract; Unix additionally tests SIGTERM. The smoke test
checks `--check`, readiness, strict denied requests, a cold adapter pool, restart,
and local-provider configuration using only loopback fixtures. It does not prove
live-provider interoperability, GUI behavior, installer trust, or LAN-device
access. No test credentials or real subscription are required.

Only a successful job uploads a distributable bundle. Every bundle contains its
host executable archive, complete matching vendored corresponding source, GPL and
dependency notices, test evidence, source commit, and SHA-256 checksums. Executables
are unsigned and macOS artifacts are not notarized. There is no signing, release
creation, installer registration, firewall change, or persistent service setup.

The templates use read-only repository permissions, do not persist checkout
credentials, skip private repositories, and use one-day artifact retention with a
200 MiB success-artifact budget. They use no larger runners or paid services. The
workflow must actually complete before a platform can be called runtime-tested;
a valid YAML template or successful cross-compilation is insufficient.

## iOS

`ios-simulator.yml.example` builds the actual in-process mobile engine and the
foreground-only simulator host, then runs XCTest. See `ios/README.md` for the
Apple SDK, simulator, unsigned-build and foreground-only constraints. A successful
simulator job is not a physical-device or App Store validation.

## Android

`android-unsigned.yml.example` builds and audits the real shared-engine APK with
matching source and licenses. See `android/VALIDATION.md` for the completed local
unsigned build and `android/README.md` for the remaining runtime and signing gates.
An unsigned APK cannot be installed, and successful build/lint checks are not a
phone, emulator or Portal runtime test.
