import ARKit
import CoreImage
import Foundation
import UIKit

@MainActor
final class ARDepthCapture: NSObject, ObservableObject, ARSessionDelegate {
    @Published private(set) var isSupported: Bool
    @Published private(set) var isRunning = false
    @Published private(set) var previewImage: UIImage?
    @Published private(set) var centerDepthMm: Int?
    @Published private(set) var validDepthRatio = 0.0
    @Published private(set) var captureFPS = 0.0
    @Published private(set) var lastError: String?

    let session = ARSession()
    var onFrame: ((DepthFramePayload) -> Void)?

    nonisolated private let processor: ARFrameProcessor

    override init() {
        isSupported = ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
        processor = ARFrameProcessor(deviceName: UIDevice.current.name)
        super.init()
        session.delegate = self
    }

    func start() {
        guard isSupported else {
            lastError = "此设备不支持 ARKit sceneDepth；请使用带 LiDAR 的 iPhone Pro 真机。"
            return
        }
        guard !isRunning else { return }

        let configuration = ARWorldTrackingConfiguration()
        configuration.frameSemantics.insert(.sceneDepth)
        if ARWorldTrackingConfiguration.supportsFrameSemantics(.smoothedSceneDepth) {
            configuration.frameSemantics.insert(.smoothedSceneDepth)
        }
        configuration.worldAlignment = .gravity
        lastError = nil
        session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
        isRunning = true
    }

    func stop() {
        guard isRunning else { return }
        session.pause()
        processor.reset()
        isRunning = false
    }

    nonisolated func session(_ session: ARSession, didUpdate frame: ARFrame) {
        processor.accept(frame) { [weak self] result in
            Task { @MainActor in
                guard let self else { return }
                switch result {
                case let .success(processed):
                    self.previewImage = processed.previewImage
                    self.centerDepthMm = processed.centerDepthMm
                    self.validDepthRatio = processed.validDepthRatio
                    self.captureFPS = processed.captureFPS
                    self.lastError = nil
                    self.onFrame?(processed.payload)
                case let .failure(error):
                    self.lastError = error.localizedDescription
                }
            }
        }
    }

    nonisolated func session(_ session: ARSession, didFailWithError error: Error) {
        Task { @MainActor [weak self] in
            self?.lastError = "ARKit 采集失败：\(error.localizedDescription)"
            self?.isRunning = false
        }
    }

    nonisolated func sessionWasInterrupted(_ session: ARSession) {
        Task { @MainActor [weak self] in
            self?.lastError = "ARKit 会话已中断。"
            self?.isRunning = false
        }
    }
}

private enum ARFrameProcessingError: LocalizedError {
    case noDepth
    case unsupportedDepthFormat
    case imageEncoding

    var errorDescription: String? {
        switch self {
        case .noDepth: return "当前 AR 帧没有 LiDAR 深度。"
        case .unsupportedDepthFormat: return "ARKit 返回了不支持的深度格式。"
        case .imageEncoding: return "相机画面 JPEG 编码失败。"
        }
    }
}

private final class ARFrameProcessor: @unchecked Sendable {
    private let queue = DispatchQueue(label: "com.duamixu.tailhand.depth-processing", qos: .userInitiated)
    private let lock = NSLock()
    private let context = CIContext(options: [.cacheIntermediates: false])
    private let deviceName: String
    private var busy = false
    private var lastAcceptedTimestamp: TimeInterval = -.infinity
    private var lastCompletedTimestamp: TimeInterval?
    private var sequence: UInt64 = 0

    init(deviceName: String) {
        self.deviceName = deviceName
    }

    func accept(
        _ frame: ARFrame,
        completion: @escaping @Sendable (Result<ProcessedDepthFrame, Error>) -> Void
    ) {
        lock.lock()
        let sufficientlyNew = frame.timestamp - lastAcceptedTimestamp >= (1.0 / 15.0)
        guard !busy, sufficientlyNew else {
            lock.unlock()
            return
        }
        busy = true
        lastAcceptedTimestamp = frame.timestamp
        lock.unlock()

        queue.async { [weak self] in
            guard let self else { return }
            let result = Result { try self.process(frame) }
            self.lock.lock()
            self.busy = false
            self.lock.unlock()
            completion(result)
        }
    }

    func reset() {
        lock.lock()
        lastAcceptedTimestamp = -.infinity
        lastCompletedTimestamp = nil
        lock.unlock()
    }

    private func process(_ frame: ARFrame) throws -> ProcessedDepthFrame {
        guard let depthData = frame.smoothedSceneDepth ?? frame.sceneDepth else {
            throw ARFrameProcessingError.noDepth
        }
        let depthBuffer = depthData.depthMap
        guard CVPixelBufferGetPixelFormatType(depthBuffer) == kCVPixelFormatType_DepthFloat32 else {
            throw ARFrameProcessingError.unsupportedDepthFormat
        }

        let rgbWidth = 640
        let rgbHeight = 480
        let sourceImage = CIImage(cvPixelBuffer: frame.capturedImage)
        let image = aspectFill(sourceImage, width: rgbWidth, height: rgbHeight)
        guard let cgImage = context.createCGImage(image, from: image.extent) else {
            throw ARFrameProcessingError.imageEncoding
        }
        let preview = UIImage(cgImage: cgImage)
        guard let jpeg = preview.jpegData(compressionQuality: 0.55) else {
            throw ARFrameProcessingError.imageEncoding
        }

        let copied = copyDepth(depthBuffer, confidenceBuffer: depthData.confidenceMap)
        let sourceWidth = max(CVPixelBufferGetWidth(frame.capturedImage), 1)
        let sourceHeight = max(CVPixelBufferGetHeight(frame.capturedImage), 1)
        let xScale = Float(rgbWidth) / Float(sourceWidth)
        let yScale = Float(rgbHeight) / Float(sourceHeight)
        let intrinsics = frame.camera.intrinsics
        let compactIntrinsics: [Float] = [
            intrinsics.columns.0.x * xScale,
            intrinsics.columns.1.y * yScale,
            intrinsics.columns.2.x * xScale,
            intrinsics.columns.2.y * yScale,
        ]
        let rgbToDepth: [Float] = [
            Float(copied.width) / Float(rgbWidth), 0, 0,
            0, Float(copied.height) / Float(rgbHeight), 0,
            0, 0, 1,
        ]
        let transform = frame.camera.transform
        var cameraTransform: [Float] = []
        cameraTransform.reserveCapacity(16)
        for column in 0..<4 {
            for row in 0..<4 {
                cameraTransform.append(transform[column][row])
            }
        }

        lock.lock()
        let currentSequence = sequence
        sequence &+= 1
        let fps: Double
        if let previous = lastCompletedTimestamp, frame.timestamp > previous {
            fps = min(60, 1.0 / (frame.timestamp - previous))
        } else {
            fps = 0
        }
        lastCompletedTimestamp = frame.timestamp
        lock.unlock()

        let payload = DepthFramePayload(
            sequence: currentSequence,
            timestampNs: UInt64(max(0, frame.timestamp * 1_000_000_000)),
            deviceName: deviceName,
            rgbWidth: rgbWidth,
            rgbHeight: rgbHeight,
            jpeg: jpeg,
            depthWidth: copied.width,
            depthHeight: copied.height,
            depthMillimeters: copied.depth,
            confidence: copied.confidence,
            intrinsics: compactIntrinsics,
            rgbToDepth: rgbToDepth,
            cameraTransform: cameraTransform
        )
        return ProcessedDepthFrame(
            payload: payload,
            previewImage: preview,
            centerDepthMm: copied.centerDepthMm,
            validDepthRatio: copied.validRatio,
            captureFPS: fps
        )
    }

    private func aspectFill(_ image: CIImage, width: Int, height: Int) -> CIImage {
        let targetWidth = CGFloat(width)
        let targetHeight = CGFloat(height)
        let scale = max(targetWidth / image.extent.width, targetHeight / image.extent.height)
        let scaled = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        let crop = CGRect(
            x: scaled.extent.midX - targetWidth / 2,
            y: scaled.extent.midY - targetHeight / 2,
            width: targetWidth,
            height: targetHeight
        )
        return scaled.cropped(to: crop).transformed(
            by: CGAffineTransform(translationX: -crop.origin.x, y: -crop.origin.y)
        )
    }

    private func copyDepth(
        _ depthBuffer: CVPixelBuffer,
        confidenceBuffer: CVPixelBuffer?
    ) -> (depth: Data, confidence: Data, width: Int, height: Int, centerDepthMm: Int?, validRatio: Double) {
        CVPixelBufferLockBaseAddress(depthBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(depthBuffer, .readOnly) }
        if let confidenceBuffer { CVPixelBufferLockBaseAddress(confidenceBuffer, .readOnly) }
        defer {
            if let confidenceBuffer { CVPixelBufferUnlockBaseAddress(confidenceBuffer, .readOnly) }
        }

        let width = CVPixelBufferGetWidth(depthBuffer)
        let height = CVPixelBufferGetHeight(depthBuffer)
        let depthStride = CVPixelBufferGetBytesPerRow(depthBuffer) / MemoryLayout<Float32>.stride
        let depthBase = CVPixelBufferGetBaseAddress(depthBuffer)!.assumingMemoryBound(to: Float32.self)
        let confidenceStride = confidenceBuffer.map(CVPixelBufferGetBytesPerRow) ?? 0
        let confidenceBase = confidenceBuffer.flatMap(CVPixelBufferGetBaseAddress)?.assumingMemoryBound(to: UInt8.self)

        var depthValues = [UInt16](repeating: 0, count: width * height)
        var confidenceValues = [UInt8](repeating: 0, count: width * height)
        var validCount = 0
        var centerValues: [UInt16] = []
        centerValues.reserveCapacity(25)
        let centerX = width / 2
        let centerY = height / 2

        for y in 0..<height {
            let depthRow = depthBase.advanced(by: y * depthStride)
            let confidenceRow = confidenceBase?.advanced(by: y * confidenceStride)
            for x in 0..<width {
                let index = y * width + x
                let meters = depthRow[x]
                let millimeters: UInt16
                if meters.isFinite, meters > 0 {
                    millimeters = UInt16(clamping: Int((meters * 1000).rounded()))
                    validCount += 1
                } else {
                    millimeters = 0
                }
                depthValues[index] = millimeters.littleEndian
                confidenceValues[index] = confidenceRow?[x] ?? 0
                if abs(x - centerX) <= 2, abs(y - centerY) <= 2, millimeters > 0 {
                    centerValues.append(millimeters)
                }
            }
        }
        centerValues.sort()
        let centerDepth = centerValues.isEmpty ? nil : Int(centerValues[centerValues.count / 2])
        let ratio = width * height == 0 ? 0 : Double(validCount) / Double(width * height)
        let depthData = depthValues.withUnsafeBytes { Data($0) }
        return (depthData, Data(confidenceValues), width, height, centerDepth, ratio)
    }
}
