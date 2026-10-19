// SPDX-License-Identifier: GPL-3.0-only
import XCTest
@testable import PSPortalHost

/// Queue gates make stale operations deterministic without real network access.
final class EngineControllerTests: XCTestCase {
    @MainActor
    func testUnavailableOrEmptyAccountingIsNotAUsableSnapshot() async {
        let driver = ControllerDriver()
        let controller = EngineController(driver: driver)
        await start(controller)
        for response in ["{\"available\":false}", "{}"] {
            driver.infoResponse = response
            let fetched = expectation(description: "Unavailable accounting remains unknown")
            controller.subscriptionInfo(url: "https://example.com/sub") { info in
                XCTAssertNil(info)
                fetched.fulfill()
            }
            await fulfillment(of: [fetched], timeout: 2)
        }
        await stop(controller)
    }

    @MainActor
    func testQueuedNodeCommandCannotReachRestartedEngine() async {
        let nodeQueue = DispatchQueue(label: "test.stale-nodes")
        nodeQueue.suspend()
        var suspended = true
        defer { if suspended { nodeQueue.resume() } }
        let driver = ControllerDriver()
        let controller = EngineController(driver: driver, nodeQueue: nodeQueue)
        await start(controller)

        let stale = expectation(description: "Old command is rejected")
        controller.nodeCommand(action: "select", name: "Old session node") { success in
            XCTAssertFalse(success)
            stale.fulfill()
        }
        let stopEntered = expectation(description: "Native Stop starts before queue drains")
        driver.onStop = { stopEntered.fulfill() }
        let stopped = expectation(description: "Stop completes")
        controller.stop { stopped.fulfill() }
        await fulfillment(of: [stopEntered], timeout: 2)
        let restarted = expectation(description: "Next Start completes")
        controller.start(json: "{}") { failure in
            XCTAssertNil(failure)
            restarted.fulfill()
        }
        nodeQueue.resume()
        suspended = false
        await fulfillment(of: [stale, stopped, restarted], timeout: 2)
        XCTAssertTrue(driver.snapshot().commands.isEmpty)
        XCTAssertEqual(driver.snapshot().starts, 2)
        driver.onStop = nil
        await stop(controller)
    }

    @MainActor
    func testStopCancelsThenJoinsAlreadyEnteredNodeCommand() async {
        let driver = ControllerDriver()
        let controller = EngineController(driver: driver)
        await start(controller)
        let nodeEntered = expectation(description: "Node command reaches native boundary")
        let releaseNode = DispatchSemaphore(value: 0)
        defer { releaseNode.signal() }
        driver.beforeNode = {
            nodeEntered.fulfill()
            _ = releaseNode.wait(timeout: .now() + 5)
        }
        let nodeFinished = expectation(description: "Stale node completion is rejected")
        controller.nodeCommand(action: "fastest", name: "") { success in
            XCTAssertFalse(success)
            nodeFinished.fulfill()
        }
        await fulfillment(of: [nodeEntered], timeout: 2)

        let stopEntered = expectation(description: "Stop is not blocked behind node work")
        driver.onStop = { stopEntered.fulfill() }
        let earlyStop = expectation(description: "Stop cannot finish before node exits")
        earlyStop.isInverted = true
        let stopped = expectation(description: "Stop finishes after node exits")
        controller.stop {
            if !driver.snapshot().nodeExited { earlyStop.fulfill() }
            stopped.fulfill()
        }
        await fulfillment(of: [stopEntered], timeout: 2)
        // The semaphore keeps the unsafe native-call window open throughout
        // this negative assertion; no assumed operation duration or sleep.
        await fulfillment(of: [earlyStop], timeout: 0.1)
        releaseNode.signal()
        await fulfillment(of: [nodeFinished, stopped], timeout: 2)
        XCTAssertTrue(driver.snapshot().nodeExited)
    }

    @MainActor
    func testQueuedMetadataSkipsStoppedSessionAndUsesNewURL() async {
        let infoQueue = DispatchQueue(label: "test.stale-metadata")
        infoQueue.suspend()
        var suspended = true
        defer { if suspended { infoQueue.resume() } }
        let driver = ControllerDriver()
        let controller = EngineController(driver: driver, infoQueue: infoQueue)
        await start(controller)
        let oldInfo = expectation(description: "Old metadata is discarded")
        controller.subscriptionInfo(url: "https://example.com/old") { info in
            XCTAssertNil(info)
            oldInfo.fulfill()
        }
        let stopEntered = expectation(description: "Stop cancels before joining accounting work")
        driver.onStop = { stopEntered.fulfill() }
        let stopped = expectation(description: "Stop completes after accounting queue drains")
        controller.stop { stopped.fulfill() }
        await fulfillment(of: [stopEntered], timeout: 2)
        let restarted = expectation(description: "New session starts after stale work drains")
        controller.start(json: "{}") { failure in
            XCTAssertNil(failure)
            restarted.fulfill()
        }
        infoQueue.resume()
        suspended = false
        await fulfillment(of: [oldInfo, stopped, restarted], timeout: 2)
        let newInfo = expectation(description: "Current metadata is returned")
        controller.subscriptionInfo(url: "https://example.com/new") { info in
            XCTAssertEqual(info?.total, 100)
            newInfo.fulfill()
        }
        await fulfillment(of: [newInfo], timeout: 2)
        XCTAssertEqual(driver.snapshot().urls, ["https://example.com/new"])
        driver.onStop = nil
        await stop(controller)
    }

    @MainActor
    func testStopCancelsInflightMetadataBeforeNewSession() async {
        let driver = ControllerDriver()
        let controller = EngineController(driver: driver)
        await start(controller)
        let infoEntered = expectation(description: "Old metadata request begins")
        let releaseInfo = DispatchSemaphore(value: 0)
        defer { releaseInfo.signal() }
        driver.beforeInfo = {
            infoEntered.fulfill()
            _ = releaseInfo.wait(timeout: .now() + 5)
        }
        // The real mobile driver cancels the engine context from Stop.
        driver.onStop = { releaseInfo.signal() }
        let discarded = expectation(description: "Late metadata is discarded")
        controller.subscriptionInfo(url: "https://example.com/old") { info in
            XCTAssertNil(info)
            discarded.fulfill()
        }
        await fulfillment(of: [infoEntered], timeout: 2)
        await stop(controller)
        XCTAssertEqual(driver.snapshot().urls, ["https://example.com/old"])
        await start(controller)
        await fulfillment(of: [discarded], timeout: 2)
        driver.onStop = nil
        await stop(controller)
    }

    @MainActor
    func testFailedStartRejectsMetadataAndNodeCommands() async {
        let driver = ControllerDriver()
        driver.startFailure = "Fixture start failure"
        let controller = EngineController(driver: driver)
        let failed = expectation(description: "Start fails")
        controller.start(json: "{}") { failure in
            XCTAssertEqual(failure, "Fixture start failure")
            failed.fulfill()
        }
        await fulfillment(of: [failed], timeout: 2)
        let infoDone = expectation(description: "Metadata is rejected")
        let nodeDone = expectation(description: "Node command is rejected")
        controller.subscriptionInfo(url: "https://example.com/sub") { info in
            XCTAssertNil(info)
            infoDone.fulfill()
        }
        controller.nodeCommand(action: "prepare", name: "") { success in
            XCTAssertFalse(success)
            nodeDone.fulfill()
        }
        await fulfillment(of: [infoDone, nodeDone], timeout: 2)
        XCTAssertTrue(driver.snapshot().urls.isEmpty)
        XCTAssertTrue(driver.snapshot().commands.isEmpty)
    }

    @MainActor
    private func start(_ controller: EngineController) async {
        let started = expectation(description: "Controller starts")
        controller.start(json: "{}") { failure in
            XCTAssertNil(failure)
            started.fulfill()
        }
        await fulfillment(of: [started], timeout: 2)
    }

    @MainActor
    private func stop(_ controller: EngineController) async {
        let stopped = expectation(description: "Controller stops")
        controller.stop { stopped.fulfill() }
        await fulfillment(of: [stopped], timeout: 2)
    }
}

private final class ControllerDriver: EngineDriver {
    private let lock = NSLock()
    private var starts = 0
    private var commands: [String] = []
    private var urls: [String] = []
    private var nodeExited = false
    // Hooks are set before the associated operation is submitted and are not
    // changed while that operation is in flight.
    var onStop: (() -> Void)?
    var beforeNode: (() -> Void)?
    var beforeInfo: (() -> Void)?
    var startFailure: String?
    var infoResponse = "{\"total\":100}"

    func start(configJSON: String) -> String? {
        lock.lock(); defer { lock.unlock() }
        starts += 1
        return startFailure
    }

    func stop() { onStop?() }
    func statusJSON() -> String { "{\"running\":true,\"state\":\"stopped\",\"active\":0}" }

    func nodeCommand(_ command: String) -> String {
        beforeNode?()
        lock.lock(); defer { lock.unlock() }
        commands.append(command)
        nodeExited = true
        return "{\"ok\":true}"
    }

    func subscriptionInfo(url: String) -> String {
        beforeInfo?()
        lock.lock(); defer { lock.unlock() }
        urls.append(url)
        return infoResponse
    }

    func snapshot() -> (starts: Int, commands: [String], urls: [String], nodeExited: Bool) {
        lock.lock(); defer { lock.unlock() }
        return (starts, commands, urls, nodeExited)
    }
}
