// SPDX-License-Identifier: GPL-3.0-only
import Foundation

protocol EngineDriver {
    func start(configJSON: String) -> String?
    func stop()
    func statusJSON() -> String
}

final class EmbeddedEngineDriver: EngineDriver {
    func start(configJSON: String) -> String? { PSPortalEngineBridge.start(configJSON: configJSON) }
    func stop() { PSPortalEngineBridge.stop() }
    func statusJSON() -> String { PSPortalEngineBridge.statusJSON() }
}

/// Calls are serialized off the UI thread. A Stop requested during Start is
/// guaranteed to execute after that Start, so a late callback cannot reopen it.
final class EngineController {
    private let queue = DispatchQueue(label: "org.psportal.host.engine", qos: .userInitiated)
    private let driver: EngineDriver
    init(driver: EngineDriver = EmbeddedEngineDriver()) { self.driver = driver }

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
