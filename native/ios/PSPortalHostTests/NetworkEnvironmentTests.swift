// SPDX-License-Identifier: GPL-3.0-only
import XCTest
@testable import PSPortalHost

final class NetworkEnvironmentTests: XCTestCase {
    func testCellularNeverImpliesOwnHotspot() {
        let wifi = LANInterface(name: "en0", address: "192.168.3.2", mask: "255.255.255.0")
        let bridge = LANInterface(name: "bridge100", address: "172.20.10.1", mask: "255.255.255.240")
        let cellular = NetworkSnapshot(uplink: .cellular, interfaces: [wifi, bridge])
        XCTAssertNil(cellular.shareableLAN(confirmOwnHotspot: false))
        XCTAssertEqual(cellular.shareableLAN(confirmOwnHotspot: true), bridge)
        XCTAssertNil(NetworkSnapshot(uplink: .cellular, interfaces: [wifi]).shareableLAN(confirmOwnHotspot: true))
        XCTAssertEqual(NetworkSnapshot(uplink: .wifi, interfaces: [wifi, bridge]).shareableLAN(confirmOwnHotspot: false), wifi)
    }

    func testAllowlistUsesActualSubnetAndExcludesOwnAddress() {
        let bridge = LANInterface(name: "bridge0", address: "172.20.10.1", mask: "255.255.255.240")
        XCTAssertEqual(bridge.clients?.count, 13)
        XCTAssertFalse(bridge.clients?.contains("172.20.10.1") ?? true)
        XCTAssertTrue(bridge.clients?.contains("172.20.10.14") ?? false)
        XCTAssertNil(LANInterface(name: "en0", address: "10.0.0.1", mask: "255.0.0.0").clients)
    }

    func testAmbiguousPhysicalInterfacesAndHotspotsAreNotGuessed() {
        let wifi = LANInterface(name: "en0", address: "192.168.3.2", mask: "255.255.255.0")
        let wired = LANInterface(name: "en5", address: "10.0.1.2", mask: "255.255.255.0")
        for uplink in [Uplink.wifi, .wired] {
            XCTAssertNil(NetworkSnapshot(uplink: uplink, interfaces: [wifi, wired]).shareableLAN(confirmOwnHotspot: false))
            XCTAssertNil(NetworkSnapshot(uplink: uplink, interfaces: [wired, wifi]).shareableLAN(confirmOwnHotspot: false))
        }
        let bridges = [LANInterface(name: "bridge0", address: "172.20.10.1", mask: "255.255.255.240"),
                       LANInterface(name: "bridge1", address: "192.168.2.1", mask: "255.255.255.0")]
        XCTAssertNil(NetworkSnapshot(uplink: .cellular, interfaces: bridges).shareableLAN(confirmOwnHotspot: true))
    }

    func testMissingSubscriptionValuesAreUnknownAndOveruseClampsToZero() throws {
        let missing = try JSONDecoder().decode(SubscriptionAccounting.self, from: Data("{}".utf8))
        XCTAssertNil(missing.used)
        XCTAssertNil(missing.remaining)
        let over = try JSONDecoder().decode(SubscriptionAccounting.self, from: Data("{\"upload\":50,\"download\":100,\"total\":100}".utf8))
        XCTAssertEqual(over.remaining, 0)
    }
}
