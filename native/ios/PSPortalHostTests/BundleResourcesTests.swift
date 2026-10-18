// SPDX-License-Identifier: GPL-3.0-only
import XCTest

final class BundleResourcesTests: XCTestCase {
    func testRequiredReasonManifestAndLicenseResourcesAreBundled() throws {
        let url = try XCTUnwrap(Bundle.main.url(forResource: "PrivacyInfo", withExtension: "xcprivacy"))
        let data = try Data(contentsOf: url)
        let manifest = try XCTUnwrap(PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any])
        let entries = try XCTUnwrap(manifest["NSPrivacyAccessedAPITypes"] as? [[String: Any]])
        var reasons: [String: [String]] = [:]
        for entry in entries {
            let category = try XCTUnwrap(entry["NSPrivacyAccessedAPIType"] as? String)
            XCTAssertNil(reasons[category], "Duplicate privacy category")
            reasons[category] = try XCTUnwrap(entry["NSPrivacyAccessedAPITypeReasons"] as? [String])
        }
        XCTAssertEqual(reasons, [
            "NSPrivacyAccessedAPICategoryFileTimestamp": ["C617.1"],
            "NSPrivacyAccessedAPICategorySystemBootTime": ["35F9.1"]
        ])
        for notice in ["GPL-3.0", "PROJECT-MIT", "THIRD-PARTY-NOTICES", "ENGINE-NOTICES"] {
            let resource = try XCTUnwrap(Bundle.main.url(forResource: notice, withExtension: "txt"))
            XCTAssertGreaterThan(try Data(contentsOf: resource).count, 100)
        }
    }
}
