// SPDX-License-Identifier: GPL-3.0-only
import Foundation

/// Read-only update information, not a network updater or installer.
enum ApplicationUpdateInfo {
    // Fixed project destination: no subscription, device or configuration data in this URL.
    static let releasesURL = URL(string: "https://github.com/LONG10222/psportal-on-demand/releases")!

    static func installedVersion(bundle: Bundle = .main) -> String {
        displayVersion(version: bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String,
                       build: bundle.object(forInfoDictionaryKey: "CFBundleVersion") as? String)
    }

    static func displayVersion(version: String?, build: String?) -> String {
        let version = version?.trimmingCharacters(in: .whitespacesAndNewlines)
        let build = build?.trimmingCharacters(in: .whitespacesAndNewlines)
        let label = version.flatMap { $0.isEmpty ? nil : $0 } ?? "—"
        guard let build, !build.isEmpty else { return label }
        return "\(label) (\(build))"
    }
}
