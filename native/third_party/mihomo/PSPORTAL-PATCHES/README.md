# Pinned synchronization and embedding-lifecycle patches

Upstream: https://github.com/MetaCubeX/mihomo/tree/v1.19.32
Commit: 88dcbf7f1614a67c3b36b848ee3592dfa92ada36

The original Go module ZIP was already available in the verified module cache.
Its canonical Go h1 checksum was independently recomputed before extracting all
1,009 files. No upstream file is omitted, including the two immutable upstream
PNG documentation logos. The module cache was not modified.

The ordered, independently reproducible patch series is:

1. 0001-atomic-log-level.patch: atomic.Int64 replaces the unsynchronized logging
   level; initialization, Level(), SetLevel() and print() use atomic access.
   int64 preserves every int-based LogLevel value on supported architectures.
   A concurrent public logging regression covers the adapter-finalizer read path.
2. 0002-ingress-quiescence.patch: new SuspendIngress/WaitIngress/ResumeIngress
   APIs opt an embedder into an admission and joining contract. Accepted TCP
   work, UDP queue entries and spawned UDP sender/reader descendants retire before
   global configuration can be replaced. The embedder closes owned dials and
   connections between SuspendIngress and WaitIngress. Deprecated raw channels
   are rejected after opt-in because submissions have no generation identity.
   Normal upstream admission starts open. Packet-sender Send/Close synchronization
   prevents admission after closure drains its queue. The legacy TCP dispatch
   explicitly passes its context into the goroutine, preserving Go 1.20 semantics.
3. 0003-queue-synchronization.patch: Pop/Last lock before inspecting queue length,
   keeping empty checks and element access in one critical section. A regression
   uses public Put/Last/Pop concurrently; empty-queue zero-value behavior remains.
4. 0004-selector-synchronization.patch: Set and ForceSet synchronize the selected
   name with selectedProxy readers. Each read takes one name snapshot and releases
   the lock before invoking a member. Background automatic groups may probe a
   nested manual selector even when the embedder reports no active client flows.
   Socket-free tests cover concurrent control, status, unwrap, TCP/UDP and
   capability reads, plus default-selected and invalid-selection semantics.

No race suppression, hidden module-cache patch or global-variable reset replaces
proper teardown. The Android embedding code must honor the ingress API contract;
calling WaitIngress without first canceling/closing owned flows can wait forever.

PROVENANCE.json identifies exact upstream and local content. UPSTREAM-FILES.sha256
lists every original module file. Applying the four patches in order reproduces
all production changes and regression tests. The parent go.mod uses a
version-specific local replace; an upstream update therefore requires deliberate
review of the pin, patches, inventory and replacement.

From native/, with the project's pinned Go toolchain and cached dependencies:

    python3 scripts/verify_mihomo_patch.py
    GOPROXY=off GOSUMDB=off GOTOOLCHAIN=local go test -race -count=10 -tags no_easytier,no_zerotier,no_tailscale github.com/metacubex/mihomo/log github.com/metacubex/mihomo/common/queue github.com/metacubex/mihomo/tunnel github.com/metacubex/mihomo/adapter/outboundgroup
    GOPROXY=off GOSUMDB=off GOTOOLCHAIN=local go test -race -tags no_easytier,no_zerotier,no_tailscale,with_gvisor ./androidcore ./androidmobile

For a fresh build, normal Go tooling retrieves pinned dependencies. For offline
builds, the corresponding-source archive includes this entire replacement and
go mod vendor output. It does not depend on edited module-cache contents.
The license collector retains original module identity alongside local patch
provenance and collects licenses from the replacement actually used.
