import XCTest
@testable import O6DepthStreamer

final class DepthPacketEncoderTests: XCTestCase {
    func testPacketUsesBigEndianHeaderAndOrderedBodies() throws {
        let payload = fixture()
        let packet = try DepthPacketEncoder.encode(payload)
        let headerLength = packet.prefix(4).reduce(0) { ($0 << 8) | Int($1) }

        XCTAssertGreaterThan(headerLength, 0)
        XCTAssertEqual(packet.suffix(8), Data([1, 2, 0x90, 0x01, 0xF4, 0x01, 2, 1]))

        let headerData = packet.subdata(in: 4..<(4 + headerLength))
        let header = try XCTUnwrap(JSONSerialization.jsonObject(with: headerData) as? [String: Any])
        XCTAssertEqual(header["protocol_version"] as? Int, 1)
        XCTAssertEqual(header["sequence"] as? Int, 7)
        XCTAssertEqual(header["depth_unit"] as? String, "millimeters")
        XCTAssertEqual(header["rgb_length"] as? Int, 2)
        XCTAssertEqual(header["depth_length"] as? Int, 4)
    }

    func testEncoderRejectsMismatchedDepthLength() {
        let original = fixture()
        let invalid = DepthFramePayload(
            sequence: original.sequence,
            timestampNs: original.timestampNs,
            deviceName: original.deviceName,
            rgbWidth: original.rgbWidth,
            rgbHeight: original.rgbHeight,
            jpeg: original.jpeg,
            depthWidth: original.depthWidth,
            depthHeight: original.depthHeight,
            depthMillimeters: Data([0]),
            confidence: original.confidence,
            intrinsics: original.intrinsics,
            rgbToDepth: original.rgbToDepth,
            cameraTransform: original.cameraTransform
        )
        XCTAssertThrowsError(try DepthPacketEncoder.encode(invalid)) { error in
            XCTAssertEqual(error as? DepthPacketEncoderError, .invalidDepthLength)
        }
    }

    func testEncoderRejectsNonFiniteMatrix() {
        let original = fixture()
        let invalid = DepthFramePayload(
            sequence: original.sequence,
            timestampNs: original.timestampNs,
            deviceName: original.deviceName,
            rgbWidth: original.rgbWidth,
            rgbHeight: original.rgbHeight,
            jpeg: original.jpeg,
            depthWidth: original.depthWidth,
            depthHeight: original.depthHeight,
            depthMillimeters: original.depthMillimeters,
            confidence: original.confidence,
            intrinsics: [.nan, 1, 0, 0],
            rgbToDepth: original.rgbToDepth,
            cameraTransform: original.cameraTransform
        )
        XCTAssertThrowsError(try DepthPacketEncoder.encode(invalid))
    }

    private func fixture() -> DepthFramePayload {
        DepthFramePayload(
            sequence: 7,
            timestampNs: 9,
            deviceName: "Duami",
            rgbWidth: 2,
            rgbHeight: 2,
            jpeg: Data([1, 2]),
            depthWidth: 2,
            depthHeight: 1,
            depthMillimeters: Data([0x90, 0x01, 0xF4, 0x01]),
            confidence: Data([2, 1]),
            intrinsics: [1, 1, 0, 0],
            rgbToDepth: [1, 0, 0, 0, 1, 0, 0, 0, 1],
            cameraTransform: Array(repeating: 0, count: 16)
        )
    }
}

