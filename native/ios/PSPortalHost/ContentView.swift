// SPDX-License-Identifier: GPL-3.0-only
import SwiftUI

@MainActor
struct ContentView: View {
    @ObservedObject var model: ProxyModel
    @State private var confirmForget = false
    @State private var showLicenses = false
    private let refresh = Timer.publish(every: 2, on: .main, in: .common).autoconnect()

    var body: some View {
        ZStack {
            // Keep a single stable screen. The prior navigation-container layout
            // hit a UIKit navigation-item ownership exception during launch.
            VStack(spacing: 0) {
                Text("PSPortal Host").font(.title2.bold()).padding()
                Form {
                    Section {
                        Label("Foreground only", systemImage: "iphone")
                            .font(.headline)
                        Text("Keep this app open and the device unlocked. Switching apps or locking stops the proxy. It never restarts automatically.")
                        Text("Development build. Physical-device and real Portal operation have not been validated.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    Section("Proxy") {
                        LabeledContent("Listener", value: model.state.rawValue)
                        Text(model.message).accessibilityIdentifier("proxyStatus")
                        if model.state == .running {
                            LabeledContent("Active outbound connections", value: String(model.activeConnections))
                        }
                        HStack {
                            Button("Start", action: model.start)
                                .buttonStyle(.borderedProminent).disabled(!model.canStart)
                                .accessibilityIdentifier("startProxy")
                            Button("Stop", role: .destructive) { model.stop() }
                                .buttonStyle(.bordered).disabled(!model.canStop)
                                .accessibilityIdentifier("stopProxy")
                        }
                    }
                    Section {
                        addressField("This device's Wi-Fi IPv4", text: $model.settings.listenHost)
                        TextField("Proxy port", text: $model.settings.listenPort)
                            .keyboardType(.numberPad)
                        TextField("Allowed Portal IPv4 addresses", text: $model.settings.allowedClients, axis: .vertical)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                            .keyboardType(.numbersAndPunctuation)
                    } header: {
                        Text("Trusted LAN")
                    } footer: {
                        Text("Use the Wi-Fi address shown in iOS Settings. Reserve the Portal's address in your router, then enter it here. Multiple client addresses may be separated by commas. Both devices must be on the same reachable trusted LAN. Never expose this port to the internet; the IP allowlist is not authentication.")
                    }
                    .disabled(!model.canEdit)
                    Section {
                        SecureField("HTTPS subscription URL", text: $model.settings.subscriptionURL)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                            .keyboardType(.URL).privacySensitive()
                            .accessibilityIdentifier("subscriptionURL")
                        Picker("Node selection", selection: $model.settings.selectionMode) {
                            ForEach(SelectionMode.allCases) { mode in Text(mode.title).tag(mode) }
                        }.pickerStyle(.menu)
                        if model.settings.selectionMode != .auto {
                            TextField("Exact node name", text: $model.settings.preferredNode)
                                .textInputAutocapitalization(.never).autocorrectionDisabled().privacySensitive()
                        }
                        Stepper("Idle pool timeout: \(model.settings.idleSeconds) seconds",
                                value: $model.settings.idleSeconds, in: 5...3600, step: 5)
                    } header: {
                        Text("Encrypted outbound")
                    } footer: {
                        Text("Starting opens the LAN listener. The first external HTTP or CONNECT request downloads the subscription and wakes the embedded Mihomo adapters. This is not a UDP or game-streaming relay.")
                    }
                    .disabled(!model.canEdit)
                    Section {
                        Toggle("Keep screen awake while running", isOn: $model.settings.keepAwake)
                            .onChange(of: model.settings.keepAwake) { _ in model.synchronizeIdleTimer() }
                    } footer: {
                        Text("Optional and off by default. Uses more battery. The previous idle-timer setting is restored on Stop or when the app becomes inactive. This does not enable background operation.")
                    }
                    Section {
                        Button("Save settings, excluding subscription URL", action: model.saveSettings).disabled(!model.canEdit)
                        Button("Forget saved configuration and clear fields", role: .destructive) { confirmForget = true }
                            .disabled(!model.canEdit)
                    } footer: {
                        Text("The subscription URL stays in memory and is never saved or logged. Re-enter it after relaunch. Save stores only the other settings in a private, file-protected folder marked for backup exclusion.")
                    }
                    Section("Portal setup") {
                        Text("In the Portal's network settings, set the manual HTTP proxy to this device's Wi-Fi IPv4 address and proxy port. Allow local-network access when iOS asks. Restore the Portal's proxy setting when you stop using this app.")
                        Text("If the Wi-Fi address changes, stop the proxy and update it here. Client isolation on some Wi-Fi networks prevents a Portal from reaching this device.")
                    }
                    Section("Open source") {
                        Button("Licenses and build limitations") { showLicenses = true }
                    }
                }
                .confirmationDialog("Remove saved settings and clear all fields?", isPresented: $confirmForget, titleVisibility: .visible) {
                    Button("Forget configuration", role: .destructive, action: model.forgetSettings)
                    Button("Cancel", role: .cancel) {}
                }
            }
            .sheet(isPresented: $showLicenses) { LicensesView() }
            // Opaque inactive-state cover reduces app-switcher disclosure. It is
            // not a guarantee against screenshots, recording, or OS snapshots.
            if !model.isActive {
                Color(.systemBackground).ignoresSafeArea()
                VStack(spacing: 12) {
                    Image(systemName: "lock.fill").font(.largeTitle)
                    Text("PSPortal Host").font(.title2)
                    Text("Configuration hidden").foregroundStyle(.secondary)
                }
            }
        }
        .onReceive(refresh) { _ in model.refreshStatus() }
    }

    private func addressField(_ title: String, text: Binding<String>) -> some View {
        TextField(title, text: text).keyboardType(.decimalPad)
            .textInputAutocapitalization(.never).autocorrectionDisabled()
    }
}

private struct LicensesView: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Licenses").font(.title2.bold())
                Spacer()
                Button("Done") { dismiss() }
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
