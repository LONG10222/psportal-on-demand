// SPDX-License-Identifier: GPL-3.0-only
import Foundation
import Network
import Combine
import Darwin

struct LANInterface: Equatable {
    let name: String
    let address: String
    let mask: String

    var clients: [String]? {
        guard let host = Self.number(address), let mask = Self.number(mask) else { return nil }
        let prefix = mask.nonzeroBitCount
        guard (24...30).contains(prefix), mask == UInt32.max << (32-prefix) else { return nil }
        let network = host & mask
        return (1..<(Int(UInt32.max ^ mask))).compactMap { offset in
            let value = network + UInt32(offset)
            return value == host ? nil : Self.string(value)
        }
    }

    private static func number(_ value: String) -> UInt32? {
        let parts = value.split(separator: ".")
        guard parts.count == 4 else { return nil }
        var result: UInt32 = 0
        for part in parts {
            guard let byte = UInt8(part) else { return nil }
            result = (result << 8) | UInt32(byte)
        }
        return result
    }

    private static func string(_ value: UInt32) -> String {
        [24, 16, 8, 0].map { String((value >> $0) & 255) }.joined(separator: ".")
    }
}

enum Uplink: String { case wifi, wired, cellular, unavailable, unknown }

struct NetworkSnapshot: Equatable {
    var uplink = Uplink.unknown
    var interfaces: [LANInterface] = []

    func shareableLAN(confirmOwnHotspot: Bool) -> LANInterface? {
        let prefix: String
        if uplink == .wifi || uplink == .wired {
            prefix = "en"
        } else if uplink == .cellular && confirmOwnHotspot {
            // A cellular uplink alone never proves Personal Hotspot is on.
            prefix = "bridge"
        } else {
            return nil
        }
        let candidates = interfaces.filter { $0.name.hasPrefix(prefix) }
        // Interface enumeration order does not identify the active route.
        // Multiple physical interfaces/aliases require explicit manual setup.
        return candidates.count == 1 ? candidates.first : nil
    }
}

@MainActor
final class NetworkEnvironment: ObservableObject {
    @Published private(set) var snapshot = NetworkSnapshot()
    private let monitor = NWPathMonitor()
    private let queue = DispatchQueue(label: "org.psportal.network-observer")

    init(initialSnapshot: NetworkSnapshot = NetworkSnapshot(), monitorsChanges: Bool = true) {
        snapshot = initialSnapshot
        guard monitorsChanges else { return }
        monitor.pathUpdateHandler = { [weak self] path in
            let kind: Uplink = path.status != .satisfied ? .unavailable :
                path.usesInterfaceType(.wifi) ? .wifi :
                path.usesInterfaceType(.wiredEthernet) ? .wired :
                path.usesInterfaceType(.cellular) ? .cellular : .unknown
            let next = NetworkSnapshot(uplink: kind, interfaces: Self.readInterfaces())
            DispatchQueue.main.async { [weak self] in self?.updateSnapshot(next) }
        }
        monitor.start(queue: queue)
    }

    deinit { monitor.cancel() }

    func updateSnapshot(_ next: NetworkSnapshot) { snapshot = next }

    nonisolated private static func readInterfaces() -> [LANInterface] {
        var head: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&head) == 0, let first = head else { return [] }
        defer { freeifaddrs(head) }
        var result: [LANInterface] = []
        var next: UnsafeMutablePointer<ifaddrs>? = first
        while let current = next {
            defer { next = current.pointee.ifa_next }
            let item = current.pointee
            guard let address = item.ifa_addr, let mask = item.ifa_netmask,
                  address.pointee.sa_family == UInt8(AF_INET),
                  item.ifa_flags & UInt32(IFF_UP | IFF_RUNNING) == UInt32(IFF_UP | IFF_RUNNING),
                  item.ifa_flags & UInt32(IFF_LOOPBACK | IFF_POINTOPOINT) == 0 else { continue }
            let name = String(cString: item.ifa_name)
            guard name.hasPrefix("en") || name.hasPrefix("bridge") else { continue }
            func numeric(_ value: UnsafeMutablePointer<sockaddr>) -> String? {
                var buffer = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
                var ipv4 = value.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { $0.pointee.sin_addr }
                guard inet_ntop(AF_INET, &ipv4, &buffer, socklen_t(buffer.count)) != nil else { return nil }
                return String(cString: buffer)
            }
            guard let host = numeric(address), let netmask = numeric(mask), ProxySettings.isPrivateIPv4(host) else { continue }
            result.append(LANInterface(name: name, address: host, mask: netmask))
        }
        return result.sorted { $0.name < $1.name }
    }

    nonisolated static func availablePort(host: String, preferred: Int = 10081) -> Int? {
        for port in [preferred] + Array(10081...10112) {
            guard (1024...65535).contains(port), port != 10082, port != 10090 else { continue }
            let fd = socket(AF_INET, SOCK_STREAM, 0)
            guard fd >= 0 else { return nil }
            var address = sockaddr_in()
            address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
            address.sin_family = sa_family_t(AF_INET)
            address.sin_port = UInt16(port).bigEndian
            guard inet_pton(AF_INET, host, &address.sin_addr) == 1 else { close(fd); return nil }
            let outcome = withUnsafePointer(to: &address) { pointer in
                pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    Darwin.bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                }
            }
            close(fd)
            if outcome == 0 { return port }
        }
        return nil
    }
}
