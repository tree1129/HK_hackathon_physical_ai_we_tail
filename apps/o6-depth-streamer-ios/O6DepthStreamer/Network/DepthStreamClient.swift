import Foundation
import Network
import UIKit

@MainActor
final class DepthStreamClient: ObservableObject {
    enum State: Equatable {
        case disconnected
        case connecting
        case pairing
        case streaming
        case failed(String)

        var label: String {
            switch self {
            case .disconnected: return "未连接"
            case .connecting: return "正在连接"
            case .pairing: return "正在配对"
            case .streaming: return "正在传输"
            case .failed: return "连接失败"
            }
        }
    }

    @Published private(set) var state: State = .disconnected
    @Published private(set) var sentFPS = 0.0
    @Published private(set) var sendDurationMs = 0.0
    @Published private(set) var roundTripMs: Double?

    var isActive: Bool {
        switch state {
        case .connecting, .pairing, .streaming: return true
        case .disconnected, .failed: return false
        }
    }

    var isStreaming: Bool { state == .streaming }
    var errorMessage: String? {
        if case let .failed(message) = state { return message }
        return nil
    }

    private lazy var engine = DepthStreamEngine(
        onState: { [weak self] state in
            Task { @MainActor in self?.state = state }
        },
        onMetrics: { [weak self] fps, duration, rtt in
            Task { @MainActor in
                self?.sentFPS = fps
                self?.sendDurationMs = duration
                self?.roundTripMs = rtt
            }
        }
    )

    func connect(to endpoint: NWEndpoint, pairingCode: String) {
        state = .connecting
        engine.connect(to: endpoint, pairingCode: pairingCode, deviceName: UIDevice.current.name)
    }

    func submit(_ payload: DepthFramePayload) {
        engine.submit(payload)
    }

    func disconnect() {
        engine.disconnect()
        state = .disconnected
        sentFPS = 0
        sendDurationMs = 0
        roundTripMs = nil
    }
}

private final class DepthStreamEngine: @unchecked Sendable {
    private let queue = DispatchQueue(label: "com.duamixu.tailhand.websocket", qos: .userInitiated)
    private let onState: @Sendable (DepthStreamClient.State) -> Void
    private let onMetrics: @Sendable (Double, Double, Double?) -> Void
    private var connection: NWConnection?
    private var acknowledged = false
    private var frameInFlight = false
    private var pendingPacket: Data?
    private var sentInWindow = 0
    private var windowStart = DispatchTime.now().uptimeNanoseconds
    private var fps = 0.0
    private var sendDurationMs = 0.0
    private var roundTripMs: Double?
    private var pingSentAt: UInt64?
    private var pingTimer: DispatchSourceTimer?

    init(
        onState: @escaping @Sendable (DepthStreamClient.State) -> Void,
        onMetrics: @escaping @Sendable (Double, Double, Double?) -> Void
    ) {
        self.onState = onState
        self.onMetrics = onMetrics
    }

    func connect(to endpoint: NWEndpoint, pairingCode: String, deviceName: String) {
        queue.async { [weak self] in
            guard let self else { return }
            self.cancelCurrent()
            let webSocket = NWProtocolWebSocket.Options()
            webSocket.autoReplyPing = true
            let parameters = NWParameters.tcp
            parameters.defaultProtocolStack.applicationProtocols.insert(webSocket, at: 0)
            parameters.includePeerToPeer = true
            let connection = NWConnection(to: endpoint, using: parameters)
            self.connection = connection
            self.onState(.connecting)
            connection.stateUpdateHandler = { [weak self, weak connection] state in
                guard let self, let connection, self.connection === connection else { return }
                switch state {
                case .ready:
                    self.onState(.pairing)
                    self.sendHello(pairingCode: pairingCode, deviceName: deviceName, on: connection)
                    self.receiveNext(on: connection)
                case let .failed(error):
                    self.fail("\(error.localizedDescription)")
                case .cancelled:
                    break
                default:
                    break
                }
            }
            connection.start(queue: self.queue)
        }
    }

    func submit(_ payload: DepthFramePayload) {
        queue.async { [weak self] in
            guard let self else { return }
            do {
                let packet = try DepthPacketEncoder.encode(payload)
                guard self.acknowledged else {
                    self.pendingPacket = packet
                    return
                }
                if self.frameInFlight {
                    self.pendingPacket = packet
                } else {
                    self.send(packet)
                }
            } catch {
                self.fail("帧编码失败：\(error.localizedDescription)")
            }
        }
    }

    func disconnect() {
        queue.async { [weak self] in self?.cancelCurrent() }
    }

    private func sendHello(pairingCode: String, deviceName: String, on connection: NWConnection) {
        let hello: [String: Any] = [
            "type": "hello",
            "protocol_version": 1,
            "pairing_code": pairingCode,
            "device_name": deviceName,
            "supports_scene_depth": true,
        ]
        guard JSONSerialization.isValidJSONObject(hello),
              let data = try? JSONSerialization.data(withJSONObject: hello) else {
            fail("无法生成配对消息。")
            return
        }
        connection.send(
            content: data,
            contentContext: webSocketContext(opcode: .text, identifier: "hello"),
            isComplete: true,
            completion: .contentProcessed { [weak self] error in
                if let error { self?.fail("配对消息发送失败：\(error.localizedDescription)") }
            }
        )
    }

    private func receiveNext(on connection: NWConnection) {
        connection.receiveMessage { [weak self, weak connection] data, context, _, error in
            guard let self, let connection, self.connection === connection else { return }
            if let error {
                self.fail(error.localizedDescription)
                return
            }
            if let metadata = context?.protocolMetadata(
                definition: NWProtocolWebSocket.definition
            ) as? NWProtocolWebSocket.Metadata {
                if metadata.opcode == .pong, let sent = self.pingSentAt {
                    let now = DispatchTime.now().uptimeNanoseconds
                    self.roundTripMs = Double(now - sent) / 1_000_000
                    self.pingSentAt = nil
                    self.publishMetrics()
                } else if metadata.opcode == .text, let data {
                    self.handleText(data)
                } else if metadata.opcode == .close {
                    self.fail("Mac 已关闭连接。")
                    return
                }
            } else if let data {
                self.handleText(data)
            }
            self.receiveNext(on: connection)
        }
    }

    private func handleText(_ data: Data) {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = object["type"] as? String else { return }
        if type == "hello_ack" {
            guard object["accepted"] as? Bool == true,
                  object["protocol_version"] as? Int == 1 else {
                fail("配对码错误、协议不兼容，或 Mac 已连接另一台 iPhone。")
                return
            }
            acknowledged = true
            onState(.streaming)
            startPingTimer()
            if let pendingPacket {
                self.pendingPacket = nil
                send(pendingPacket)
            }
        } else if type == "error" {
            fail((object["message"] as? String) ?? "Mac 拒绝了连接。")
        }
    }

    private func send(_ packet: Data) {
        guard let connection, acknowledged, !frameInFlight else {
            pendingPacket = packet
            return
        }
        frameInFlight = true
        let started = DispatchTime.now().uptimeNanoseconds
        connection.send(
            content: packet,
            contentContext: webSocketContext(opcode: .binary, identifier: "depth-frame"),
            isComplete: true,
            completion: .contentProcessed { [weak self] error in
                guard let self else { return }
                self.frameInFlight = false
                if let error {
                    self.fail(error.localizedDescription)
                    return
                }
                let now = DispatchTime.now().uptimeNanoseconds
                self.sendDurationMs = Double(now - started) / 1_000_000
                self.sentInWindow += 1
                let elapsed = Double(now - self.windowStart) / 1_000_000_000
                if elapsed >= 1 {
                    self.fps = Double(self.sentInWindow) / elapsed
                    self.sentInWindow = 0
                    self.windowStart = now
                }
                self.publishMetrics()
                if let pending = self.pendingPacket {
                    self.pendingPacket = nil
                    self.send(pending)
                }
            }
        )
    }

    private func startPingTimer() {
        pingTimer?.cancel()
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + 2, repeating: 2)
        timer.setEventHandler { [weak self] in self?.sendPing() }
        pingTimer = timer
        timer.resume()
    }

    private func sendPing() {
        guard let connection, acknowledged, pingSentAt == nil else { return }
        pingSentAt = DispatchTime.now().uptimeNanoseconds
        connection.send(
            content: Data(),
            contentContext: webSocketContext(opcode: .ping, identifier: "ping"),
            isComplete: true,
            completion: .contentProcessed { [weak self] error in
                if let error { self?.fail(error.localizedDescription) }
            }
        )
    }

    private func publishMetrics() {
        onMetrics(fps, sendDurationMs, roundTripMs)
    }

    private func fail(_ message: String) {
        onState(.failed(message))
        cancelCurrent(publishState: false)
    }

    private func cancelCurrent(publishState: Bool = true) {
        pingTimer?.cancel()
        pingTimer = nil
        connection?.stateUpdateHandler = nil
        connection?.cancel()
        connection = nil
        acknowledged = false
        frameInFlight = false
        pendingPacket = nil
        pingSentAt = nil
        if publishState { onState(.disconnected) }
    }

    private func webSocketContext(
        opcode: NWProtocolWebSocket.Opcode,
        identifier: String
    ) -> NWConnection.ContentContext {
        let metadata = NWProtocolWebSocket.Metadata(opcode: opcode)
        return NWConnection.ContentContext(identifier: identifier, metadata: [metadata])
    }
}
