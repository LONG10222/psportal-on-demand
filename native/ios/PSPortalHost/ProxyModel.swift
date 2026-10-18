// SPDX-License-Identifier: GPL-3.0-only
import Foundation
import SwiftUI
import UIKit

@MainActor
final class ProxyModel: ObservableObject {
    enum State: String { case stopped = "Stopped", starting = "Starting", running = "Listening", stopping = "Stopping" }
    @Published var settings = ProxySettings()
    @Published private(set) var state = State.stopped
    @Published private(set) var message = "Enter your LAN settings, then tap Start."
    @Published private(set) var activeConnections = 0
    @Published private(set) var isActive = false
    @Published private(set) var hasSavedSettings = false

    private let engine: EngineController
    private let store: PrivateSettingsStore
    private var generation = 0
    private var statusPending = false
    private var previousIdleTimerValue: Bool?
    private var cleanupTask = UIBackgroundTaskIdentifier.invalid

    var canStart: Bool { isActive && state == .stopped }
    var canStop: Bool { state == .starting || state == .running }
    var canEdit: Bool { state == .stopped }

    init(engine: EngineController = EngineController(), store: PrivateSettingsStore = PrivateSettingsStore()) {
        self.engine = engine
        self.store = store
        do {
            if let saved = try store.load() {
                settings = saved
                hasSavedSettings = true
                message = "Saved LAN settings loaded. Enter the subscription URL before starting."
            }
        } catch {
            message = "Saved settings could not be read securely. Unlock the device and reopen the app, or enter fresh settings."
        }
        // Loading a saved subscription never starts a listener or network request.
    }

    func start() {
        guard canStart else { return }
        if let validation = settings.validationMessage { message = validation; return }
        let json: String
        do {
            json = try settings.engineJSON(dataDirectory: store.runtimeDirectory().path)
        } catch {
            message = "Private storage is unavailable. Unlock the device and try again."
            return
        }
        generation += 1
        let token = generation
        state = .starting
        message = "Opening the LAN listener…"
        synchronizeIdleTimer()
        engine.start(json: json) { [weak self] failure in
            guard let self, self.generation == token else { return }
            if let failure {
                self.state = .stopped
                self.message = failure
                self.restoreIdleTimer()
                return
            }
            self.state = .running
            self.message = "Listening; outbound pool will wake on demand."
            self.refreshStatus()
        }
    }

    func stop(reason: String = "Stopped. Restore the Portal's proxy setting when finished.") {
        restoreIdleTimer()
        guard state != .stopped else { return }
        // A finite UIKit assertion is used only to close the listener and owned
        // connections, never to keep serving traffic in the background.
        beginCleanupTask()
        guard state != .stopping else { return }
        generation += 1
        let token = generation
        statusPending = false
        state = .stopping
        message = "Closing the listener and connections…"
        engine.stop { [weak self] in
            guard let self else { return }
            self.endCleanupTask()
            guard self.generation == token else { return }
            self.state = .stopped
            self.activeConnections = 0
            self.message = reason
        }
    }

    func scenePhaseChanged(_ phase: ScenePhase) {
        isActive = phase == .active
        if phase == .background {
            stop(reason: "Stopped because the app left the foreground. Tap Start to resume.")
        } else {
            // Temporary inactive states (e.g. a system permission prompt) mask
            // the UI and release keep-awake, without implicitly restarting.
            synchronizeIdleTimer()
            if isActive { refreshStatus() }
        }
    }

    func didEnterBackground() {
        // Also handle UIKit's notification in case the view transition is delayed.
        isActive = false
        stop(reason: "Stopped because the app left the foreground. Tap Start to resume.")
    }

    func refreshStatus() {
        guard isActive, state == .running, !statusPending else { return }
        statusPending = true
        let token = generation
        engine.status { [weak self] status in
            guard let self, self.generation == token else { return }
            self.statusPending = false
            guard let status else { self.message = "Engine status is unavailable. Stop and restart if this persists."; return }
            self.message = status.summary
            self.activeConnections = max(0, status.active)
            if !status.running {
                self.state = .stopped
                self.restoreIdleTimer()
            }
        }
    }

    func saveSettings() {
        guard canEdit else { return }
        if let validation = settings.validationMessage { message = validation; return }
        do {
            try store.save(settings)
            hasSavedSettings = true
            message = "LAN settings saved with file protection and backup exclusion. The subscription URL was not saved."
        } catch {
            message = "Settings could not be saved securely. Nothing was logged."
        }
    }

    func forgetSettings() {
        guard canEdit else { return }
        do {
            try store.forget()
            settings = ProxySettings()
            hasSavedSettings = false
            message = "Saved configuration removed and fields cleared."
        } catch {
            message = "Saved configuration could not be removed. Unlock the device and try again."
        }
    }

    func synchronizeIdleTimer() {
        guard isActive, (state == .starting || state == .running), settings.keepAwake else {
            restoreIdleTimer()
            return
        }
        if previousIdleTimerValue == nil { previousIdleTimerValue = UIApplication.shared.isIdleTimerDisabled }
        UIApplication.shared.isIdleTimerDisabled = true
    }

    private func restoreIdleTimer() {
        if let previous = previousIdleTimerValue {
            UIApplication.shared.isIdleTimerDisabled = previous
            previousIdleTimerValue = nil
        }
    }

    private func beginCleanupTask() {
        guard cleanupTask == .invalid else { return }
        cleanupTask = UIApplication.shared.beginBackgroundTask(withName: "Close proxy connections") { [weak self] in
            // Stop is already in flight. No renewal, restart, or background work
            // is scheduled after expiry; UIKit may suspend or terminate us.
            self?.endCleanupTask()
        }
    }

    private func endCleanupTask() {
        guard cleanupTask != .invalid else { return }
        let task = cleanupTask
        cleanupTask = .invalid
        UIApplication.shared.endBackgroundTask(task)
    }
}

