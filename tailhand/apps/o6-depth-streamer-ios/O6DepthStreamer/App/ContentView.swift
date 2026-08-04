import Network
import SwiftUI

struct ContentView: View {
    @StateObject private var capture = ARDepthCapture()
    @StateObject private var browser = MacServiceBrowser()
    @StateObject private var client = DepthStreamClient()
    @State private var selectedServiceID = ""
    @State private var useManualAddress = false
    @State private var manualHost = ""
    @State private var manualPort = "8766"
    @State private var pairingCode = ""
    @State private var inputError: String?

    var body: some View {
        GeometryReader { proxy in
            HStack(spacing: 0) {
                preview
                    .frame(width: max(proxy.size.width * 0.62, 420))

                Divider()

                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        titleBar
                        connectionControls
                        metrics
                        statusMessages
                    }
                    .padding(20)
                }
                .frame(maxWidth: .infinity)
                .background(Color(uiColor: .secondarySystemBackground))
            }
        }
        .onAppear {
            capture.onFrame = { payload in client.submit(payload) }
        }
        .onChange(of: browser.services) { _, services in
            if selectedServiceID.isEmpty, let first = services.first {
                selectedServiceID = first.id
            }
        }
        .onChange(of: client.state) { _, state in
            if case .failed = state {
                capture.stop()
            }
        }
        .onDisappear {
            capture.stop()
            client.disconnect()
            browser.stop()
        }
    }

    private var preview: some View {
        ZStack {
            Color.black
            if let image = capture.previewImage {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                VStack(spacing: 10) {
                    Image(systemName: capture.isSupported ? "camera.metering.center.weighted" : "sensor.tag.radiowaves.forward")
                        .font(.system(size: 38, weight: .light))
                    Text(capture.isSupported ? "LiDAR 待机" : "此设备没有 sceneDepth")
                        .font(.headline)
                }
                .foregroundStyle(.secondary)
            }

            reticle
            VStack {
                HStack {
                    statusBadge
                    Spacer()
                }
                Spacer()
                HStack(alignment: .bottom) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("中心距离")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(centerDistanceText)
                            .font(.system(size: 30, weight: .semibold, design: .rounded))
                    }
                    Spacer()
                    Text(String(format: "%.1f FPS", capture.captureFPS))
                        .font(.system(.body, design: .monospaced))
                }
                .padding(14)
                .background(.black.opacity(0.58))
            }
            .padding(16)
        }
        .clipped()
    }

    private var reticle: some View {
        ZStack {
            Circle().stroke(.white.opacity(0.85), lineWidth: 1.5).frame(width: 54, height: 54)
            Rectangle().fill(.white).frame(width: 18, height: 1)
            Rectangle().fill(.white).frame(width: 1, height: 18)
        }
        .shadow(color: .black.opacity(0.6), radius: 2)
    }

    private var statusBadge: some View {
        HStack(spacing: 7) {
            Circle()
                .fill(client.isStreaming ? Color.green : client.isActive ? Color.yellow : Color.gray)
                .frame(width: 8, height: 8)
            Text(client.state.label)
                .font(.subheadline.weight(.medium))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(.black.opacity(0.62), in: RoundedRectangle(cornerRadius: 6))
    }

    private var titleBar: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("O6 Depth Streamer")
                    .font(.title2.weight(.semibold))
                Text("iPhone 17 Pro · LiDAR")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Image(systemName: "viewfinder")
                .font(.title2)
                .foregroundStyle(.blue)
        }
    }

    private var connectionControls: some View {
        VStack(alignment: .leading, spacing: 12) {
            Toggle("手动输入 Mac 地址", isOn: $useManualAddress)
                .disabled(client.isActive)

            if useManualAddress {
                HStack {
                    TextField("Mac IP", text: $manualHost)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.numbersAndPunctuation)
                    TextField("端口", text: $manualPort)
                        .keyboardType(.numberPad)
                        .frame(width: 84)
                }
                .textFieldStyle(.roundedBorder)
            } else {
                Picker("Mac 接收端", selection: $selectedServiceID) {
                    if browser.services.isEmpty {
                        Text(browser.isSearching ? "正在搜索…" : "尚未搜索").tag("")
                    }
                    ForEach(browser.services) { service in
                        Text(service.name).tag(service.id)
                    }
                }
                .pickerStyle(.menu)
                .disabled(client.isActive)
            }

            TextField("6 位配对码", text: $pairingCode)
                .keyboardType(.numberPad)
                .textContentType(.oneTimeCode)
                .textFieldStyle(.roundedBorder)
                .onChange(of: pairingCode) { _, value in
                    pairingCode = String(value.filter(\.isNumber).prefix(6))
                }
                .disabled(client.isActive)

            Button(action: toggleConnection) {
                Label(
                    client.isActive ? "断开" : "连接",
                    systemImage: client.isActive ? "xmark.circle.fill" : "link.circle.fill"
                )
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .tint(client.isActive ? .red : .blue)
            .controlSize(.large)
        }
    }

    private var metrics: some View {
        VStack(spacing: 0) {
            metricRow("发送帧率", value: String(format: "%.1f FPS", client.sentFPS), icon: "speedometer")
            Divider()
            metricRow("网络 RTT", value: client.roundTripMs.map { String(format: "%.0f ms", $0) } ?? "—", icon: "network")
            Divider()
            metricRow("发送耗时", value: String(format: "%.1f ms", client.sendDurationMs), icon: "arrow.up.circle")
            Divider()
            metricRow("有效深度", value: String(format: "%.0f%%", capture.validDepthRatio * 100), icon: "dot.scope")
        }
        .background(Color(uiColor: .tertiarySystemBackground), in: RoundedRectangle(cornerRadius: 6))
    }

    private var statusMessages: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(messages, id: \.self) { message in
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(.footnote)
                    .foregroundStyle(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var messages: [String] {
        [inputError, client.errorMessage, capture.lastError, browser.lastError].compactMap { $0 }
    }

    private var centerDistanceText: String {
        guard let millimeters = capture.centerDepthMm else { return "—" }
        return String(format: "%.1f cm", Double(millimeters) / 10)
    }

    private func metricRow(_ title: String, value: String, icon: String) -> some View {
        HStack {
            Label(title, systemImage: icon)
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .font(.system(.body, design: .monospaced).weight(.medium))
        }
        .padding(.horizontal, 12)
        .frame(height: 43)
    }

    private func toggleConnection() {
        inputError = nil
        if client.isActive {
            capture.stop()
            client.disconnect()
            return
        }
        guard pairingCode.count == 6 else {
            inputError = "请输入 Mac 网页显示的 6 位配对码。"
            return
        }
        browser.start()

        let endpoint: NWEndpoint?
        if useManualAddress {
            endpoint = MacServiceBrowser.manualEndpoint(host: manualHost, port: manualPort)
            if endpoint == nil { inputError = "Mac IP 或端口无效。" }
        } else {
            endpoint = browser.services.first(where: { $0.id == selectedServiceID })?.endpoint
            if endpoint == nil { inputError = "正在搜索 Mac；发现后再次点连接。" }
        }
        guard let endpoint else { return }
        capture.start()
        client.connect(to: endpoint, pairingCode: pairingCode)
    }
}
