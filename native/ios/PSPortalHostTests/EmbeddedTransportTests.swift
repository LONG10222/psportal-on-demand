// SPDX-License-Identifier: GPL-3.0-only
import XCTest
import Darwin
@testable import PSPortalHost

/// These tests invoke the shipped Objective-C/gomobile bridge and real TCP
/// sockets. No RecordingDriver, injected dialer, fake engine or policy override.
/// Existing RFC1918 addresses are used for direct fixtures because production
/// policy intentionally rejects loopback destinations. No interface is added.
final class EmbeddedTransportTests: XCTestCase {
    func testRealFrameworkHTTPAndCONNECTDirectTraffic() throws {
        let lan = try privateInterfaceAddress()
        let engine = EmbeddedEngineDriver()
        engine.stop()
        defer { engine.stop() }
        let port = try unusedPort(host: "127.0.0.1")
        XCTAssertNil(engine.start(configJSON: try configuration(host: "127.0.0.1", port: port, clients: ["127.0.0.1"])))
        XCTAssertEqual(try status(engine)["running"] as? Bool, true)

        let http = try FixtureServer(host: lan) { connection in
            let header = try connection.readHeader()
            try connection.write("HTTP/1.1 200 OK\r\nContent-Length: 15\r\nConnection: close\r\n\r\nios-native-http")
            return header
        }
        defer { http.close() }
        let client = try TCPSocket.connect(host: "127.0.0.1", port: port)
        defer { client.close() }
        try client.write("GET http://\(lan):\(http.port)/fixture?native=1 HTTP/1.1\r\nHost: \(lan):\(http.port)\r\nProxy-Authorization: fixture-only\r\nX-Fixture: yes\r\n\r\n")
        let response = try client.readToEOF()
        XCTAssertTrue(response.hasPrefix("HTTP/1.1 200"))
        XCTAssertTrue(response.hasSuffix("ios-native-http"))
        let forwarded = try http.result()
        XCTAssertTrue(forwarded.hasPrefix("GET /fixture?native=1 HTTP/1.1\r\n"))
        XCTAssertFalse(forwarded.contains("fixture-only"))
        XCTAssertTrue(forwarded.contains("X-Fixture: yes"))

        let echo = try FixtureServer(host: lan) { connection in
            let payload = try connection.readToEOF()
            try connection.write("echo:" + payload)
            return payload
        }
        defer { echo.close() }
        let tunnel = try TCPSocket.connect(host: "127.0.0.1", port: port)
        defer { tunnel.close() }
        try tunnel.write("CONNECT \(lan):\(echo.port) HTTP/1.1\r\nHost: \(lan):\(echo.port)\r\n\r\n")
        XCTAssertTrue(try tunnel.readHeader().hasPrefix("HTTP/1.1 200"))
        try tunnel.write("ios-native-tunnel")
        try tunnel.finishWriting()
        XCTAssertEqual(try tunnel.readToEOF(), "echo:ios-native-tunnel")
        XCTAssertEqual(try echo.result(), "ios-native-tunnel")
        // Direct fixtures must not fetch the intentionally unused subscription.
        XCTAssertEqual(try status(engine)["state"] as? String, "stopped")
    }

    func testRealFrameworkStopClosesOpenSocketAndCanRestart() throws {
        let engine = EmbeddedEngineDriver()
        engine.stop()
        defer { engine.stop() }
        let port = try unusedPort(host: "127.0.0.1")
        let config = try configuration(host: "127.0.0.1", port: port, clients: ["127.0.0.1"])
        XCTAssertNil(engine.start(configJSON: config))
        let waiting = try TCPSocket.connect(host: "127.0.0.1", port: port)
        defer { waiting.close() }
        try waiting.write("GET ") // Deliberately incomplete request owned by engine.
        var accepted = false
        for _ in 0..<100 {
            let stats = try status(engine)["stats"] as? [String: Any]
            if (stats?["active"] as? Int ?? 0) > 0 { accepted = true; break }
            Thread.sleep(forTimeInterval: 0.02)
        }
        XCTAssertTrue(accepted, "Real listener never accepted the test connection")
        let liveStats = try status(engine)["stats"] as? [String: Any]
        XCTAssertEqual(liveStats?["active_devices"] as? Int, 1)
        let devices = liveStats?["devices"] as? [[String: Any]]
        XCTAssertEqual(devices?.first?["ip"] as? String, "127.0.0.1")
        // Exercise the newly generated ABI without fetching any subscription.
        XCTAssertTrue(engine.nodeCommand("{\"action\":\"invalid\"}").contains("invalid"))
        engine.stop()
        XCTAssertTrue(waiting.isClosedByPeer(), "Stop must close the owned socket, not merely time it out")
        XCTAssertEqual(try status(engine)["running"] as? Bool, false)
        XCTAssertThrowsError(try TCPSocket.connect(host: "127.0.0.1", port: port))
        XCTAssertNil(engine.start(configJSON: config))
        let denied = try TCPSocket.connect(host: "127.0.0.1", port: port)
        defer { denied.close() }
        try denied.write("CONNECT 127.0.0.1:9 HTTP/1.1\r\nHost: 127.0.0.1:9\r\n\r\n")
        XCTAssertTrue(try denied.readToEOF().hasPrefix("HTTP/1.1 403"), "Production loopback destination denial must remain active")
    }

    func testRealFrameworkRejectsNonAllowlistedPeer() throws {
        let lan = try privateInterfaceAddress()
        let engine = EmbeddedEngineDriver()
        engine.stop()
        defer { engine.stop() }
        let port = try unusedPort(host: lan)
        let other = lan == "192.168.254.253" ? "192.168.254.252" : "192.168.254.253"
        XCTAssertNil(engine.start(configJSON: try configuration(host: lan, port: port, clients: [other])))
        let client = try TCPSocket.connect(host: lan, port: port)
        defer { client.close() }
        XCTAssertTrue(try client.readToEOF().hasPrefix("HTTP/1.1 403"))
        let stats = try status(engine)["stats"] as? [String: Any]
        XCTAssertEqual(stats?["denied_clients"] as? Int, 1)
        XCTAssertEqual(stats?["active_devices"] as? Int, 0)
        XCTAssertEqual(stats?["accepted"] as? Int ?? 0, 0)
    }

    private func status(_ engine: EmbeddedEngineDriver) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: Data(engine.statusJSON().utf8)) as? [String: Any])
    }

    private func configuration(host: String, port: UInt16, clients: [String]) throws -> String {
        let data = try JSONSerialization.data(withJSONObject: [
            "listen_host": host, "listen_port": Int(port), "allowed_clients": clients,
            "subscription_url": "https://example.com/unused-native-fixture",
            "selection_mode": "auto", "request_timeout": 10
        ])
        return try XCTUnwrap(String(data: data, encoding: .utf8))
    }

    private func unusedPort(host: String) throws -> UInt16 {
        for _ in 0..<20 {
            let reservation = try TCPSocket.listen(host: host)
            let port = try reservation.localPort()
            reservation.close()
            if port >= 1024 && port != 10082 && port != 10090 { return port }
        }
        throw FixtureError.detail("Could not reserve a non-reserved ephemeral TCP port")
    }

    private func privateInterfaceAddress() throws -> String {
        var first: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&first) == 0, let initial = first else { throw FixtureError.socket("getifaddrs", errno) }
        defer { freeifaddrs(initial) }
        var current: UnsafeMutablePointer<ifaddrs>? = initial
        while let entry = current {
            defer { current = entry.pointee.ifa_next }
            guard let address = entry.pointee.ifa_addr, Int32(address.pointee.sa_family) == AF_INET,
                  entry.pointee.ifa_flags & UInt32(IFF_UP) != 0 else { continue }
            var text = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            guard getnameinfo(address, socklen_t(address.pointee.sa_len), &text, socklen_t(text.count), nil, 0, NI_NUMERICHOST) == 0 else { continue }
            let host = String(cString: text)
            if ProxySettings.isPrivateIPv4(host) { return host }
        }
        throw FixtureError.detail("No existing RFC1918 interface for real direct-route fixtures. No network settings were changed.")
    }
}

private enum FixtureError: Error {
    case socket(String, Int32)
    case detail(String)
}

private final class TCPSocket {
    private var descriptor: Int32
    init(descriptor: Int32) throws {
        self.descriptor = descriptor
        guard descriptor >= 0 else { throw FixtureError.socket("socket", errno) }
        var noSignal: Int32 = 1
        var timeout = timeval(tv_sec: 5, tv_usec: 0)
        guard setsockopt(descriptor, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, socklen_t(MemoryLayout.size(ofValue: noSignal))) == 0,
              setsockopt(descriptor, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout.size(ofValue: timeout))) == 0,
              setsockopt(descriptor, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout.size(ofValue: timeout))) == 0 else {
            let failure = errno; close(); throw FixtureError.socket("setsockopt", failure)
        }
    }
    deinit { close() }
    func close() { if descriptor >= 0 { Darwin.close(descriptor); descriptor = -1 } }

    private static func makeAddress(_ host: String, _ port: UInt16) throws -> sockaddr_in {
        var result = sockaddr_in()
        result.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        result.sin_family = sa_family_t(AF_INET)
        result.sin_port = port.bigEndian
        guard inet_pton(AF_INET, host, &result.sin_addr) == 1 else { throw FixtureError.detail("Invalid numeric fixture address") }
        return result
    }
    static func listen(host: String) throws -> TCPSocket {
        let result = try TCPSocket(descriptor: Darwin.socket(AF_INET, SOCK_STREAM, 0))
        var address = try makeAddress(host, 0)
        let bound = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.bind(result.descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
        }
        guard bound == 0, Darwin.listen(result.descriptor, 4) == 0 else { throw FixtureError.socket("bind/listen", errno) }
        return result
    }
    static func connect(host: String, port: UInt16) throws -> TCPSocket {
        let result = try TCPSocket(descriptor: Darwin.socket(AF_INET, SOCK_STREAM, 0))
        var address = try makeAddress(host, port)
        let connected = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.connect(result.descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
        }
        guard connected == 0 else { throw FixtureError.socket("connect", errno) }
        return result
    }
    func localPort() throws -> UInt16 {
        var address = sockaddr_in()
        var length = socklen_t(MemoryLayout<sockaddr_in>.size)
        let result = withUnsafeMutablePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(descriptor, $0, &length) }
        }
        guard result == 0 else { throw FixtureError.socket("getsockname", errno) }
        return UInt16(bigEndian: address.sin_port)
    }
    func accept() throws -> TCPSocket {
        var readiness = pollfd(fd: descriptor, events: Int16(POLLIN), revents: 0)
        guard Darwin.poll(&readiness, 1, 10_000) > 0 else { throw FixtureError.detail("Fixture accept deadline expired") }
        return try TCPSocket(descriptor: Darwin.accept(descriptor, nil, nil))
    }
    func write(_ text: String) throws {
        let bytes = Array(text.utf8)
        try bytes.withUnsafeBytes { buffer in
            var sent = 0
            while sent < buffer.count {
                let count = Darwin.send(descriptor, buffer.baseAddress!.advanced(by: sent), buffer.count - sent, 0)
                guard count > 0 else { throw FixtureError.socket("send", errno) }
                sent += count
            }
        }
    }
    func finishWriting() throws {
        guard Darwin.shutdown(descriptor, SHUT_WR) == 0 else { throw FixtureError.socket("shutdown", errno) }
    }
    func readHeader() throws -> String {
        var bytes: [UInt8] = []
        while bytes.count <= 65_536 {
            var byte: UInt8 = 0
            let count = Darwin.recv(descriptor, &byte, 1, 0)
            guard count == 1 else { throw FixtureError.socket("receive header", count == 0 ? 0 : errno) }
            bytes.append(byte)
            if bytes.suffix(4).elementsEqual([13, 10, 13, 10]) { return String(decoding: bytes, as: UTF8.self) }
        }
        throw FixtureError.detail("Fixture header too large")
    }
    func readToEOF() throws -> String {
        var bytes: [UInt8] = []
        var buffer = [UInt8](repeating: 0, count: 4096)
        while bytes.count <= 65_536 {
            let count = Darwin.recv(descriptor, &buffer, buffer.count, 0)
            if count == 0 { return String(decoding: bytes, as: UTF8.self) }
            guard count > 0 else { throw FixtureError.socket("receive", errno) }
            bytes.append(contentsOf: buffer.prefix(count))
        }
        throw FixtureError.detail("Fixture response too large")
    }
    func isClosedByPeer() -> Bool {
        var byte: UInt8 = 0
        let count = Darwin.recv(descriptor, &byte, 1, 0)
        return count == 0 || (count < 0 && (errno == ECONNRESET || errno == ENOTCONN))
    }
}

private final class FixtureServer {
    private let listener: TCPSocket
    let port: UInt16
    private let finished = DispatchGroup()
    private let lock = NSLock()
    private var outcome: Result<String, Error>?

    init(host: String, handler: @escaping (TCPSocket) throws -> String) throws {
        listener = try TCPSocket.listen(host: host)
        port = try listener.localPort()
        finished.enter()
        DispatchQueue.global(qos: .userInitiated).async { [self] in
            let result = Result {
                let connection = try listener.accept()
                defer { connection.close() }
                return try handler(connection)
            }
            lock.lock(); outcome = result; lock.unlock()
            finished.leave()
        }
    }
    func close() {
        // Never close/reuse the listener descriptor while its worker is polling.
        // On timeout the worker retains self and deinitializes after its deadline.
        if finished.wait(timeout: .now() + 12) == .success { listener.close() }
    }
    func result() throws -> String {
        guard finished.wait(timeout: .now() + 12) == .success else { throw FixtureError.detail("Fixture completion deadline expired") }
        lock.lock(); defer { lock.unlock() }
        return try XCTUnwrap(outcome).get()
    }
}
