// SPDX-License-Identifier: GPL-3.0-only
import XCTest
@testable import PSPortalHost

final class ProxySettingsTests: XCTestCase {
    func testOnlyCanonicalRFC1918AddressesAreAccepted() {
        for address in ["10.0.0.1", "172.16.0.2", "172.31.255.254", "192.168.1.1"] {
            XCTAssertTrue(ProxySettings.isPrivateIPv4(address), address)
        }
        for address in ["0.0.0.0", "127.0.0.1", "8.8.8.8", "169.254.1.2", "172.32.0.1", "192.168.001.1", "192.168.1.256", "::1", "192.168.1.1 "] {
            XCTAssertFalse(ProxySettings.isPrivateIPv4(address), address)
        }
    }

    func testClientListAndSelectionValidation() {
        var settings = validSettings()
        XCTAssertNil(settings.validationMessage)
        settings.allowedClients = "192.168.1.20,\n192.168.1.21"
        XCTAssertEqual(settings.clientAddresses, ["192.168.1.20", "192.168.1.21"])
        XCTAssertNil(settings.validationMessage)
        settings.allowedClients = "192.168.1.20,192.168.1.20"
        XCTAssertNotNil(settings.validationMessage)
        settings = validSettings()
        settings.selectionMode = .fixed
        XCTAssertNotNil(settings.validationMessage)
        settings.preferredNode = "Tokyo 1"
        XCTAssertNil(settings.validationMessage)
    }

    func testSubscriptionAndPortsFailClosed() {
        for url in ["http://example.com/sub", "https://u:p@example.com/sub", "https://example.com:444/sub", "https://example.com/sub#x", "https://example.com/ has-space"] {
            var settings = validSettings()
            settings.subscriptionURL = url
            XCTAssertNotNil(settings.validationMessage)
        }
        for port in ["80", "0", "65536", "10082", "10090", "port"] {
            var settings = validSettings()
            settings.listenPort = port
            XCTAssertNotNil(settings.validationMessage)
        }
    }

    func testPayloadMatchesSharedGoContractAndExcludesUIPreferences() throws {
        var settings = validSettings()
        settings.keepAwake = true
        let data = try XCTUnwrap(try settings.engineJSON(dataDirectory: "/private/runtime").data(using: .utf8))
        let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(payload["listen_host"] as? String, "192.168.1.10")
        XCTAssertEqual(payload["allowed_clients"] as? [String], ["192.168.1.20"])
        XCTAssertEqual(payload["selection_mode"] as? String, "auto")
        XCTAssertEqual(payload["data_dir"] as? String, "/private/runtime")
        XCTAssertNil(payload["keepAwake"])
        XCTAssertNil(payload["keep_awake"])
        XCTAssertEqual(payload.count, 16)
    }

    func testStatusDoesNotDisplayNativeErrorOrNodeSecrets() throws {
        let raw = #"{"running":true,"state":"error","active":0,"error":"secret-token","selected_node":"private-name"}"#
        let status = try JSONDecoder().decode(EngineStatus.self, from: Data(raw.utf8))
        XCTAssertFalse(status.summary.contains("secret-token"))
        XCTAssertFalse(status.summary.contains("private-name"))
    }
}

func validSettings() -> ProxySettings {
    var settings = ProxySettings()
    settings.listenHost = "192.168.1.10"
    settings.allowedClients = "192.168.1.20"
    settings.subscriptionURL = "https://example.com/subscription?token=fixture-only"
    return settings
}

