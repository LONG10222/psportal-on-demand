// SPDX-License-Identifier: GPL-3.0-only
import XCTest
@testable import PSPortalHost

/// Deterministic orchestration with synthetic interface updates. These tests
/// do not claim physical Wi-Fi/hotspot delivery or transport coverage.
final class NetworkLifecycleTests: XCTestCase {
    @MainActor
    func testFirstPublishedDisconnectStopsWithoutMountedView() async {
        let harness = NetworkHarness()
        defer { harness.removeFiles() }
        harness.model.quickStart()
        await harness.waitFor { harness.model.state == .running }

        // @Published notifies before network.snapshot is assigned. The old
        // view callback read that previous property and missed this event.
        harness.network.updateSnapshot(NetworkSnapshot(uplink: .unavailable))
        XCTAssertEqual(harness.model.state, .stopping)
        await harness.waitFor { harness.model.state == .stopped }
        XCTAssertEqual(harness.driver.counts().stops, 1)
        XCTAssertTrue(harness.model.message.contains("Network changed"))

        harness.network.updateSnapshot(NetworkHarness.connected)
        XCTAssertEqual(harness.model.state, .stopped)
        XCTAssertEqual(harness.driver.counts().starts, 1, "Reconnect must not restart implicitly")
    }

    @MainActor
    func testAddressChangeDuringStartupInvalidatesLateCompletion() async {
        let harness = NetworkHarness(blockStart: true)
        defer { harness.driver.releaseStart(); harness.removeFiles() }
        harness.model.quickStart()
        XCTAssertEqual(harness.model.state, .starting)
        let changed = NetworkSnapshot(uplink: .wifi, interfaces: [
            LANInterface(name: "en0", address: "192.168.7.3", mask: "255.255.255.0")
        ])
        harness.network.updateSnapshot(changed)
        XCTAssertEqual(harness.model.state, .stopping)
        harness.driver.releaseStart()
        await harness.waitFor { harness.model.state == .stopped }
        XCTAssertEqual(harness.driver.counts().starts, 1)
        XCTAssertEqual(harness.driver.counts().stops, 1)
        XCTAssertFalse(harness.driver.counts().running)
        XCTAssertTrue(harness.model.message.contains("Network changed"))
    }

    @MainActor
    func testIdenticalSnapshotsDoNotStopAndDuplicateLossStopsOnce() async {
        let harness = NetworkHarness()
        defer { harness.removeFiles() }
        harness.model.quickStart()
        await harness.waitFor { harness.model.state == .running }
        harness.network.updateSnapshot(NetworkHarness.connected)
        harness.network.updateSnapshot(NetworkHarness.connected)
        XCTAssertEqual(harness.model.state, .running)
        XCTAssertEqual(harness.driver.counts().stops, 0)

        let disconnected = NetworkSnapshot(uplink: .unavailable)
        harness.network.updateSnapshot(disconnected)
        harness.network.updateSnapshot(disconnected)
        await harness.waitFor { harness.model.state == .stopped }
        XCTAssertEqual(harness.driver.counts().stops, 1)
    }
}

@MainActor
private final class NetworkHarness {
    static let connected = NetworkSnapshot(uplink: .wifi, interfaces: [
        LANInterface(name: "en0", address: "192.168.7.2", mask: "255.255.255.0")
    ])
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let network: NetworkEnvironment
    let driver: NetworkDriver
    let model: ProxyModel

    init(blockStart: Bool = false) {
        network = NetworkEnvironment(initialSnapshot: Self.connected, monitorsChanges: false)
        driver = NetworkDriver(blockStart: blockStart)
        model = ProxyModel(engine: EngineController(driver: driver), store: PrivateSettingsStore(directory: directory),
                           network: network, findPort: { _, preferred in preferred })
        model.settings = validSettings()
        model.scenePhaseChanged(.active)
    }

    func waitFor(_ condition: () -> Bool) async {
        for _ in 0..<100 {
            if condition() { return }
            try? await Task.sleep(nanoseconds: 20_000_000)
        }
        XCTFail("Network lifecycle operation did not finish")
    }

    func removeFiles() { try? FileManager.default.removeItem(at: directory) }
}

private final class NetworkDriver: EngineDriver {
    private let lock = NSLock()
    private let gate = DispatchSemaphore(value: 0)
    private let blockStart: Bool
    private var starts = 0
    private var stops = 0
    private var running = false

    init(blockStart: Bool) { self.blockStart = blockStart }
    func releaseStart() { gate.signal() }
    func start(configJSON: String) -> String? {
        if blockStart { _ = gate.wait(timeout: .now() + 5) }
        lock.lock(); defer { lock.unlock() }
        starts += 1; running = true
        return nil
    }
    func stop() {
        lock.lock(); defer { lock.unlock() }
        stops += 1; running = false
    }
    func statusJSON() -> String {
        lock.lock(); defer { lock.unlock() }
        return "{\"running\":\(running),\"state\":\"stopped\",\"active\":0}"
    }
    func counts() -> (starts: Int, stops: Int, running: Bool) {
        lock.lock(); defer { lock.unlock() }
        return (starts, stops, running)
    }
}
