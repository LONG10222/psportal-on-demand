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
    @Published var language = "zh"
    @Published var darkAppearance = true
    @Published var confirmOwnHotspot = false
    @Published private(set) var subscriptionInfo: SubscriptionAccounting?
    let network = NetworkEnvironment()
    private var quickNetworkAddress: String?

    func t(_ zh: String, _ en: String) -> String { language == "zh" ? zh : en }
    func clearSubscriptionInfo() { subscriptionInfo = nil }
    var localizedMessage: String {
        guard language == "zh" else { return message }
        return [
            "Enter your LAN settings, then tap Start.": "粘贴订阅后，点击一键准备并启动。",
            "Enter this iPhone or iPad's current private Wi-Fi IPv4 address. Wildcard and loopback addresses are not allowed.": "请使用本机当前的 Wi-Fi 私网 IPv4 地址。",
            "Use a port from 1024 to 65535, other than the reserved compatibility ports 10082 and 10090.": "请使用 1024 至 65535 的端口，并避开保留端口 10082 和 10090。",
            "Enter one or more unique private IPv4 client addresses, separated by commas or new lines.": "请填写不重复的设备私网 IPv4 地址，用逗号或换行分隔。",
            "Enter a public HTTPS subscription URL, without a username, password, fragment, or non-443 port.": "请填写公网 HTTPS 订阅链接，不包含用户信息、片段或非 443 端口。",
            "Enter the exact node name for preferred or fixed mode.": "首选或固定模式需要准确的节点名称。",
            "Idle timeout must be between 1 and 86400 seconds.": "空闲等待时间应为 1 至 86400 秒。",
            "Private storage is unavailable. Unlock the device and try again.": "暂时无法使用私有存储，请解锁设备后重试。",
            "LAN settings saved with file protection and backup exclusion. The subscription URL was not saved.": "接入设置已加密保护并排除备份，订阅链接未保存。",
            "Settings could not be saved securely. Nothing was logged.": "无法安全保存设置，请解锁后重试。",
            "Saved configuration removed and fields cleared.": "已移除保存的配置并清空输入。",
            "Settings could not be removed. Unlock the device and try again.": "无法移除设置，请解锁设备后重试。",
            "Saved LAN settings loaded. Enter the subscription URL before starting.": "已载入接入设置，请先粘贴订阅链接。",
            "Saved settings could not be read securely. Unlock the device and reopen the app, or enter fresh settings.": "无法读取已保存的设置，请解锁设备后重试。",
            "Opening the LAN listener…": "正在启动局域网监听…",
            "Listening; outbound pool will wake on demand.": "正在监听；上游会在收到外部请求时按需唤醒。",
            "Listening; outbound pool will wake on demand": "正在监听；上游会在收到外部请求时按需唤醒。",
            "Closing the listener and connections…": "正在关闭监听器和连接…",
            "Stopped. Restore the Portal's proxy setting when finished.": "已停止。结束使用后，请关闭设备的手动 HTTP 代理。",
            "Stopped because the app left the foreground. Tap Start to resume.": "应用已离开前台，监听已停止。返回后可重新启动。",
            "Engine status is unavailable. Stop and restart if this persists.": "暂时无法获取引擎状态，可停止后重新启动。",
            "Loading and checking proxy nodes": "正在载入和检查节点",
            "Encrypted outbound pool ready": "上游节点已就绪",
            "Outbound unavailable; check the subscription and node connectivity": "上游不可用，请检查订阅与节点连接。",
            "Listening; waiting for engine status": "正在监听，等待引擎状态。",
            "Stopped": "已停止",
            "The proxy could not start. Check the Wi-Fi address, port, and configuration.": "代理无法启动，请检查 Wi-Fi 地址、端口和配置。",
            "No shareable LAN address found. Join Wi-Fi, or enable your own hotspot and connect the client first.": "未发现可共享地址。请接入 Wi-Fi；使用本机热点时，先开启热点并连接设备。",
            "No available port. Check Advanced settings.": "没有可用端口，请检查高级设置。",
            "Network changed. Listener stopped. Prepare again and update the client proxy address.": "网络已变化，监听已停止。请重新准备并更新设备的代理地址。"
        ][message] ?? message
    }

    func quickStart() {
        guard canStart else { return }
        guard let lan = network.snapshot.shareableLAN(confirmOwnHotspot: confirmOwnHotspot),
              let clients = lan.clients, !clients.isEmpty else {
            message = "No shareable LAN address found. Join Wi-Fi, or enable your own hotspot and connect the client first."
            return
        }
        guard let port = NetworkEnvironment.availablePort(host: lan.address, preferred: Int(settings.listenPort) ?? 10081) else {
            message = "No available port. Check Advanced settings."
            return
        }
        settings.listenHost = lan.address
        settings.listenPort = String(port)
        settings.allowedClients = clients.joined(separator: ",")
        quickNetworkAddress = lan.address
        start()
        if state == .stopped { quickNetworkAddress = nil }
    }

    func networkChanged() {
        guard let address = quickNetworkAddress, canStop else { return }
        if network.snapshot.shareableLAN(confirmOwnHotspot: confirmOwnHotspot)?.address != address {
            quickNetworkAddress = nil
            stop(reason: "Network changed. Listener stopped. Prepare again and update the client proxy address.")
        }
    }

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
                self.quickNetworkAddress = nil
                self.state = .stopped
                self.message = failure
                self.restoreIdleTimer()
                return
            }
            self.state = .running
            self.message = "Listening; outbound pool will wake on demand."
            self.refreshStatus()
            self.subscriptionInfo = nil
            self.engine.subscriptionInfo(url: self.settings.subscriptionURL) { [weak self] info in
                guard let self, self.generation == token else { return }
                self.subscriptionInfo = info
            }
        }
    }

    func stop(reason: String = "Stopped. Restore the Portal's proxy setting when finished.") {
        quickNetworkAddress = nil
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

