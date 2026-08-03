import json
import math
import struct
import unittest

import cv2
import numpy as np

from vision.depth_protocol import DepthProtocolError, parse_depth_frame


def make_fixture(
    *,
    header_updates=None,
    rgb=None,
    depth=None,
    confidence=None,
    truncate=0,
):
    rgb = np.array(
        [[[0, 0, 255], [0, 255, 0]], [[255, 0, 0], [255, 255, 255]]],
        dtype=np.uint8,
    ) if rgb is None else rgb
    depth = np.array([[500, 501], [502, 503]], dtype=np.uint16) if depth is None else depth
    confidence = np.array([[1, 2], [3, 4]], dtype=np.uint8) if confidence is None else confidence
    ok, encoded = cv2.imencode(".jpg", rgb)
    if not ok:
        raise RuntimeError("JPEG fixture encoding failed")
    rgb_bytes = encoded.tobytes()
    header = {
        "protocol_version": 1,
        "sequence": 7,
        "timestamp_ns": 123456,
        "device_name": "Duami",
        "orientation": "landscapeRight",
        "rgb_width": rgb.shape[1],
        "rgb_height": rgb.shape[0],
        "rgb_length": len(rgb_bytes),
        "depth_width": depth.shape[1],
        "depth_height": depth.shape[0],
        "depth_length": depth.nbytes,
        "confidence_length": confidence.nbytes,
        "intrinsics": [1.0, 2.0, 3.0, 4.0],
        "rgb_to_depth": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        "camera_transform": [
            1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
        ],
    }
    if header_updates:
        header.update(header_updates)
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload = (
        struct.pack(">I", len(header_bytes))
        + header_bytes
        + rgb_bytes
        + depth.astype("<u2", copy=False).tobytes()
        + confidence.tobytes()
    )
    return payload[:-truncate] if truncate else payload


class DepthProtocolTest(unittest.TestCase):
    def parse(self, payload, max_message_bytes=1_000_000):
        return parse_depth_frame(payload, received_monotonic=42.5, max_message_bytes=max_message_bytes)

    def assert_rejected(self, payload, message):
        with self.assertRaisesRegex(DepthProtocolError, message):
            self.parse(payload)

    def test_valid_2x2_fixture_parses_exact_buffers(self):
        frame = self.parse(make_fixture())
        self.assertEqual((frame.sequence, frame.timestamp_ns, frame.received_monotonic), (7, 123456, 42.5))
        self.assertEqual((frame.device_name, frame.orientation), ("Duami", "landscapeRight"))
        np.testing.assert_array_equal(frame.depth_mm, [[500, 501], [502, 503]])
        np.testing.assert_array_equal(frame.confidence, [[1, 2], [3, 4]])
        self.assertEqual(frame.rgb_bgr.shape, (2, 2, 3))
        self.assertTrue(frame.rgb_bgr.flags["OWNDATA"])
        self.assertTrue(frame.depth_mm.flags["OWNDATA"])
        self.assertTrue(frame.confidence.flags["OWNDATA"])

    def test_rejects_truncated_header_and_body(self):
        self.assert_rejected(b"\x00\x00\x00\x02{", "header")
        self.assert_rejected(make_fixture(truncate=1), "body")

    def test_rejects_oversize_message(self):
        payload = make_fixture()
        with self.assertRaisesRegex(DepthProtocolError, "message exceeds"):
            self.parse(payload, max_message_bytes=len(payload) - 1)

    def test_rejects_unsupported_version_and_missing_field(self):
        self.assert_rejected(make_fixture(header_updates={"protocol_version": 2}), "unsupported")
        self.assert_rejected(make_fixture(header_updates={"protocol_version": True}), "unsupported")
        payload = make_fixture()
        header_length = struct.unpack_from(">I", payload, 0)[0]
        header = json.loads(payload[4:4 + header_length])
        del header["orientation"]
        header_bytes = json.dumps(header).encode()
        rebuilt = struct.pack(">I", len(header_bytes)) + header_bytes + payload[4 + header_length:]
        self.assert_rejected(rebuilt, "missing")

    def test_rejects_invalid_dimensions_and_length_mismatch(self):
        self.assert_rejected(make_fixture(header_updates={"rgb_width": 0}), "dimensions")
        self.assert_rejected(make_fixture(header_updates={"depth_length": 7}), "depth length")
        self.assert_rejected(make_fixture(header_updates={"rgb_length": 1}), "body length")

    def test_rejects_invalid_jpeg_and_dimension_mismatch(self):
        payload = make_fixture()
        header_length = struct.unpack_from(">I", payload, 0)[0]
        header = json.loads(payload[4:4 + header_length])
        original_rgb_length = header["rgb_length"]
        header["rgb_length"] = 4
        header_bytes = json.dumps(header).encode()
        invalid_jpeg = struct.pack(">I", len(header_bytes)) + header_bytes + b"nope" + payload[4 + header_length + original_rgb_length:]
        self.assert_rejected(invalid_jpeg, "JPEG")

        header["rgb_length"] = 0
        header_bytes = json.dumps(header).encode()
        empty_jpeg = struct.pack(">I", len(header_bytes)) + header_bytes + payload[4 + header_length + original_rgb_length:]
        self.assert_rejected(empty_jpeg, "invalid JPEG")
        self.assert_rejected(make_fixture(header_updates={"rgb_width": 3}), "dimensions")

    def test_rejects_invalid_matrix_metadata(self):
        self.assert_rejected(make_fixture(header_updates={"intrinsics": [1.0] * 3}), "intrinsics")
        self.assert_rejected(make_fixture(header_updates={"rgb_to_depth": [math.inf] * 9}), "rgb_to_depth")
        self.assert_rejected(make_fixture(header_updates={"camera_transform": [1.0] * 15}), "camera_transform")

    def test_rejects_invalid_sequence_and_timestamp(self):
        self.assert_rejected(make_fixture(header_updates={"sequence": True}), "sequence")
        self.assert_rejected(make_fixture(header_updates={"sequence": -1}), "sequence")
        self.assert_rejected(make_fixture(header_updates={"timestamp_ns": "1"}), "timestamp_ns")
        self.assert_rejected(make_fixture(header_updates={"timestamp_ns": -1}), "timestamp_ns")


if __name__ == "__main__":
    unittest.main()
