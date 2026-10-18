// SPDX-License-Identifier: GPL-3.0-only
import SwiftUI
import Combine

@MainActor
struct ContentView: View {
    @ObservedObject var model: ProxyModel
    @ObservedObject private var network: NetworkEnvironment
    @State private var confirmForget = false
    @State private var showLicenses = false
    private let refresh = Timer.publish(every: 2, on: .main, in: .common).autoconnect()

    init(model: ProxyModel) {
        self.model = model
        self.network = model.network
    }

    private func t(_ zh: String, _ en: String) -> String { model.t(zh, en) }

    private var networkTitle: String {
        switch network.snapshot.uplink {
        case .wifi: return t("Wi-Fi 局域网", "Wi-Fi LAN")
        case .wired: return t("有线局域网", "Ethernet LAN")
        case .cellular: return t("蜂窝网络 · 个人热点待确认", "Cellular · confirm own hotspot")
        case .unavailable: return t("尚未连接网络", "No network connection")
        case .unknown: return t("正在识别网络", "Detecting network")
        }
    }

    var body: some View {
        ZStack {
            VStack(spacing: 0) {
                HStack {
                    Text("OnDemand").font(.title2.bold())
                    Spacer()
                    Picker(t("语言", "Language"), selection: $model.language) {
                        Text("中文").tag("zh")
                        Text("English").tag("en")
                    }.pickerStyle(.segmented).frame(width: 170)
                }.padding()
                Form {
                    Section {
                        Label(networkTitle, systemImage: network.snapshot.uplink == .cellular ? "antenna.radiowaves.left.and.right" : "wifi")
                        if network.snapshot.uplink == .cellular {
                            Toggle(t("我已开启本机个人热点", "I enabled this device's Personal Hotspot"), isOn: $model.confirmOwnHotspot)
                                .disabled(!model.canEdit)
                            Text(t("蜂窝连接不能证明热点已开启。先开启个人热点并让设备连接；仅使用检测到的私网共享接口，不会猜测固定热点地址。", "Cellular does not prove Personal Hotspot is enabled. Enable it and connect the client. Only a detected private sharing interface can be used; no hotspot address is assumed."))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    } header: { Text(t("当前网络", "Current network")) }
                    Section {
                        SecureField(t("粘贴 HTTPS 订阅链接", "Paste HTTPS subscription URL"), text: $model.settings.subscriptionURL)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                            .keyboardType(.URL).privacySensitive()
                            .accessibilityIdentifier("subscriptionURL").disabled(!model.canEdit)
                        if let info = model.subscriptionInfo {
                            LabeledContent(t("已用 / 总量", "Used / total"), value: bytes(info.used) + " / " + bytes(info.total.flatMap { $0>0 ? $0 : nil }))
                            LabeledContent(t("剩余流量", "Remaining"), value: bytes(info.remaining))
                            LabeledContent(t("到期时间", "Expires"), value: expiration(info.expire))
                            if let used = info.used, let total = info.total, total>0 {
                                ProgressView(value: Double(min(used,total)), total: Double(total))
                            }
                        } else {
                            Text(t("准备后显示订阅流量与到期信息，未返回的字段显示“未提供”。", "Subscription accounting appears after preparation. Missing server fields show Not provided."))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Button(t("一键准备并启动", "Prepare & start"), action: model.quickStart)
                            .buttonStyle(.borderedProminent).disabled(!model.canStart)
                            .accessibilityIdentifier("quickStartProxy")
                        Text(t("自动识别地址，优先保留端口 10081。允许当前局域网网段的设备连接。", "Detect the LAN address and keep port 10081 when available. Devices on the current local subnet can connect."))
                            .font(.caption).foregroundStyle(.secondary)
                    } header: { Text(t("订阅", "Subscription")) }
                    Section {
                        Text(model.localizedMessage).accessibilityIdentifier("proxyStatus")
                        if model.state == .running {
                            LabeledContent(t("活动连接", "Active connections"), value: String(model.activeConnections))
                        }
                        Button(t("停止监听", "Stop listener"), role: .destructive) { model.stop() }
                            .disabled(!model.canStop).accessibilityIdentifier("stopProxy")
                        Text(t("请保持本应用在前台且设备解锁；切换应用或锁屏后会停止服务。", "Keep this app in the foreground and the device unlocked. Switching apps or locking stops the service."))
                            .font(.caption).foregroundStyle(.secondary)
                    } header: { Text(t("运行状态", "Status")) }
                    Section {
                        if !model.settings.listenHost.isEmpty {
                            LabeledContent(t("服务器", "Server"), value: model.settings.listenHost).textSelection(.enabled)
                            LabeledContent(t("端口", "Port"), value: model.settings.listenPort).textSelection(.enabled)
                        }
                        Text(t("让设备加入同一个 Wi-Fi（热点模式下加入本机热点），打开设备 Wi-Fi 设置 → HTTP 代理 → 手动，填写服务器和端口，认证关闭。", "Join the same Wi-Fi, or this device's hotspot. Open the client's Wi-Fi settings → HTTP Proxy → Manual. Enter the server and port and leave authentication off."))
                        Text(t("IP 地址变化后需更新设备上的代理地址。停止使用时，将设备 HTTP 代理恢复为关闭。", "Update the client proxy if the IP changes. Turn the client's HTTP proxy off when finished."))
                            .font(.caption).foregroundStyle(.secondary)
                    } header: { Text(t("设备 Wi-Fi 怎么设置", "Device Wi-Fi setup")) }
                    Section {
                        DisclosureGroup(t("高级设置", "Advanced settings")) {
                            TextField(t("本机私网 IPv4", "Local private IPv4"), text: $model.settings.listenHost)
                                .keyboardType(.decimalPad).textInputAutocapitalization(.never).autocorrectionDisabled()
                            TextField(t("代理端口", "Proxy port"), text: $model.settings.listenPort).keyboardType(.numberPad)
                            TextField(t("允许接入的设备 IPv4", "Allowed client IPv4 addresses"), text: $model.settings.allowedClients, axis: .vertical)
                                .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.numbersAndPunctuation)
                            Picker(t("节点策略", "Node selection"), selection: $model.settings.selectionMode) {
                                Text(t("自动：香港 → 日本 → 其他", "Auto: HK → JP → other")).tag(SelectionMode.auto)
                                Text(t("首选，保留回退", "Prefer, with fallback")).tag(SelectionMode.prefer)
                                Text(t("固定，不自动换节点", "Fixed, no fallback")).tag(SelectionMode.fixed)
                            }
                            if model.settings.selectionMode != .auto {
                                TextField(t("准确节点名称", "Exact node name"), text: $model.settings.preferredNode)
                                    .textInputAutocapitalization(.never).autocorrectionDisabled().privacySensitive()
                            }
                            Stepper(t("空闲等待：", "Idle timeout: ") + String(model.settings.idleSeconds) + t(" 秒", " seconds"), value: $model.settings.idleSeconds, in: 5...3600, step: 5)
                            Button(t("使用手动配置启动", "Start with manual settings"), action: model.start)
                                .accessibilityIdentifier("startProxy")
                            Button(t("保存设置（不含订阅链接）", "Save settings, excluding subscription URL"), action: model.saveSettings)
                            Button(t("清除已保存的配置", "Forget saved configuration"), role: .destructive) { confirmForget = true }
                        }.disabled(!model.canEdit)
                        Toggle(t("运行时保持屏幕唤醒", "Keep screen awake while running"), isOn: $model.settings.keepAwake)
                            .onChange(of: model.settings.keepAwake) { _ in model.synchronizeIdleTimer() }
                        Toggle(t("深色外观", "Dark appearance"), isOn: $model.darkAppearance)
                        Button(t("开源许可与开发限制", "Licenses and development limits")) { showLicenses = true }
                        Text(t("当前支持 HTTP/CONNECT，尚未完成真机热点和实际游戏机验收。订阅链接只留在本次内存，不会保存。", "HTTP/CONNECT only. Physical hotspot and game-console acceptance remain pending. The subscription URL stays in session memory and is not saved."))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                .confirmationDialog(t("清除已保存的设置？", "Forget saved settings?"), isPresented: $confirmForget, titleVisibility: .visible) {
                    Button(t("清除配置", "Forget configuration"), role: .destructive, action: model.forgetSettings)
                    Button(t("取消", "Cancel"), role: .cancel) {}
                }
            }
            .sheet(isPresented: $showLicenses) { LicensesView(model: model) }
            if !model.isActive {
                Color(.systemBackground).ignoresSafeArea()
                VStack(spacing: 12) {
                    Image(systemName: "lock.fill").font(.largeTitle)
                    Text("OnDemand").font(.title2)
                    Text(t("配置已隐藏", "Configuration hidden")).foregroundStyle(.secondary)
                }
            }
        }
        .tint(.blue)
        .preferredColorScheme(model.darkAppearance ? .dark : .light)
        .onReceive(refresh) { _ in model.refreshStatus() }
        .onReceive(network.$snapshot) { _ in model.networkChanged() }
        .onChange(of: model.confirmOwnHotspot) { _ in model.networkChanged() }
        .onChange(of: model.settings.subscriptionURL) { _ in model.clearSubscriptionInfo() }
    }

    private func bytes(_ value: UInt64?) -> String {
        guard let value else { return t("未提供", "Not provided") }
        let units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"]
        var amount = Double(value)
        var index = 0
        while amount>=1024 && index<units.count-1 { amount /= 1024; index += 1 }
        return String(format: "%.2f %@", amount, units[index])
    }

    private func expiration(_ value: UInt64?) -> String {
        guard let value, value>0, value<=253402300799 else { return t("未提供", "Not provided") }
        let date = Date(timeIntervalSince1970: Double(value))
        return date.formatted(date: .numeric, time: .shortened) + (date < Date() ? t(" · 已到期", " · Expired") : "")
    }
}

@MainActor
private struct LicensesView: View {
    @ObservedObject var model: ProxyModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(model.t("开源许可", "Licenses")).font(.title2.bold())
                Spacer()
                Button(model.t("完成", "Done")) { dismiss() }
            }.padding()
            List {
                Text("This native application links Mihomo v1.19.32 and is GPL-3.0-only. The original project's MIT notice is preserved separately. No App Store compatibility or distribution approval is claimed.")
                Text("Foreground-only development app. No VPN, Packet Tunnel, background hosting, downloaded executable, or full iOS parity is provided. HTTP/CONNECT is supported by the shared engine; a real Portal session still needs device testing.")
                ForEach(["GPL-3.0", "THIRD-PARTY-NOTICES", "ENGINE-NOTICES", "PROJECT-MIT"], id: \.self) { name in
                    DisclosureGroup(name) {
                        Text(licenseText(name)).font(.caption.monospaced()).textSelection(.enabled)
                    }
                }
            }
        }
    }

    private func licenseText(_ name: String) -> String {
        guard let url = Bundle.main.url(forResource: name, withExtension: "txt")
                ?? Bundle.main.url(forResource: name, withExtension: "txt", subdirectory: "Licenses"),
              let text = try? String(contentsOf: url, encoding: .utf8) else {
            return "License resource missing. Do not distribute this build."
        }
        return text
    }
}
