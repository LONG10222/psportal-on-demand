// SPDX-License-Identifier: GPL-3.0-only
import SwiftUI
import Combine

@MainActor
struct ContentView: View {
    @ObservedObject var model: ProxyModel
    @ObservedObject private var network: NetworkEnvironment
    @State private var tab = 0
    @State private var confirmForget = false
    @State private var showLicenses = false
    @State private var settingsFeedback = false
    @State private var nodeSearch = ""
    @State private var healthyOnly = false
    @State private var sortByDelay = false
    @FocusState private var subscriptionFocused: Bool
    private let refresh = Timer.publish(every: 2, on: .main, in: .common).autoconnect()

    init(model: ProxyModel) {
        self.model = model
        self.network = model.network
    }

    private func t(_ zh: String, _ en: String) -> String { model.t(zh, en) }
    private var running: Bool { model.state == .running }
    private var transitioning: Bool { model.state == .starting || model.state == .stopping }
    private var canControlNodes: Bool { running && !model.nodeBusy }
    private var primaryTitle: String {
        if model.state == .starting { return t("取消启动", "Cancel start") }
        if model.state == .stopping { return t("正在停止", "Stopping") }
        return model.canStop ? t("停止共享", "Stop sharing") : t("准备并启动共享", "Prepare & start")
    }
    private var networkTitle: String {
        switch network.snapshot.uplink {
        case .wifi: return t("Wi-Fi 局域网", "Wi-Fi LAN")
        case .wired: return t("有线局域网", "Ethernet LAN")
        case .cellular: return t("蜂窝网络", "Cellular")
        case .unavailable: return t("未连接网络", "Offline")
        case .unknown: return t("识别网络中", "Detecting network")
        }
    }

    var body: some View {
        ZStack {
            VStack(spacing: 0) {
                appHeader
                TabView(selection: $tab) {
                    sharingPage.tag(0).tabItem { Label(t("共享", "Share"), systemImage: "wifi") }
                    nodesPage.tag(1).tabItem { Label(t("节点", "Nodes"), systemImage: "point.3.connected.trianglepath.dotted") }
                    devicesPage.tag(2).tabItem { Label(t("设备", "Devices"), systemImage: "laptopcomputer.and.iphone") }
                    settingsPage.tag(3).tabItem { Label(t("设置", "Settings"), systemImage: "slider.horizontal.3") }
                }
                .confirmationDialog(t("清除已保存的设置？", "Forget saved settings?"), isPresented: $confirmForget, titleVisibility: .visible) {
                    Button(t("清除配置", "Forget configuration"), role: .destructive) { model.forgetSettings(); settingsFeedback = true }
                    Button(t("取消", "Cancel"), role: .cancel) {}
                }
            }
            if !model.isActive {
                Color(.systemBackground).ignoresSafeArea()
                VStack(spacing: 12) {
                    Image("StarPassMark").resizable().scaledToFit().frame(width: 64, height: 64)
                        .clipShape(RoundedRectangle(cornerRadius: 16))
                    Text(t("星渡 StarPass", "StarPass")).font(.title2.bold())
                    Label(t("配置已隐藏", "Configuration hidden"), systemImage: "lock.fill").foregroundStyle(.secondary)
                }
            }
        }
        .sheet(isPresented: $showLicenses) { LicensesView(model: model) }
        .tint(.blue)
        .preferredColorScheme(model.darkAppearance ? .dark : .light)
        .onReceive(refresh) { _ in model.refreshStatus() }
        .onChange(of: model.confirmOwnHotspot) { _ in model.networkChanged(network.snapshot) }
        .onChange(of: model.settings.subscriptionURL) { _ in model.clearSubscriptionInfo() }
        .onChange(of: tab) { _ in subscriptionFocused = false }
    }

    private var appHeader: some View {
        HStack(spacing: 10) {
            Image("StarPassMark").resizable().scaledToFit().frame(width: 38, height: 38)
                .clipShape(RoundedRectangle(cornerRadius: 10)).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(t("星渡", "StarPass")).font(.title3.bold())
                Text(t("让设备轻松连接", "Connect your devices")).font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 8)
            Menu {
                Button { model.language = "zh" } label: {
                    Label("中文", systemImage: model.language == "zh" ? "checkmark" : "globe")
                }
                Button { model.language = "en" } label: {
                    Label("English", systemImage: model.language == "en" ? "checkmark" : "globe")
                }
            } label: {
                Label(model.language == "zh" ? "中文" : "EN", systemImage: "globe")
                    .font(.subheadline.weight(.medium)).padding(.horizontal, 12).padding(.vertical, 9)
                    .background(Color(.tertiarySystemFill), in: Capsule())
            }.accessibilityLabel(t("切换语言", "Change language")).accessibilityIdentifier("languageMenu")
        }.padding(.horizontal, 20).padding(.vertical, 12).background(Color(.systemGroupedBackground))
    }

    private func page<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 16, content: content)
                .frame(maxWidth: 660).padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 30)
                .frame(maxWidth: .infinity)
        }.background(Color(.systemGroupedBackground)).scrollDismissesKeyboard(.interactively)
    }

    private func card<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 16, content: content)
            .frame(maxWidth: .infinity, alignment: .leading).padding(20)
            .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 24))
            .overlay(RoundedRectangle(cornerRadius: 24).stroke(Color.primary.opacity(0.045), lineWidth: 1))
    }

    private func sectionTitle(_ title: String, detail: String? = nil) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title).font(.headline)
            Spacer()
            if let detail { Text(detail).font(.caption).foregroundStyle(.secondary) }
        }
    }

    private var sharingPage: some View {
        page {
            card {
                HStack {
                    Label(t("设备共享", "Device sharing"), systemImage: "gamecontroller")
                        .font(.subheadline.weight(.medium)).accessibilityIdentifier("availableProductMode")
                    Spacer()
                    Label(networkTitle, systemImage: network.snapshot.uplink == .cellular ? "antenna.radiowaves.left.and.right" : "wifi")
                        .font(.caption).foregroundStyle(.secondary)
                }
                HStack(spacing: 14) {
                    Image(systemName: running ? "wifi" : "power")
                        .font(.system(size: 24, weight: .semibold)).foregroundStyle(running ? Color.green : Color.blue)
                        .frame(width: 56, height: 56)
                        .background((running ? Color.green : Color.blue).opacity(0.12), in: RoundedRectangle(cornerRadius: 18))
                    VStack(alignment: .leading, spacing: 5) {
                        Text(model.statusTitle).font(.title3.bold()).fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("sharingStatusTitle")
                        Text(model.localizedMessage).font(.caption).foregroundStyle(.secondary)
                            .accessibilityIdentifier("proxyStatus")
                    }
                    if transitioning { Spacer(minLength: 0); ProgressView() }
                }
                Divider()
                HStack {
                    metric(t("接入设备", "Devices"), value: model.activeDevices)
                    Spacer()
                    metric(t("活动连接", "Connections"), value: model.activeConnections)
                    Spacer()
                    VStack(alignment: .trailing, spacing: 5) {
                        Label(model.hasBackgroundGrant ? t("限时后台已授权", "Timed background granted") : t("前台共享", "Foreground"), systemImage: "iphone")
                            .font(.caption.weight(.medium)).foregroundStyle(.secondary)
                        Text("HTTP · TCP").font(.caption2.monospaced()).foregroundStyle(.secondary)
                    }
                }
            }
            card {
                sectionTitle(t("订阅", "Subscription"), detail: t("仅需一个链接", "Just one link"))
                HStack(spacing: 10) {
                    Image(systemName: "link").foregroundStyle(.blue)
                    SecureField(t("粘贴 HTTPS 订阅链接", "Paste HTTPS subscription URL"), text: $model.settings.subscriptionURL)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                        .privacySensitive().focused($subscriptionFocused).disabled(!model.canEdit)
                        .submitLabel(.done).onSubmit { subscriptionFocused = false }
                        .accessibilityIdentifier("subscriptionURL")
                    if model.canEdit {
                        PasteButton(payloadType: String.self) { values in
                            if let value = values.first { model.settings.subscriptionURL = value.trimmingCharacters(in: .whitespacesAndNewlines) }
                        }.labelStyle(.iconOnly).accessibilityLabel(t("粘贴订阅链接", "Paste subscription link"))
                    }
                }.padding(14).background(Color(.tertiarySystemFill), in: RoundedRectangle(cornerRadius: 14))
                if let info = model.subscriptionInfo {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(t("剩余流量", "Remaining")).font(.caption).foregroundStyle(.secondary)
                            Text(bytes(info.remaining)).font(.title3.bold()).monospacedDigit()
                        }
                        Spacer()
                        VStack(alignment: .trailing, spacing: 4) {
                            Text(t("到期时间", "Expires")).font(.caption).foregroundStyle(.secondary)
                            Text(expiration(info.expire)).font(.subheadline.weight(.medium))
                        }
                    }
                    if let used = info.used, let total = info.total, total > 0 {
                        ProgressView(value: Double(min(used, total)), total: Double(total))
                        Text(t("已用 ", "Used ") + bytes(used) + " / " + bytes(total)).font(.caption).foregroundStyle(.secondary)
                    }
                    if let updated = model.subscriptionInfoUpdatedAt {
                        Text(t("服务器快照 · ", "Server snapshot · ") + updated.formatted(date: .omitted, time: .shortened))
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                }
                Button {
                    subscriptionFocused = false
                    if model.canStop { model.stop() } else { model.quickStart() }
                } label: {
                    HStack {
                        Spacer(minLength: 0)
                        if transitioning { ProgressView().tint(.white) }
                        Image(systemName: model.canStop ? "stop.fill" : "power")
                        Text(primaryTitle)
                            .font(.headline)
                        Spacer(minLength: 0)
                    }.padding(.vertical, 8).frame(maxWidth: .infinity)
                }.buttonStyle(.borderedProminent).tint(model.canStop ? Color.red : Color.blue)
                    .controlSize(.large)
                    .disabled(model.state == .stopping || (!model.canStop && (!model.canStart || model.settings.subscriptionURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)))
                    .accessibilityIdentifier(model.canStop ? "stopProxy" : "quickStartProxy")
                if model.subscriptionInfo == nil {
                    Text(t("启动后读取订阅用量与到期信息；链接仅保留在本次会话。", "Usage and expiry appear after starting. The link stays in this session only."))
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            if network.snapshot.uplink == .cellular {
                card {
                    Toggle(t("我已开启本机个人热点", "I enabled this device's Personal Hotspot"), isOn: $model.confirmOwnHotspot).disabled(!model.canEdit)
                    Text(t("先开启热点并连接设备，应用会检测实际共享地址。蜂窝联网不代表热点已开启。", "Enable your hotspot and connect a device first. We detect its actual sharing address; cellular alone does not prove a hotspot is enabled."))
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            connectionCard
            Label(model.hasBackgroundGrant ? t("限时后台实验已获授权，系统仍可提前终止。", "Timed background experiment granted; the system can end it early.") : t("切后台或锁屏后停止共享，请保持应用打开。", "Sharing stops when backgrounded or locked. Keep this app open."), systemImage: "info.circle")
                .font(.caption).foregroundStyle(.secondary).padding(.horizontal, 4)
        }
    }

    private var connectionCard: some View {
        card {
            sectionTitle(t("连接其他设备", "Connect another device"), detail: running ? t("监听已就绪", "Listener ready") : t("启动后生成", "Available after start"))
            HStack(spacing: 12) {
                endpoint(t("服务器", "Server"), value: running ? model.settings.listenHost : "—")
                endpoint(t("端口", "Port"), value: running ? model.settings.listenPort : "—")
            }
            DisclosureGroup(t("设备 Wi-Fi 怎么设置", "How to set up device Wi-Fi")) {
                VStack(alignment: .leading, spacing: 14) {
                    guideStep(1, t("加入同一个 Wi-Fi 或本机热点", "Join the same Wi-Fi or this device's hotspot"))
                    guideStep(2, t("Wi-Fi → HTTP 代理 → 手动，填写上方地址与端口，认证关闭", "Wi-Fi → HTTP Proxy → Manual. Enter the address and port above; authentication off"))
                    guideStep(3, t("打开网页验证；结束使用后关闭设备的 HTTP 代理", "Open a webpage to verify. Turn the device's HTTP proxy off when finished"))
                }.padding(.top, 12)
            }.font(.subheadline)
            Button { tab = 2 } label: {
                HStack { Label(t("查看接入设备", "View connected devices"), systemImage: "laptopcomputer.and.iphone"); Spacer(); Image(systemName: "chevron.right").font(.caption.bold()) }
            }.font(.subheadline.weight(.medium))
        }
    }

    private func endpoint(_ title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.system(.body, design: .monospaced).weight(.semibold)).textSelection(.enabled)
                .lineLimit(1).minimumScaleFactor(0.7)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(14)
            .background(Color(.tertiarySystemFill), in: RoundedRectangle(cornerRadius: 14))
    }

    private func guideStep(_ number: Int, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Text(String(number)).font(.caption.bold()).foregroundStyle(.blue).frame(width: 23, height: 23)
                .background(Color.blue.opacity(0.12), in: Circle())
            Text(text).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }
    }

    private func metric(_ title: String, value: Int) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(String(value)).font(.system(.title2, design: .rounded).bold()).monospacedDigit()
            Text(title).font(.caption).foregroundStyle(.secondary)
        }.accessibilityElement(children: .combine)
    }

    private var visibleNodes: [ProxyNode] {
        let matches = model.nodes.filter { (!healthyOnly || $0.healthy) && (nodeSearch.isEmpty || $0.name.localizedCaseInsensitiveContains(nodeSearch)) }
        return sortByDelay ? matches.sorted { ($0.delay_ms.flatMap { $0 > 0 ? $0 : nil } ?? Int.max) < ($1.delay_ms.flatMap { $0 > 0 ? $0 : nil } ?? Int.max) } : matches
    }

    private var nodesPage: some View {
        page {
            pageHeading(t("选择节点", "Choose a node"), subtitle: t("点选切换，新连接使用新节点", "Tap to switch the route for new connections"))
            card {
                HStack(spacing: 12) {
                    nodeTool(t("载入", "Load"), icon: "arrow.down.circle", enabled: canControlNodes, identifier: "loadNodes") { model.nodeAction("prepare") }
                    nodeTool(t("测速", "Test"), icon: "speedometer", enabled: canControlNodes && !model.nodes.isEmpty) { model.nodeAction("probe") }
                    nodeTool(t("自动最快", "Fastest"), icon: model.autoFastest ? "checkmark.circle.fill" : "bolt.circle", enabled: canControlNodes && !model.nodes.isEmpty) { model.nodeAction("fastest") }
                }
                if model.nodeBusy { ProgressView(t("正在载入或测速…", "Loading or testing…")).font(.caption) }
                else if model.nodeMessage == "failed" {
                    Label(t("操作失败，请检查订阅或网络；原有策略保留。", "Failed. Check the subscription or network; your policy is retained."), systemImage: "exclamationmark.circle")
                        .font(.caption).foregroundStyle(.orange)
                }
                HStack {
                    Circle().fill(model.autoFastest ? Color.green : Color.blue).frame(width: 7, height: 7)
                    Text(model.autoFastest ? t("自动 · 最低延迟", "Auto · lowest latency") : t("手动 / 地区优先", "Manual / region priority")).font(.caption.weight(.medium))
                    Spacer()
                    if model.nodeMessage == "done" { Image(systemName: "checkmark").foregroundStyle(.green) }
                }
            }
            if model.nodes.isEmpty {
                emptyState(icon: "point.3.connected.trianglepath.dotted", title: running ? t("准备载入订阅节点", "Ready to load nodes") : t("先启动共享", "Start sharing first"),
                           detail: running ? t("点击载入，读取并检查本次订阅节点。", "Tap Load to download and check this subscription's nodes.") : t("在共享页粘贴链接并启动，再来选择节点。", "Paste your link and start on the Share page, then choose a node."))
                if !running { Button(t("前往共享", "Go to Share")) { tab = 0 }.buttonStyle(.borderedProminent).frame(maxWidth: .infinity) }
            } else {
                HStack {
                    HStack(spacing: 8) {
                        Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                        TextField(t("搜索节点", "Search nodes"), text: $nodeSearch).textInputAutocapitalization(.never).autocorrectionDisabled()
                            .accessibilityIdentifier("nodeSearch")
                    }.padding(12).background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 14))
                    Menu {
                        Toggle(t("仅显示可用", "Healthy only"), isOn: $healthyOnly)
                        Toggle(t("按延迟排序", "Sort by latency"), isOn: $sortByDelay)
                    } label: { Image(systemName: "line.3.horizontal.decrease.circle").font(.title2).padding(6) }.accessibilityLabel(t("筛选节点", "Filter nodes"))
                }
                sectionTitle(t("订阅节点", "Subscription nodes"), detail: String(visibleNodes.count) + " / " + String(model.nodes.count))
                if visibleNodes.isEmpty { emptyState(icon: "magnifyingglass", title: t("没有匹配的节点", "No matching nodes"), detail: t("试试其他关键词或关闭筛选。", "Try another search or turn off filters.")) }
                ForEach(visibleNodes) { node in nodeRow(node) }
            }
            DisclosureGroup(t("节点策略说明", "About node selection")) {
                Text(t("自动最低延迟按健康检查周期重测，默认 5 分钟；不会为测速唤醒休眠核心。失败节点不作为零延迟，手动点选退出自动模式。已有连接保留原路径。", "Lowest-latency mode retests every 5 minutes by default without waking an idle core. Failed probes are not zero-latency winners. Manual selection exits auto mode; existing connections keep their route."))
                    .font(.caption).foregroundStyle(.secondary).padding(.top, 8)
            }.font(.caption).foregroundStyle(.secondary).padding(.horizontal, 4)
        }
    }

    private func nodeTool(_ title: String, icon: String, enabled: Bool, identifier: String = "", action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 8) { Image(systemName: icon).font(.title2); Text(title).font(.caption.weight(.semibold)) }
                .frame(maxWidth: .infinity).padding(.vertical, 14)
                .background(Color.blue.opacity(0.09), in: RoundedRectangle(cornerRadius: 16))
        }.buttonStyle(.plain).foregroundStyle(.blue).opacity(enabled ? 1 : 0.35).disabled(!enabled).accessibilityIdentifier(identifier)
    }

    private func nodeRow(_ node: ProxyNode) -> some View {
        let selected = model.selectedNode == node.name
        return Button { model.nodeAction("select", name: node.name) } label: {
            HStack(spacing: 12) {
                Image(systemName: selected ? "checkmark.circle.fill" : "circle").font(.title3).foregroundStyle(selected ? Color.blue : Color.secondary)
                VStack(alignment: .leading, spacing: 7) {
                    Text(node.name).font(.subheadline.weight(.semibold)).foregroundStyle(.primary).multilineTextAlignment(.leading)
                    Text(node.protocol ?? "Proxy").font(.caption2.weight(.medium)).foregroundStyle(.secondary)
                        .padding(.horizontal, 8).padding(.vertical, 3).background(Color(.tertiarySystemFill), in: Capsule())
                }
                Spacer(minLength: 4)
                Text(node.healthy && (node.delay_ms ?? 0) > 0 ? "\(node.delay_ms ?? 0) ms" : t("不可用", "Unavailable"))
                    .font(.caption.monospacedDigit()).foregroundStyle(node.healthy ? Color.green : Color.orange)
            }.padding(16).frame(maxWidth: .infinity)
                .background(selected ? Color.blue.opacity(0.09) : Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 18))
                .overlay(RoundedRectangle(cornerRadius: 18).stroke(selected ? Color.blue.opacity(0.6) : Color.clear, lineWidth: 1))
        }.buttonStyle(.plain).disabled(!canControlNodes || !node.healthy).privacySensitive()
            .accessibilityValue(selected ? t("已选择", "Selected") : "")
    }

    private var devicesPage: some View {
        page {
            pageHeading(t("接入设备", "Connected devices"), subtitle: t("查看正在使用共享的设备", "See which devices are using your connection"))
            card {
                HStack { metric(t("活跃设备", "Active devices"), value: model.activeDevices); Spacer(); metric(t("活动连接", "Connections"), value: model.activeConnections) }
                Text(t("按实际代理来源 IP 统计，一个设备可能建立多个连接。", "Counts actual proxy source IPs; one device can open several connections.")).font(.caption).foregroundStyle(.secondary)
            }
            if model.devices.isEmpty {
                emptyState(icon: "laptopcomputer.and.iphone", title: running ? t("等待第一台设备", "Waiting for your first device") : t("还没有接入记录", "No devices yet"), detail: running ? t("给设备设置 Wi-Fi 手动代理，再打开网页。接入后会显示在这里。", "Set the device's manual Wi-Fi proxy and open a webpage. It will appear here.") : t("启动共享后，设备连接与最近记录会显示在这里。", "Start sharing to see active connections and recent devices."))
                Button(t("前往共享页", "Go to Share")) { tab = 0 }.buttonStyle(.borderedProminent).frame(maxWidth: .infinity)
            } else {
                sectionTitle(t("最近接入", "Recent devices"), detail: t("5 分钟内", "Last 5 min"))
                ForEach(model.devices) { device in
                    card {
                        HStack(spacing: 12) {
                            Image(systemName: "network").font(.title2).foregroundStyle(.blue)
                                .frame(width: 44, height: 44).background(Color.blue.opacity(0.1), in: RoundedRectangle(cornerRadius: 14))
                            VStack(alignment: .leading, spacing: 4) {
                                Text(device.ip).font(.system(.subheadline, design: .monospaced).weight(.semibold))
                                Text(device.active > 0 ? t("正在使用", "Active") : t("最近连接", "Recently connected")).font(.caption).foregroundStyle(device.active > 0 ? Color.green : Color.secondary)
                            }
                            Spacer()
                            Text(String(device.active)).font(.title2.bold()).monospacedDigit()
                        }
                        HStack {
                            Text(t("累计接入 ", "Accepted ") + String(device.accepted))
                            Spacer()
                            Text(Date(timeIntervalSince1970: Double(device.last_seen)), style: .time)
                        }.font(.caption).foregroundStyle(.secondary)
                    }.privacySensitive()
                }
            }
            DisclosureGroup(t("接入诊断与隐私", "Diagnostics & privacy")) {
                VStack(alignment: .leading, spacing: 12) {
                    LabeledContent(t("请求错误", "Request errors"), value: String(model.requestErrors))
                    LabeledContent(t("被拒绝的连接", "Denied connections"), value: String(model.deniedClients))
                    Text(t("有连接不代表外网成功。不扫描局域网，不记录目标网站；记录仅在内存保留 5 分钟，停止即清空。", "Connections do not prove Internet access. No LAN scanning or destination history. Records stay in memory for 5 minutes and clear on stop."))
                        .foregroundStyle(.secondary)
                }.font(.caption).padding(.top, 12)
            }.font(.caption).foregroundStyle(.secondary).padding(.horizontal, 4)
        }
    }

    private func pageHeading(_ title: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.title2.bold())
            Text(subtitle).font(.caption).foregroundStyle(.secondary)
        }.padding(.vertical, 8)
    }

    private func emptyState(icon: String, title: String, detail: String) -> some View {
        VStack(spacing: 14) {
            Image(systemName: icon).font(.system(size: 40, weight: .light)).foregroundStyle(.blue)
                .frame(width: 84, height: 84).background(Color.blue.opacity(0.08), in: RoundedRectangle(cornerRadius: 26))
            Text(title).font(.headline)
            Text(detail).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }.frame(maxWidth: .infinity).padding(.horizontal, 20).padding(.vertical, 32)
    }

    private var settingsPage: some View {
        Form {
            Section {
                Label(t("游戏 / 局域网共享", "Game / LAN sharing"), systemImage: "gamecontroller")
                Text(t("提供 HTTP/CONNECT TCP 共享，后台为限时实验。UDP 游戏流量、整机 VPN 与完整分组 / 规则尚不可用。", "HTTP/CONNECT TCP sharing with an experimental timed background mode. UDP game traffic, device-wide VPN, and full Clash groups/rules modes are unavailable."))
                    .font(.caption).foregroundStyle(.secondary).accessibilityIdentifier("productModeScope")
            } header: { Text(t("当前能力", "Available features")) }
            Section {
                Picker(t("语言", "Language"), selection: $model.language) { Text("中文").tag("zh"); Text("English").tag("en") }
                Toggle(t("深色外观", "Dark appearance"), isOn: $model.darkAppearance)
                Toggle(t("运行时保持屏幕唤醒", "Keep screen awake while running"), isOn: $model.settings.keepAwake)
                    .onChange(of: model.settings.keepAwake) { _ in model.synchronizeIdleTimer() }
            } header: { Text(t("使用偏好", "Preferences")) } footer: {
                Text(t("保持唤醒会增加耗电，不能让共享在后台继续。", "Keeping the screen awake uses more power and does not enable background sharing."))
            }
            Section {
                Toggle(t("启用限时后台共享（实验）", "Timed background sharing (experimental)"), isOn: $model.backgroundEnabled)
                    .disabled(!model.canEdit || !model.backgroundAvailable)
                    .accessibilityIdentifier("timedBackgroundToggle")
                Picker(t("共享时长", "Session duration"), selection: $model.backgroundMinutes) {
                    ForEach([15, 30, 60], id: \.self) { Text("\($0) " + t("分钟", "min")).tag($0) }
                }.disabled(!model.canEdit || !model.backgroundAvailable)
                if let deadline = model.backgroundDeadline {
                    Text(t("结束时间：", "Ends: ") + deadline.formatted(date: .omitted, time: .shortened))
                }
                if !model.backgroundMessage.isEmpty { Text(model.localizedBackgroundMessage).font(.caption) }
                Text(model.backgroundAvailable
                    ? t("此选项不会保存，不会自动启动。系统授权后才可退到后台；取消、到期或网络变化会停止共享。锁屏联网尚待真机验证，不支持永久保活。", "This option is not saved and never starts sharing automatically. Wait for the system grant before leaving. Cancellation, expiry or network changes stop sharing. Lock-screen networking needs device validation; no unlimited keepalive.")
                    : t("需要 iOS 26+ 真机与系统授权。模拟器不支持此后台任务；当前仍为前台共享。", "Requires a real device on iOS 26+ and a system grant. Simulator does not support this task; sharing remains foreground-only."))
                    .font(.caption).foregroundStyle(.secondary)
            } header: { Text(t("后台共享", "Background sharing")) }
            Section {
                DisclosureGroup(t("高级接入设置", "Advanced connection settings")) {
                    TextField(t("本机私网 IPv4", "Local private IPv4"), text: $model.settings.listenHost).keyboardType(.decimalPad)
                    TextField(t("代理端口", "Proxy port"), text: $model.settings.listenPort).keyboardType(.numberPad)
                    TextField(t("允许接入的设备 IPv4", "Allowed client IPv4 addresses"), text: $model.settings.allowedClients, axis: .vertical)
                        .keyboardType(.numbersAndPunctuation)
                    Picker(t("初始节点策略", "Initial node policy"), selection: $model.settings.selectionMode) {
                        Text(t("自动：香港 → 日本 → 其他", "Auto: HK → JP → other")).tag(SelectionMode.auto)
                        Text(t("首选，保留回退", "Prefer, with fallback")).tag(SelectionMode.prefer)
                        Text(t("固定，不自动换节点", "Fixed, no fallback")).tag(SelectionMode.fixed)
                    }
                    if model.settings.selectionMode != .auto {
                        TextField(t("准确节点名称", "Exact node name"), text: $model.settings.preferredNode).privacySensitive()
                    }
                    Stepper(t("空闲等待：", "Idle timeout: ") + String(model.settings.idleSeconds) + t(" 秒", " seconds"), value: $model.settings.idleSeconds, in: 5...3600, step: 5)
                    Button(t("使用手动配置启动", "Start with manual settings")) { model.start(); settingsFeedback = true }.accessibilityIdentifier("startProxy")
                }.disabled(!model.canEdit).textInputAutocapitalization(.never).autocorrectionDisabled()
                Button(t("保存接入设置", "Save connection settings")) { model.saveSettings(); settingsFeedback = true }.disabled(!model.canEdit)
                Button(t("清除已保存的配置", "Forget saved configuration"), role: .destructive) { confirmForget = true }.disabled(!model.canEdit)
                if settingsFeedback { Text(model.localizedMessage).font(.caption).foregroundStyle(.secondary).accessibilityIdentifier("settingsFeedback") }
            } header: { Text(t("接入与存储", "Connection & storage")) } footer: {
                Text(t("订阅链接只在本次会话中使用，不保存到设置。默认端口 10081，被占用时才更换。", "The subscription link is session-only and is not saved. Port 10081 is preferred; another is used only if occupied."))
            }
            Section {
                Button(t("开源许可与开发限制", "Licenses and development limits")) { showLicenses = true }
                Text(t("手机仅需导入订阅，无需另开代理应用。当前不支持后台共享；真实热点与游戏机尚待验证。", "Import a subscription; no second proxy app is needed. Background sharing is unavailable; physical hotspots and game consoles remain unverified."))
                    .font(.caption).foregroundStyle(.secondary)
            } header: { Text(t("关于星渡", "About StarPass")) }
        }
    }

    private func bytes(_ value: UInt64?) -> String {
        guard let value else { return t("未提供", "Not provided") }
        let units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"]
        var amount = Double(value), index = 0
        while amount >= 1024 && index < units.count - 1 { amount /= 1024; index += 1 }
        return String(format: "%.2f %@", amount, units[index])
    }

    private func expiration(_ value: UInt64?) -> String {
        guard let value, value > 0, value <= 253402300799 else { return t("未提供", "Not provided") }
        let date = Date(timeIntervalSince1970: Double(value))
        return date.formatted(date: .numeric, time: .omitted) + (date < Date() ? t(" · 已到期", " · Expired") : "")
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
