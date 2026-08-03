import Foundation

enum DepthPacketEncoderError: LocalizedError, Equatable {
    case invalidDimensions
    case invalidJPEG
    case invalidDepthLength
    case invalidConfidenceLength
    case invalidMatrix(name: String, expected: Int)
    case headerTooLarge

    var errorDescription: String? {
        switch self {
        case .invalidDimensions: return "Frame dimensions must be positive."
        case .invalidJPEG: return "JPEG data is empty."
        case .invalidDepthLength: return "Depth data size does not match its dimensions."
        case .invalidConfidenceLength: return "Confidence data size does not match its dimensions."
        case let .invalidMatrix(name, expected): return "\(name) must contain \(expected) finite values."
        case .headerTooLarge: return "Frame header is too large."
        }
    }
}

enum DepthPacketEncoder {
    private struct Header: Encodable {
        let protocolVersion: Int
        let sequence: UInt64
        let timestampNs: UInt64
        let deviceName: String
        let orientation: String
        let rgbWidth: Int
        let rgbHeight: Int
        let rgbLength: Int
        let depthWidth: Int
        let depthHeight: Int
        let depthLength: Int
        let confidenceLength: Int
        let intrinsics: [Float]
        let rgbToDepth: [Float]
        let cameraTransform: [Float]
        let depthUnit: String

        enum CodingKeys: String, CodingKey {
            case protocolVersion = "protocol_version"
            case sequence
            case timestampNs = "timestamp_ns"
            case deviceName = "device_name"
            case orientation
            case rgbWidth = "rgb_width"
            case rgbHeight = "rgb_height"
            case rgbLength = "rgb_length"
            case depthWidth = "depth_width"
            case depthHeight = "depth_height"
            case depthLength = "depth_length"
            case confidenceLength = "confidence_length"
            case intrinsics
            case rgbToDepth = "rgb_to_depth"
            case cameraTransform = "camera_transform"
            case depthUnit = "depth_unit"
        }
    }

    static func encode(_ payload: DepthFramePayload) throws -> Data {
        guard payload.rgbWidth > 0, payload.rgbHeight > 0,
              payload.depthWidth > 0, payload.depthHeight > 0 else {
            throw DepthPacketEncoderError.invalidDimensions
        }
        guard !payload.jpeg.isEmpty else { throw DepthPacketEncoderError.invalidJPEG }

        let (pixelCount, overflow) = payload.depthWidth.multipliedReportingOverflow(by: payload.depthHeight)
        guard !overflow else { throw DepthPacketEncoderError.invalidDimensions }
        let (depthBytes, bytesOverflow) = pixelCount.multipliedReportingOverflow(by: 2)
        guard !bytesOverflow, payload.depthMillimeters.count == depthBytes else {
            throw DepthPacketEncoderError.invalidDepthLength
        }
        guard payload.confidence.count == pixelCount else {
            throw DepthPacketEncoderError.invalidConfidenceLength
        }
        try validate(payload.intrinsics, name: "intrinsics", count: 4)
        try validate(payload.rgbToDepth, name: "rgb_to_depth", count: 9)
        try validate(payload.cameraTransform, name: "camera_transform", count: 16)

        let header = Header(
            protocolVersion: 1,
            sequence: payload.sequence,
            timestampNs: payload.timestampNs,
            deviceName: payload.deviceName,
            orientation: payload.orientation,
            rgbWidth: payload.rgbWidth,
            rgbHeight: payload.rgbHeight,
            rgbLength: payload.jpeg.count,
            depthWidth: payload.depthWidth,
            depthHeight: payload.depthHeight,
            depthLength: payload.depthMillimeters.count,
            confidenceLength: payload.confidence.count,
            intrinsics: payload.intrinsics,
            rgbToDepth: payload.rgbToDepth,
            cameraTransform: payload.cameraTransform,
            depthUnit: "millimeters"
        )
        let headerData = try JSONEncoder().encode(header)
        guard headerData.count <= Int(UInt32.max) else { throw DepthPacketEncoderError.headerTooLarge }

        var headerLength = UInt32(headerData.count).bigEndian
        var packet = Data(bytes: &headerLength, count: MemoryLayout<UInt32>.size)
        packet.reserveCapacity(4 + headerData.count + payload.jpeg.count + depthBytes + pixelCount)
        packet.append(headerData)
        packet.append(payload.jpeg)
        packet.append(payload.depthMillimeters)
        packet.append(payload.confidence)
        return packet
    }

    private static func validate(_ values: [Float], name: String, count: Int) throws {
        guard values.count == count, values.allSatisfy(\.isFinite) else {
            throw DepthPacketEncoderError.invalidMatrix(name: name, expected: count)
        }
    }
}

