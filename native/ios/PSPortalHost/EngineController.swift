// SPDX-License-Identifier: GPL-3.0-only
import Foundation

protocol EngineDriver {
    func start(configJSON: String) -> String?
    func stop()
    func statusJSON() -> String
    func subscriptionInfo(url: String) -> String
    func nodeCommand(_ command: String) -> String
}

extension EngineDriver {
    func subscriptionInfo(url: String) -> String { "{}" }
    func nodeCommand(_ command: String) -> String { "{\"ok\":false,\"code\":\"unavailable\"}" }
}

final class EmbeddedEngineDriver: EngineDriver {
    func start(configJSON: String) -> String? { PSPortalEngineBridge.start(configJSON: configJSON) }
    func stop() { PSPortalEngineBridge.stop() }
    func statusJSON() -> String { PSPortalEngineBridge.statusJSON() }
    func subscriptionInfo(url: String) -> String { PSPortalEngineBridge.subscriptionInfo(url: url) }
    func nodeCommand(_ command: String) -> String { PSPortalEngineBridge.nodeCommand(command) }
}

/// Calls are serialized off the UI thread. A Stop requested during Start is
/// guaranteed to execute after that Start, so a late callback cannot reopen it.
final class EngineController {
    private let queue = DispatchQueue(label: "org.psportal.host.engine", qos: .userInitiated)
    private let driver: EngineDriver
    private let infoQueue = DispatchQueue(label: "org.psportal.host.subscription-info", qos: .utility)
    private let nodeQueue = DispatchQueue(label: "org.psportal.host.nodes", qos: .userInitiated)
    init(driver: EngineDriver = EmbeddedEngineDriver()) { self.driver = driver }

    func nodeCommand(action: String, name: String, completion: @escaping @MainActor (Bool) -> Void) {
        guard let data = try? JSONSerialization.data(withJSONObject: ["action": action, "name": name]),
              let command = String(data: data, encoding: .utf8) else {
            DispatchQueue.main.async { completion(false) }
            return
        }
        nodeQueue.async {
            let raw = self.driver.nodeCommand(command)
            let result = raw.data(using: .utf8).flatMap { try? JSONDecoder().decode(NodeResult.self, from: $0) }
            DispatchQueue.main.async { completion(result?.ok == true) }
        }
    }

    func subscriptionInfo(url: String, completion: @escaping @MainActor (SubscriptionAccounting?) -> Void) {
        infoQueue.async {
            let raw = self.driver.subscriptionInfo(url: url)
            let info = raw.data(using: .utf8).flatMap { try? JSONDecoder().decode(SubscriptionAccounting.self, from: $0) }
            DispatchQueue.main.async { completion(info) }
        }
    }

    func start(json: String, completion: @escaping @MainActor (String?) -> Void) {
        queue.async {
            let failure = self.driver.start(configJSON: json)
            DispatchQueue.main.async { completion(failure) }
        }
    }

    func stop(completion: @escaping @MainActor () -> Void) {
        queue.async {
            self.driver.stop()
            DispatchQueue.main.async { completion() }
        }
    }

    func status(completion: @escaping @MainActor (EngineStatus?) -> Void) {
        queue.async {
            let raw = self.driver.statusJSON()
            let status = raw.data(using: .utf8).flatMap { try? JSONDecoder().decode(EngineStatus.self, from: $0) }
            DispatchQueue.main.async { completion(status) }
        }
    }
}

struct EngineStatus: Decodable {
    let running: Bool
    let state: String
    let active: Int
    var stats: ListenerStats?
    var nodes: [ProxyNode]?
    var selected_node: String?
    var manual_node: String?
    var auto_fastest: Bool?

    var summary: String {
        guard running else { return "Stopped" }
        switch state {
        case "starting": return "Loading and checking proxy nodes"
        case "running": return "Encrypted outbound pool ready"
        case "error": return "Outbound unavailable; check the subscription and node connectivity"
        case "stopped": return "Listening; outbound pool will wake on demand"
        default: return "Listening; waiting for engine status"
        }
    }
}

struct NodeResult: Decodable { let ok: Bool }
struct ProxyNode: Decodable, Identifiable {
    let name: String
    let healthy: Bool
    let delay_ms: Int?
    let `protocol`: String?
    var id: String { name }
}
struct ConnectedDevice: Decodable, Identifiable {
    let ip: String
    let active: Int
    let accepted: UInt64
    let last_seen: Int64
    var id: String { ip }
}
struct ListenerStats: Decodable {
    let active: Int
    let active_devices: Int?
    let devices: [ConnectedDevice]?
    let errors: UInt64
    let denied_clients: UInt64
}

struct SubscriptionAccounting: Decodable {
    let upload: UInt64?
    let download: UInt64?
    let total: UInt64?
    let expire: UInt64?
    var used: UInt64? {
        guard let upload, let download, upload <= UInt64.max-download else { return nil }
        return upload+download
    }
    var remaining: UInt64? {
        guard let total, total>0, let used else { return nil }
        return used>=total ? 0 : total-used
    }
}
