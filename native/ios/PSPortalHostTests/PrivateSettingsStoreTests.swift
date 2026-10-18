// SPDX-License-Identifier: GPL-3.0-only
import XCTest
@testable import PSPortalHost

final class PrivateSettingsStoreTests: XCTestCase {
    func testSaveOmitsSubscriptionAndIsExcludedFromBackupThenForgotten() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = PrivateSettingsStore(directory: directory)
        XCTAssertNil(try store.load())
        let settings = validSettings()
        try store.save(settings)
        var expected = settings
        expected.subscriptionURL = ""
        XCTAssertEqual(try store.load(), expected)
        let file = directory.appendingPathComponent("settings.json")
        let savedText = try String(contentsOf: file, encoding: .utf8)
        XCTAssertFalse(savedText.contains("fixture-only"))
        XCTAssertFalse(savedText.contains("subscriptionURL"))
        for url in [directory, file, try store.runtimeDirectory()] {
            XCTAssertEqual(try url.resourceValues(forKeys: [.isExcludedFromBackupKey]).isExcludedFromBackup, true)
        }
        try store.forget()
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.path))
        XCTAssertNil(try store.load())
    }

    func testCompleteDataProtectionOnPhysicalDevice() throws {
        #if targetEnvironment(simulator)
        throw XCTSkip("Simulator cannot establish hardware-backed iOS Data Protection. Verify on a physical device.")
        #else
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = PrivateSettingsStore(directory: directory)
        try store.save(validSettings())
        for url in [directory, directory.appendingPathComponent("settings.json"), try store.runtimeDirectory()] {
            let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
            XCTAssertEqual(attributes[.protectionKey] as? String, FileProtectionType.complete.rawValue)
        }
        #endif
    }
}

