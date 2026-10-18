# Startup and idle lifecycle

The listener no longer waits inside `wake_core`. The first external request
starts one readiness worker; additional external requests share that startup.
Client input is backpressured at the existing buffer limit while it waits.
The main poll loop continues to accept and relay approved LAN requests.

The readiness worker owns a separate process group, closes inherited listener
and session sockets, starts the service if necessary, and verifies the selected
route's health. The parent checks completion with nonblocking `waitpid`, bounds
startup by `wakeup_timeout`, and returns 503 on failure. A later request can
retry. The `starts` status counter counts readiness-worker attempts, including
attempts against an already-running core. Backend connection errors and timeouts invalidate readiness too.

Worker ownership is scoped to the launcher generation and Linux process start
time. Stop/restart marks cancellation before killing a recorded worker group;
a late worker must recheck ownership before starting the service. A stale
worker cannot cancel a newer generation's core. These source hooks do not run
until an updated package is explicitly installed.

The idle budget starts when readiness completes, not when the wake request
arrives. Waiting or connecting requests are protected by their own deadlines.
Successfully relayed external bytes refresh the budget. Buffered bytes alone
do not keep the core alive forever if the peer stops consuming data. LAN bytes
do not refresh external idleness.

## Verification boundaries

`tests/lifecycle.lua` runs the actual listener source inside a fake environment:
no network, fork, signals, services, clock waits, or output files are real.
`tests/ownership.lua` tests cancellation and generation races with mocked
process identities/files. Pure protocol and DNS tests exercise destination
checks and malformed packet handling. Run all of them with Lua 5.1 in CI.

These tests do not establish real OpenWrt/procd signal, process-group, UCI or
Mihomo compatibility. Before deployment, test slow startup, service failure,
stop/restart during startup, cancellation of descendants, and LAN forwarding
on a disposable target with the intended versions. Cancellation covers descendants
that remain in the readiness worker's process group. Detached service descendants
and in-flight procd requests need target validation. If a worker leader has
already been reaped, the stop helper cannot prove its identity through `/proc`;
it does not blindly signal a stale PID. The live launcher also retires the group
on an observed abnormal worker exit. The existing optional
router smoke test uses fixtures and is not a live streaming test.

The startup wait is asynchronous; service stop and status/ubus calls still run
in the listener and can pause it if the platform is slow. General platform
portability, asynchronous DNS, fully asynchronous service control, and UDP
streaming remain outside this patch.
