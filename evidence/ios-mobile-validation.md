# iOS runtime panels — 2026-10-19

- Actual simulator-arm64 XCFramework rebuilt via the pinned gomobile recipe; SwiftUI app linked on Xcode 27.0 / iOS 27.0 Simulator.
- XCTest: 21 total, 20 passed, one explicit physical Data Protection skip, zero failures.
- Real bridge tests verify HTTP/CONNECT direct fixtures, source denial, device telemetry, command ABI and Stop/restart. Panel model tests verify listener rather than outbound-lease counts, runtime clearing, Unicode node names and language switching.
- Go engine/mobile tests with race detector passed, including five controls/telemetry tests for manual/no-fallback routing, latency order, cancellation, failed-probe selection preservation, and one-IP/multiple-socket counting.
- Source guardrails: 8/8 passed after generating actual Objective-C headers; required NodeCommand ABI verified in the built framework.
- CUA inspection: Share, Nodes and Devices tabs; immediate Chinese/English switching. Screenshots are stopped-state UI without user subscriptions or fabricated live data.
- Real encrypted subscription routes, physical hotspot and game-console acceptance remain unverified. No original Clash or OS network settings changed.
