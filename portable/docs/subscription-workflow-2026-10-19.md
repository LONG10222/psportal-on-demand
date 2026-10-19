# Desktop subscription workflow — 2026-10-19

Based on the validated Windows control-pipe fixes in `bb5c1e7`, plus the upstream
native Windows read-cancellation fix `a0dcf23`. This iteration changes desktop
interaction; Android and iOS onboarding are unchanged.

## User-visible behavior

1. **Paste link** and the input's normal paste shortcut replace the entire URL
   field, import a snapshot, and save it privately. Manual typing is committed
   with Enter. Importing never starts the listener or discovers the LAN.
2. A completed identical URL/snapshot is reused. Repeated clicks while an import
   is in flight do nothing. Stop/start and reopening the window reuse the saved
   import; **Refresh subscription** is the explicit action that downloads again.
3. **Start sharing** is a single fixed-footer action, available from every simple
   page. It detects the LAN once, validates and starts the existing imported
   snapshot. Advanced mode retains explicit configuration and Start listener.
4. Changing a URL invalidates the old snapshot for startup until a successful new
   import. A cancelled/stale import cannot start the app or override navigation.
   Import failures remain inline; a failed refresh keeps the old accepted snapshot.
5. A successful import saves only the source settings and preserves unrelated
   unsaved form edits. The draft is not runtime validation: Start still validates
   the complete configuration. A URL SHA-256 marker binds the saved source to its
   accepted URL without adding another plaintext URL field.
6. The core chooser is visible on the home page. Missing core paths have a direct
   hint, and simple Start is disabled until a valid source and core are present.
   Connection instructions display the address only after listener readiness.
7. The Windows UI uses Microsoft YaHei UI, centers within the available screen
   bounds, scrolls the overview, and keeps footer controls outside that scroll.
   While running, live status replaces the disabled import form. Read-only LAN
   detection runs without opening a console window.
8. Unselected Clash accounting is no longer read/displayed as if it were the new
   subscription. Explicit linked mode retains read-only cached accounting and can
   restart sharing through the common Start action.

## Validation

Windows 11 x64 build 26300; Python 3.12.14; Tcl/Tk 8.6.12; PyYAML 6.0.3;
PyInstaller 6.16.0; trusted official Mihomo v1.19.32 Windows compatible build.

- Full final portable suite: **331 tests, 290 passed, 41 conditional skips**.
- Real Tk tests exercise paste virtual events, repeated/in-flight imports,
  persistence/reload, explicit refresh, failure recovery, stale-link startup
  refusal, preservation of unsaved edits, metadata isolation, navigation and
  fixed-footer accessibility at 1040×740.
- The existing real-core and Windows frozen checks cover HTTP/CONNECT,
  active/idle/rewake lifecycle, Unicode node controls, invalid control input,
  listener restart, normal window close and cleanup.
- The actual frozen Windows home page was visually inspected. No actual user
  subscription was imported or sent through the test harness. Synthetic import
  tests replace only the downloader with a local fixture; runtime tests use
  controlled loopback upstreams.
- Tested local external-mode EXE SHA-256:
  `71fb8ed15ededb727c519e391de0e3272710b7ac26cf42950c243959b676b2bd`.
- `git diff --check` passed. Native/mobile sources were not newly modified here;
  the inherited native fix keeps its upstream validation record.

To reproduce, use the Windows environment and commands in
[Windows validation](windows-validation-2026-10-19.md), enabling `PSPORTAL_TK_TEST`,
`PSPORTAL_BINARY`, `PSPORTAL_FROZEN_WINDOW_TEST`, and `MIHOMO_BINARY`.

These are local development checks, not physical Portal/PS5, real subscription,
Wi-Fi/firewall or embedded-engine acceptance. Other-platform conditional skips
are not passes. Public binary distribution still requires the existing exact
runtime/license/source gates; this local EXE is an unsigned development preview.
