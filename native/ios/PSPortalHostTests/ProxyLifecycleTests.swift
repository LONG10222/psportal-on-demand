// SPDX-License-Identifier: GPL-3.0-only
import XCTest
import UIKit
@testable import PSPortalHost

/// These mocks test orchestration only. They do not prove transport works.
final class ProxyLifecycleTests: XCTestCase {
    @MainActor
    func testLanguageAndAppearanceSwitchWithoutRestartOrSettingsLoss() async {
        let harness = LifecycleHarness()
        let model = harness.model
        model.start()
        for _ in 0..<100 {
            if model.state == .running { break }
            try? await Task.sleep(nanoseconds: 20_000_000)
        }
        XCTAssertEqual(model.state, .running)
        let before = model.settings
        model.language = "en"
        model.darkAppearance = false
        XCTAssertTrue(model.localizedMessage.contains("Listening"))
        model.language = "zh"
        model.darkAppearance = true
        XCTAssertTrue(model.localizedMessage.contains("监听"))
        XCTAssertEqual(model.settings, before)
        XCTAssertEqual(harness.driver.snapshot().starts, 1)
        XCTAssertTrue(harness.driver.snapshot().running)
        model.stop()
        await harness.waitUntilStopped()
        harness.removeFiles()
    }

    @MainActor
    func testRepeatedStartIsIgnoredAndImmediateStopWins() async {
        let harness = LifecycleHarness()
        let model = harness.model
        model.start()
        model.start()
        model.stop()
        await harness.waitUntilStopped()
        XCTAssertEqual(harness.driver.snapshot().starts, 1)
        XCTAssertFalse(harness.driver.snapshot().running)
        XCTAssertEqual(model.state, .stopped)
        harness.removeFiles()
    }

    @MainActor
    func testBackgroundStopsAndForegroundNeverRestarts() async {
        let harness = LifecycleHarness()
        let model = harness.model
        model.start()
        model.scenePhaseChanged(.background)
        model.didEnterBackground() // Duplicate UIKit notification must be safe.
        await harness.waitUntilStopped()
        XCTAssertFalse(harness.driver.snapshot().running)
        model.scenePhaseChanged(.active)
        XCTAssertEqual(model.state, .stopped)
        XCTAssertEqual(harness.driver.snapshot().starts, 1)
        harness.removeFiles()
    }

    @MainActor
    func testStopRestoresPriorIdleTimer() async {
        let harness = LifecycleHarness()
        let model = harness.model
        let original = UIApplication.shared.isIdleTimerDisabled
        defer { UIApplication.shared.isIdleTimerDisabled = original }
        UIApplication.shared.isIdleTimerDisabled = false
        model.settings.keepAwake = true
        model.start()
        XCTAssertTrue(UIApplication.shared.isIdleTimerDisabled)
        model.stop()
        XCTAssertFalse(UIApplication.shared.isIdleTimerDisabled)
        await harness.waitUntilStopped()
        harness.removeFiles()
    }

    @MainActor
    func testSavedSettingsNeverAutoStart() throws {
        let harness = LifecycleHarness()
        defer { harness.removeFiles() }
        let store = PrivateSettingsStore(directory: harness.directory)
        try store.save(validSettings())
        let reloaded = ProxyModel(engine: EngineController(driver: harness.driver), store: store)
        reloaded.scenePhaseChanged(.active)
        XCTAssertEqual(reloaded.state, .stopped)
        XCTAssertTrue(reloaded.hasSavedSettings)
        XCTAssertEqual(harness.driver.snapshot().starts, 0)
    }
}

@MainActor
private final class LifecycleHarness {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let driver = RecordingDriver()
    let model: ProxyModel

    init() {
        model = ProxyModel(engine: EngineController(driver: driver), store: PrivateSettingsStore(directory: directory))
        model.settings = validSettings()
        model.scenePhaseChanged(.active)
    }

    func removeFiles() { try? FileManager.default.removeItem(at: directory) }

    func waitUntilStopped() async {
        for _ in 0..<100 {
            if model.state == .stopped { return }
            try? await Task.sleep(nanoseconds: 20_000_000)
        }
        XCTFail("Stop did not finish within the orchestration-test deadline")
    }
}

private final class RecordingDriver: EngineDriver {
    private let lock = NSLock()
    private var starts = 0
    private var running = false
    func start(configJSON: String) -> String? {
        lock.lock(); defer { lock.unlock() }
        starts += 1
        running = true
        return nil
    }
    func stop() {
        lock.lock(); defer { lock.unlock() }
        running = false
    }
    func statusJSON() -> String {
        lock.lock(); defer { lock.unlock() }
        return "{\"running\":\(running),\"state\":\"stopped\",\"active\":0}"
    }
    func snapshot() -> (starts: Int, running: Bool) {
        lock.lock(); defer { lock.unlock() }
        return (starts, running)
    }
}
