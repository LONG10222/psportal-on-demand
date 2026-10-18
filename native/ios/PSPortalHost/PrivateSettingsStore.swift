// SPDX-License-Identifier: GPL-3.0-only
import Foundation

/// The subscription URL is excluded by ProxySettings.CodingKeys. It never goes
/// to disk, UserDefaults, shared containers, application logs, or Documents.
/// Backup exclusion is established on the directory before any content is written.
final class PrivateSettingsStore {
    private let manager: FileManager
    private let directory: URL
    private var settingsURL: URL { directory.appendingPathComponent("settings.json") }

    init(manager: FileManager = .default, directory: URL? = nil) {
        self.manager = manager
        self.directory = directory ?? manager.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("PSPortalPrivate", isDirectory: true)
    }

    func load() throws -> ProxySettings? {
        guard manager.fileExists(atPath: settingsURL.path) else { return nil }
        try prepareDirectory(directory)
        try protectFile(settingsURL)
        let size = try settingsURL.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? Int.max
        guard size <= 65_536 else { throw SettingsError.invalid }
        return try JSONDecoder().decode(ProxySettings.self, from: Data(contentsOf: settingsURL))
    }

    func save(_ settings: ProxySettings) throws {
        try prepareDirectory(directory)
        let data = try JSONEncoder().encode(settings)
        guard data.count <= 65_536 else { throw SettingsError.invalid }
        try data.write(to: settingsURL, options: [.atomic, .completeFileProtection])
        try protectFile(settingsURL)
    }

    func forget() throws {
        // The model permits this only after Stop completes. Remove any future
        // engine cache along with the saved settings, rather than leaving it behind.
        if manager.fileExists(atPath: directory.path) { try manager.removeItem(at: directory) }
    }

    func runtimeDirectory() throws -> URL {
        try prepareDirectory(directory)
        let runtime = directory.appendingPathComponent("runtime", isDirectory: true)
        try prepareDirectory(runtime)
        return runtime
    }

    private func prepareDirectory(_ original: URL) throws {
        try manager.createDirectory(at: original, withIntermediateDirectories: true,
                                    attributes: [.protectionKey: FileProtectionType.complete, .posixPermissions: 0o700])
        try manager.setAttributes([.protectionKey: FileProtectionType.complete, .posixPermissions: 0o700], ofItemAtPath: original.path)
        var url = original
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try url.setResourceValues(values)
    }

    private func protectFile(_ original: URL) throws {
        try manager.setAttributes([.protectionKey: FileProtectionType.complete, .posixPermissions: 0o600], ofItemAtPath: original.path)
        var url = original
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try url.setResourceValues(values)
    }
}

