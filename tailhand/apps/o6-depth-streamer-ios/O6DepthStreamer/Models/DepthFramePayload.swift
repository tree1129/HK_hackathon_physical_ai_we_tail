import Foundation
import UIKit

struct DepthFramePayload: Sendable {
    let sequence: UInt64
    let timestampNs: UInt64
    let deviceName: String
    let orientation: String
    let rgbWidth: Int
    let rgbHeight: Int
    let jpeg: Data
    let depthWidth: Int
    let depthHeight: Int
    let depthMillimeters: Data
    let confidence: Data
    let intrinsics: [Float]
    let rgbToDepth: [Float]
    let cameraTransform: [Float]

    init(
        sequence: UInt64,
        timestampNs: UInt64,
        deviceName: String,
        orientation: String = "landscapeRight",
        rgbWidth: Int,
        rgbHeight: Int,
        jpeg: Data,
        depthWidth: Int,
        depthHeight: Int,
        depthMillimeters: Data,
        confidence: Data,
        intrinsics: [Float],
        rgbToDepth: [Float],
        cameraTransform: [Float]
    ) {
        self.sequence = sequence
        self.timestampNs = timestampNs
        self.deviceName = deviceName
        self.orientation = orientation
        self.rgbWidth = rgbWidth
        self.rgbHeight = rgbHeight
        self.jpeg = jpeg
        self.depthWidth = depthWidth
        self.depthHeight = depthHeight
        self.depthMillimeters = depthMillimeters
        self.confidence = confidence
        self.intrinsics = intrinsics
        self.rgbToDepth = rgbToDepth
        self.cameraTransform = cameraTransform
    }
}

struct ProcessedDepthFrame: @unchecked Sendable {
    let payload: DepthFramePayload
    let previewImage: UIImage
    let centerDepthMm: Int?
    let validDepthRatio: Double
    let captureFPS: Double
}

