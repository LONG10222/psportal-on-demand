# Shared native engine in the desktop app

Validation date: 2026-10-18 UTC. This is a follow-on development change to the
previous separate-Mihomo Linux milestone, not a claim of finished platform parity.

## What changed

One desktop window now selects `external` (unchanged default fallback) or
`embedded` (experimental shared native engine). It retains the same listener,
allowlist, URL/local-provider, node selection and idle controls. Each engine has
its own executable field. Changing the engine requires stopping first and never
happens automatically after a failure.

The native child receives only an explicit supported-field allowlist in a private
temporary JSON file. Python-only settings, unknown keys and the unused URL/token
when a local file is chosen are omitted. POSIX directory/file modes are 0700/0600.
Launch failures and observed exits clean up the temporary configuration. A hard
parent termination can leave private temporary files; the closed stdin pipe still
stops the native listener. No shell, downloaded code, OS network settings or
remote repository changes are involved.

Readiness requires the native JSON event to match the requested host, port and
engine. Logs retain URL/token redaction and drop oversized records whole. The
Python CLI and frozen `--backend` entrypoint also dispatch explicit embedded
configurations. Both normal Stop and parent EOF close the owned native process.

## Verified on Linux

The new test module `tests/test_embedded.py` covers 28 cases:

- Default external fallback and engine-specific executable validation, including
  rejecting Windows batch scripts for the native executable
- Source/frozen command generation without a shell, fixed bundled lookup paths
- Native-only validation limits without tightening external compatibility
- Private temporary permissions, explicit projection and unused-token omission
- Cleanup on spawn failure, exact readiness matching and original-child redaction
- Late buffered readiness from an exited child cannot mark a replacement or
  stopped controller as listening; process/readiness updates are synchronized
- Engine control enable/disable, duplicate Start, cancel Close and confirmed Close
- Actual native schema check through the Python CLI, using the built Linux engine
- Actual native desktop-controller readiness, restricted destination rejection,
  empty local-provider failure, repeated Stop and restart, listener closure and
  temporary-file cleanup
- Actual source CLI stdin EOF and SIGTERM; abrupt parent disappearance stops the
  native listener; occupied-port startup failure is observed without taking over
  the existing socket
- One optional frozen embedded-dispatch/EOF test, enabled with
  `PSPORTAL_DUAL_BINARY` after building a matching package

The original 78 Python tests were also rerun with the trusted real Mihomo and
previous frozen external-mode executable supplied; all 78 passed. This preserves
the previously established controlled HTTP/CONNECT, active/idle, fixed-selection
and EOF-cleanup regression evidence. It is not a native-engine real-provider test.

An earlier dual-engine build passed 104 tests with zero skips. A further audit
then identified and fixed a buffered-readiness restart race, with two new
regression tests; packaged-startup and opt-in graphical-window tests were also
added. The final Debian-Python Linux rebuild passed **108 tests: 107 passed and
one graphical-window test skipped** in 16.026 seconds, with both frozen CLI
routes, actual external Mihomo and the bundled native binary enabled. The GUI
test requires an isolated X11 display, which was not available for this run.

Additional smoke checks against that same final Debian build passed automatic
bundled-native discovery with a blank `native_path`, all three selection-mode
schema handoffs, stdin-EOF shutdown, token-safe output, and refusal to silently
switch to an available external core when the configured native path is invalid.
Selection handoff checks are not real-node ordering/health acceptance. The
canonical and Debian-build `desktop.py` source hashes were also checked equal.

Tested executable SHA256 values:

```text
PSPortalProxy: 90bb6f3e59aec6cde159f13a24bfcbd7586f946ff8efa6bae763f5ff01ef4590
native/psportal-native: dedd5197f99f9d478086d635246944be7fc73891ba3484c76774533339461c5a
```

Reproduce all checks with a rebuilt package and trusted test binaries:

```sh
MIHOMO_BINARY=/trusted/path/mihomo \
PSPORTAL_BINARY=/trusted/path/PSPortalProxy \
PSPORTAL_NATIVE_BINARY=/trusted/path/psportal \
PSPORTAL_DUAL_BINARY=/trusted/path/PSPortalProxy \
python -m unittest discover -s tests -v
```

The real-native desktop smoke uses an empty synthetic provider and localhost
client/listener. It proves safe failure and lifecycle without contacting a real
node, subscription or PlayStation service. Native adapter HTTP/CONNECT tests live
separately under `native/engine` and must be reported with their own evidence.

## Not established here

- GUI visual inspection or real mouse/keyboard use on a graphical desktop
- Native Windows/macOS GUI builds or runtime behavior
- Physical Portal, trusted LAN/Wi-Fi, real providers or remote-node performance
- Every Mihomo configuration/protocol: the embedded subset and restrictions are
  explicit in [the desktop guide](desktop.md#choose-an-engine-in-the-same-app)
- Mobile app builds, signing, store review or device/background acceptance

Distribution of a dual-engine build additionally needs the native license
notices and exact corresponding source. The separate external-mode milestone
validation remains recorded in `validation.md`; its results do not automatically
cover a different rebuilt artifact. The hashes above identify this follow-on
package's tested executables.
