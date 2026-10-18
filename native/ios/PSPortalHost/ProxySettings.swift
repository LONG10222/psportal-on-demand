// SPDX-License-Identifier: GPL-3.0-only
import Foundation

enum SelectionMode: String, Codable, CaseIterable, Identifiable {
    case auto, prefer, fixed
    var id: String { rawValue }
    var title: String {
        switch self {
        case .auto: return "Auto: Hong Kong, then Japan"
        case .prefer: return "Prefer one node, with fallback"
        case .fixed: return "Fixed node, no fallback"
        }
    }
}

struct ProxySettings: Codable, Equatable {
    var listenHost = ""
    var listenPort = "10081"
    var allowedClients = ""
    var subscriptionURL = ""
    var selectionMode = SelectionMode.auto
    var preferredNode = ""
    var idleSeconds = 60
    var keepAwake = false

    // Deliberately omit subscriptionURL: it is session memory only. Neither
    // Save nor any future Codable caller can put the subscription token on disk.
    private enum CodingKeys: String, CodingKey {
        case listenHost, listenPort, allowedClients, selectionMode, preferredNode, idleSeconds, keepAwake
    }

    var clientAddresses: [String] {
        allowedClients.split { $0 == "," || $0.isWhitespace }.map(String.init)
    }

    var validationMessage: String? {
        guard Self.isPrivateIPv4(listenHost) else {
            return "Enter this iPhone or iPad's current private Wi-Fi IPv4 address. Wildcard and loopback addresses are not allowed."
        }
        guard let port = Int(listenPort), (1024...65535).contains(port), port != 10082, port != 10090 else {
            return "Use a port from 1024 to 65535, other than the reserved compatibility ports 10082 and 10090."
        }
        let clients = clientAddresses
        guard !clients.isEmpty, clients.count <= 256, clients.allSatisfy(Self.isPrivateIPv4), Set(clients).count == clients.count else {
            return "Enter one or more unique private IPv4 client addresses, separated by commas or new lines."
        }
        guard subscriptionURL.utf8.count <= 8192,
              !subscriptionURL.unicodeScalars.contains(where: { CharacterSet.whitespacesAndNewlines.union(.controlCharacters).contains($0) }),
              let url = URLComponents(string: subscriptionURL), url.scheme == "https",
              let host = url.host, !host.isEmpty, url.user == nil, url.password == nil,
              url.fragment == nil, url.port == nil || url.port == 443 else {
            return "Enter a public HTTPS subscription URL, without a username, password, fragment, or non-443 port."
        }
        if selectionMode != .auto && preferredNode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return "Enter the exact node name for preferred or fixed mode."
        }
        guard (1...86400).contains(idleSeconds) else {
            return "Idle timeout must be between 1 and 86400 seconds."
        }
        // The shared engine remains authoritative for public destinations,
        // reserved names, subscription formats, and all network policy.
        return nil
    }

    func engineJSON(dataDirectory: String) throws -> String {
        guard validationMessage == nil, let port = Int(listenPort) else { throw SettingsError.invalid }
        let object: [String: Any] = [
            "listen_host": listenHost, "listen_port": port,
            "allowed_clients": clientAddresses, "subscription_url": subscriptionURL,
            "selection_mode": selectionMode.rawValue, "preferred_node": preferredNode,
            "backend_port": 10082, "api_port": 10090,
            "idle_seconds": idleSeconds, "wakeup_timeout": 45,
            "request_timeout": 30, "max_connections": 128,
            "health_url": "https://www.gstatic.com/generate_204",
            "health_interval": 300, "health_timeout": 5000,
            "data_dir": dataDirectory
        ]
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        guard let json = String(data: data, encoding: .utf8) else { throw SettingsError.invalid }
        return json
    }

    static func isPrivateIPv4(_ text: String) -> Bool {
        let parts = text.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 4 else { return false }
        var bytes: [Int] = []
        for part in parts {
            guard !part.isEmpty, part.allSatisfy({ $0 >= "0" && $0 <= "9" }),
                  let value = Int(part), (0...255).contains(value), String(value) == part else { return false }
            bytes.append(value)
        }
        return bytes[0] == 10 || (bytes[0] == 172 && (16...31).contains(bytes[1])) || (bytes[0] == 192 && bytes[1] == 168)
    }
}

enum SettingsError: Error { case invalid, unavailable }

