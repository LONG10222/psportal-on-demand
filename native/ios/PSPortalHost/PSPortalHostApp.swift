// SPDX-License-Identifier: GPL-3.0-only
import SwiftUI
import UIKit

@main
@MainActor
struct PSPortalHostApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var model = ProxyModel()

    var body: some Scene {
        WindowGroup {
            ContentView(model: model)
                .onAppear { model.scenePhaseChanged(scenePhase) }
                .onChange(of: scenePhase) { model.scenePhaseChanged($0) }
                .onReceive(NotificationCenter.default.publisher(for: UIApplication.didEnterBackgroundNotification)) { _ in
                    model.didEnterBackground()
                }
                .onReceive(NotificationCenter.default.publisher(for: UIApplication.protectedDataWillBecomeUnavailableNotification)) { _ in
                    model.protectedDataUnavailable()
                }
        }
    }
}

