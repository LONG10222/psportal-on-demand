# PSPortal local Mihomo derivative

This directory contains the complete Go module source distribution of
Mihomo v1.19.32, commit 88dcbf7f1614a67c3b36b848ee3592dfa92ada36,
with its original GPLv3 LICENSE, notices, source, tests, and documentation assets.

PSPortal modifications, 2026-10-19:

1. Make log/log.go's shared logging level atomic so configuration updates do not
   race concurrent logging, including adapter finalizers. Default level, public
   API and filtering semantics are retained.
2. Add opt-in tunnel ingress suspension, rejection and joining, including queued
   UDP jobs and their sender/reader descendants, before an embedder replaces
   process-global configuration. After lifecycle opt-in, deprecated unversioned
   TCPIn/UDPIn submissions are rejected. Serialize packet sender admission and
   closure so shutdown cannot strand a late packet.
3. Move queue Pop/Last locks before their slice-length reads. This removes a race
   with Put/Pop and prevents indexing an emptied slice after competing Pop calls.
4. Synchronize manual Selector choices with concurrent status, dialing and
   nested automatic-group health checks. Set/ForceSet writes and all selection
   reads share a mutex; no lock is retained while an adapter dials.

Focused regression tests accompany each patch. No race detection or logging is
suppressed. Exact production changes are limited to log/log.go,
common/queue/queue.go, tunnel/tunnel.go and tunnel/connection.go, plus the new
tunnel/ingress.go lifecycle API and adapter/outboundgroup/selector.go.

The original project is https://github.com/MetaCubeX/mihomo. This is a local
derivative, not an upstream release. Exact upstream module checksums, source
inventory, four modification patches and verification instructions are in
PSPORTAL-PATCHES/. The original documentation logos are retained only for complete
corresponding source and are not used as PSPortal app branding.
