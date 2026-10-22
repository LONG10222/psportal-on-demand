// SPDX-License-Identifier: GPL-3.0-only
import XCTest
@testable import PSPortalHost

final class ApplicationUpdateInfoTests: XCTestCase {
    func testReleasesDestinationIsFixedHTTPSWithoutUserData() {
        let url = ApplicationUpdateInfo.releasesURL
        XCTAssertEqual(url.scheme, "https")
        XCTAssertEqual(url.host, "github.com")
        XCTAssertEqual(url.path, "/LONG10222/psportal-on-demand/releases")
        XCTAssertNil(url.query)
        XCTAssertNil(url.fragment)
        XCTAssertNil(url.user)
        XCTAssertNil(url.password)
    }

    func testInstalledVersionDoesNotGuessCurrentOrLatestVersion() {
        XCTAssertEqual(ApplicationUpdateInfo.displayVersion(version: "0.1.0", build: "1"), "0.1.0 (1)")
        XCTAssertEqual(ApplicationUpdateInfo.displayVersion(version: " 0.2.0 \n", build: " 2 "), "0.2.0 (2)")
        XCTAssertEqual(ApplicationUpdateInfo.displayVersion(version: "0.1.0", build: nil), "0.1.0")
        XCTAssertEqual(ApplicationUpdateInfo.displayVersion(version: nil, build: nil), "—")
        XCTAssertEqual(ApplicationUpdateInfo.displayVersion(version: " ", build: " "), "—")
        XCTAssertEqual(ApplicationUpdateInfo.displayVersion(version: nil, build: "3"), "— (3)")
    }
}
