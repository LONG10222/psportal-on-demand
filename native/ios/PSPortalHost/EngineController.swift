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

/// Lifecycle calls are serialized off the UI thread. A Stop requested during Start is
/// guaranteed to execute after that Start, so a late callback cannot reopen it.
final class EngineController {
    private let queue = DispatchQueue(label: "org.psportal.host.engine", qos: .userInitiated)
    private let driver: EngineDriver
    private let infoQueue: DispatchQueue
    private let nodeQueue: DispatchQueue
    private let sessionLock = NSLock()
    private var sessionGeneration = 0
    private var sessionOpen = false

    init(driver: EngineDriver = EmbeddedEngineDriver(),
         infoQueue: DispatchQueue = DispatchQueue(label: "org.psportal.host.subscription-info", qos: .utility),
         nodeQueue: DispatchQueue = DispatchQueue(label: "org.psportal.host.nodes", qos: .userInitiated)) {
        self.driver = driver
        self.infoQueue = infoQueue
        self.nodeQueue = nodeQueue
    }

    private func replaceSession(open: Bool) -> Int {
        sessionLock.lock(); defer { sessionLock.unlock() }
        sessionGeneration += 1
        sessionOpen = open
        return sessionGeneration
    }

    private func currentSession() -> Int? {
        sessionLock.lock(); defer { sessionLock.unlock() }
        return sessionOpen ? sessionGeneration : nil
    }

    private func completeStart(_ token: Int, succeeded: Bool) {
        sessionLock.lock(); defer { sessionLock.unlock() }
        if sessionGeneration == token { sessionOpen = succeeded }
    }

    func nodeCommand(action: String, name: String, completion: @escaping @MainActor (Bool) -> Void) {
        guard let token = currentSession(),
              let data = try? JSONSerialization.data(withJSONObject: ["action": action, "name": name]),
              let command = String(data: data, encoding: .utf8) else {
            DispatchQueue.main.async { completion(false) }
            return
        }
        nodeQueue.async {
            guard self.currentSession() == token else {
                DispatchQueue.main.async { completion(false) }
                return
            }
            let raw = self.driver.nodeCommand(command)
            let result = raw.data(using: .utf8).flatMap { try? JSONDecoder().decode(NodeResult.self, from: $0) }
            DispatchQueue.main.async { completion(self.currentSession() == token && result?.ok == true) }
        }
    }

    func subscriptionInfo(url: String, completion: @escaping @MainActor (SubscriptionAccounting?) -> Void) {
        guard let token = currentSession() else {
            DispatchQueue.main.async { completion(nil) }
            return
        }
        infoQueue.async {
            guard self.currentSession() == token else {
                DispatchQueue.main.async { completion(nil) }
                return
            }
            let raw = self.driver.subscriptionInfo(url: url)
            let decoded = raw.data(using: .utf8).flatMap { try? JSONDecoder().decode(SubscriptionAccounting.self, from: $0) }
            let info = decoded.flatMap { $0.hasValues ? $0 : nil }
            DispatchQueue.main.async { completion(self.currentSession() == token ? info : nil) }
        }
    }

    func start(json: String, completion: @escaping @MainActor (String?) -> Void) {
        let token = replaceSession(open: false)
        queue.async {
            let failure = self.driver.start(configJSON: json)
            self.completeStart(token, succeeded: failure == nil)
            DispatchQueue.main.async { completion(failure) }
        }
    }

    func stop(completion: @escaping @MainActor () -> Void) {
        _ = replaceSession(open: false)
        queue.async {
            self.driver.stop()
            // Native Stop cancels in-flight node work first. Drain commands that
            // crossed the session check before Stop, so none can resolve the
            // mobile bridge's global engine after a subsequent Start.
            self.nodeQueue.sync {}
            // Mobile accounting uses the same cancellable engine session. Join
            // it after cancellation and discard any queued old subscription URL.
            self.infoQueue.sync {}
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
    var hasValues: Bool { upload != nil || download != nil || total != nil || expire != nil }
    var used: UInt64? {
        guard let upload, let download, upload <= UInt64.max-download else { return nil }
        return upload+download
    }
    var remaining: UInt64? {
        guard let total, total>0, let used else { return nil }
        return used>=total ? 0 : total-used
    }
}
