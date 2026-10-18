// SPDX-License-Identifier: GPL-3.0-only
import XCTest
@testable import PSPortalHost

final class RuntimePanelTests: XCTestCase {
    @MainActor
    func testPanelsUseListenerConnectionsAndResetAfterStop() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let driver = PanelDriver()
        let model = ProxyModel(engine: EngineController(driver: driver), store: PrivateSettingsStore(directory: directory))
        model.settings = validSettings()
        model.scenePhaseChanged(.active)
        model.start()
        for _ in 0..<100 {
            if model.activeConnections == 3 { break }
            try? await Task.sleep(nanoseconds: 20_000_000)
        }
        // Top-level active is an outbound lease count; it must not mask direct LAN clients.
        XCTAssertEqual(model.activeConnections, 3)
        XCTAssertEqual(model.activeDevices, 1)
        XCTAssertEqual(model.devices.first?.ip, "192.168.1.20")
        XCTAssertEqual(model.nodes.first?.name, "🇭🇰 Demo")
        XCTAssertTrue(model.statusTitle.contains("使用"))
        model.language = "en"
        XCTAssertEqual(model.statusTitle, "Devices connected")
        model.nodeAction("select", name: "🇭🇰 Demo")
        for _ in 0..<100 {
            if !model.nodeBusy { break }
            try? await Task.sleep(nanoseconds: 20_000_000)
        }
        XCTAssertEqual(model.nodeMessage, "done")
        model.stop()
        for _ in 0..<100 {
            if model.state == .stopped { break }
            try? await Task.sleep(nanoseconds: 20_000_000)
        }
        XCTAssertEqual(model.state, .stopped)
        XCTAssertTrue(model.devices.isEmpty)
        XCTAssertTrue(model.nodes.isEmpty)
        XCTAssertEqual(model.activeConnections, 0)
        XCTAssertEqual(model.activeDevices, 0)
    }

    func testLegacyStatusRemainsDecodableAndNoInventedDevices() throws {
        let status = try JSONDecoder().decode(EngineStatus.self, from: Data("{\"running\":true,\"state\":\"stopped\",\"active\":0}".utf8))
        XCTAssertNil(status.stats)
        XCTAssertNil(status.nodes)
    }
}

private final class PanelDriver: EngineDriver {
    func start(configJSON: String) -> String? { nil }
    func stop() {}
    func nodeCommand(_ command: String) -> String {
        guard let data = command.data(using: .utf8),
              let value = try? JSONSerialization.jsonObject(with: data) as? [String: String],
              value["action"] == "select", value["name"] == "🇭🇰 Demo" else { return "{\"ok\":false}" }
        return "{\"ok\":true}"
    }
    func statusJSON() -> String {
        """
        {"running":true,"state":"stopped","active":0,
         "stats":{"active":3,"active_devices":1,"errors":2,"denied_clients":1,
                  "devices":[{"ip":"192.168.1.20","active":3,"accepted":5,"last_seen":1700000000}]},
         "nodes":[{"name":"🇭🇰 Demo","healthy":true,"delay_ms":42,"protocol":"trojan"}],
         "manual_node":"🇭🇰 Demo","auto_fastest":false}
        """
    }
}
