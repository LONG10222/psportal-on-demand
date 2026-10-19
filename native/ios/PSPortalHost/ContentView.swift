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
                TabView {
                Form {
                    Section {
                        HStack(spacing: 12) {
                            Image(systemName: model.state == .running ? "wifi.circle.fill" : "power.circle")
                                .font(.system(size: 42)).foregroundStyle(model.state == .running ? .green : .secondary)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(model.statusTitle).font(.headline).accessibilityIdentifier("sharingStatusTitle")
                                Text(model.localizedMessage).font(.caption).foregroundStyle(.secondary).accessibilityIdentifier("proxyStatus")
                            }
                            if model.state == .starting || model.state == .stopping { ProgressView() }
                        }.padding(.vertical, 8)
                        HStack {
                            metric(t("接入设备", "Devices"), value: model.activeDevices)
                            Spacer()
                            metric(t("活动连接", "Connections"), value: model.activeConnections)
                        }
                        if model.canStop {
                            Button(t("停止共享", "Stop sharing"), role: .destructive) { model.stop() }
                                .accessibilityIdentifier("stopProxy")
                        }
                        Text(t("保持应用在前台且设备解锁；切换应用或锁屏后停止共享。", "Keep this app open and the device unlocked. Sharing stops when backgrounded or locked."))
                            .font(.caption).foregroundStyle(.secondary)
                    } header: { Text(t("局域网共享", "LAN sharing")) }
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
                }.tabItem { Label(t("共享", "Share"), systemImage: "wifi") }
                nodesPage.tabItem { Label(t("节点", "Nodes"), systemImage: "point.3.connected.trianglepath.dotted") }
                devicesPage.tabItem { Label(t("设备", "Devices"), systemImage: "iphone.and.arrow.forward") }
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

    private func metric(_ title: String, value: Int) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(String(value)).font(.title.bold()).monospacedDigit()
            Text(title).font(.caption).foregroundStyle(.secondary)
        }.accessibilityElement(children: .combine)
    }

    private var nodesPage: some View {
        Form {
            Section {
                Text(t("订阅节点", "Subscription nodes")).font(.title2.bold())
                Text(t("管理本应用内置核心。手动选择只影响新的连接；已建立的连接保持原路径。", "Controls this app's embedded engine. Changes apply to new connections; existing connections keep their route."))
                    .font(.caption).foregroundStyle(.secondary)
                Button(t("载入节点", "Load nodes")) { model.nodeAction("prepare") }
                    .disabled(model.state != .running || model.nodeBusy).accessibilityIdentifier("loadNodes")
                Button(t("测试延迟", "Test latency")) { model.nodeAction("probe") }
                    .disabled(model.state != .running || model.nodeBusy || model.nodes.isEmpty)
                Button { model.nodeAction("fastest") } label: {
                    Label(t("自动选择最低延迟", "Auto: lowest latency"), systemImage: model.autoFastest ? "checkmark.circle.fill" : "bolt.circle")
                }.disabled(model.state != .running || model.nodeBusy || model.nodes.isEmpty)
                if model.nodeBusy { ProgressView(t("正在载入或测速…", "Loading or testing…")) }
                if model.nodeMessage == "done" {
                    Text(t("操作已完成", "Operation completed")).foregroundStyle(.green)
                } else if model.nodeMessage == "failed" {
                    Text(t("操作未完成；请检查订阅、节点连接或重新载入。原有选择不会被失败测速替换。", "Operation failed. Check the subscription or connectivity, then reload. Failed probes do not replace your selection."))
                        .font(.caption).foregroundStyle(.orange)
                }
                Text(t("最低延迟模式按健康检查周期重测，默认每 5 分钟；核心休眠时不会为测速唤醒。手动点选会退出自动模式。", "Lowest-latency mode retests on the health interval, every 5 minutes by default. It does not wake an idle core. Manual selection turns it off."))
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section {
                if model.nodes.isEmpty {
                    Text(t("先在共享页启动，再点“载入节点”。这会下载订阅并检测节点，不需要其他设备先发起请求。", "Start sharing, then tap Load nodes. This downloads and checks nodes without waiting for another device's request."))
                        .foregroundStyle(.secondary)
                }
                ForEach(model.nodes) { node in
                    Button { model.nodeAction("select", name: node.name) } label: {
                        HStack(spacing: 12) {
                            Image(systemName: model.selectedNode == node.name ? "checkmark.circle.fill" : "circle")
                            VStack(alignment: .leading, spacing: 5) {
                                Text(node.name).font(.body).foregroundStyle(.primary)
                                Text(node.protocol ?? "Proxy").font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(node.healthy && (node.delay_ms ?? 0) > 0 ? "\(node.delay_ms ?? 0) ms" : t("不可用", "Unavailable"))
                                .font(.caption.monospacedDigit()).foregroundStyle(node.healthy ? .green : .orange)
                        }.padding(.vertical, 6)
                    }.disabled(model.nodeBusy || model.state != .running || !node.healthy).privacySensitive()
                }
            } header: { Text(t("点选切换节点", "Tap a node to switch")) }
            Section {
                Text(t("粘贴订阅链接，由本应用完成节点连接与设备共享，无需另开代理应用。当前导入支持的订阅节点，不导入完整分组和规则。", "Paste a subscription link to connect nodes and share with devices in this app. No second proxy app is needed. Supported nodes are imported; complete groups and rules are not."))
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private var devicesPage: some View {
        Form {
            Section {
                Text(t("接入设备", "Connected devices")).font(.title2.bold())
                HStack { metric(t("活跃设备", "Active devices"), value: model.activeDevices); Spacer(); metric(t("活动连接", "Connections"), value: model.activeConnections) }
                Text(t("按实际代理连接的来源 IP 统计，不扫描 Wi-Fi。一个设备可能建立多个连接；有连接不代表外网请求成功。", "Counts source IPs of actual proxy connections without scanning Wi-Fi. One device may open multiple connections. A connection does not prove Internet access."))
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section {
                if model.devices.isEmpty {
                    Text(model.state == .running ? t("等待设备接入。请按共享页填写 Wi-Fi 手动代理，然后访问网页。", "Waiting for devices. Set the manual Wi-Fi proxy using the Share page, then open a webpage.") : t("启动共享后显示设备记录。", "Start sharing to see devices."))
                        .foregroundStyle(.secondary)
                }
                ForEach(model.devices) { device in
                    VStack(alignment: .leading, spacing: 7) {
                        HStack {
                            Label(device.ip, systemImage: "network").font(.headline.monospaced())
                            Spacer()
                            Text(device.active > 0 ? t("使用中", "Active") : t("最近接入", "Recent"))
                                .font(.caption).foregroundStyle(device.active > 0 ? .green : .secondary)
                        }
                        Text(t("活动连接：", "Connections: ") + String(device.active) + t(" · 累计接入：", " · Accepted: ") + String(device.accepted)).font(.caption)
                        Text(Date(timeIntervalSince1970: Double(device.last_seen)), style: .time).font(.caption).foregroundStyle(.secondary)
                    }.padding(.vertical, 6).privacySensitive()
                }
            } header: { Text(t("最近 5 分钟 · 停止即清空", "Last 5 minutes · cleared on stop")) }
            Section {
                LabeledContent(t("请求错误", "Request errors"), value: String(model.requestErrors))
                LabeledContent(t("被拒绝的连接", "Denied connections"), value: String(model.deniedClients))
                Text(t("错误计数用于排查接入问题，不记录目标网站或订阅密钥。", "Counters help diagnose access issues without recording destination sites or subscription secrets."))
                    .font(.caption).foregroundStyle(.secondary)
            } header: { Text(t("接入诊断", "Connection diagnostics")) }
        }
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
