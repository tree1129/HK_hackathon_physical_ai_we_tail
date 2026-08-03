from __future__ import annotations

from dataclasses import dataclass
import json
import math
import struct

import cv2
import numpy as np


PROTOCOL_VERSION = 1


class DepthProtocolError(ValueError):
    """Raised when an incoming depth frame does not satisfy the wire contract."""


@dataclass(frozen=True)
class DepthFrame:
    sequence: int
    timestamp_ns: int
    received_monotonic: float
    device_name: str
    orientation: str
    rgb_bgr: np.ndarray
    depth_mm: np.ndarray
    confidence: np.ndarray
    intrinsics: tuple[float, float, float, float]
    rgb_to_depth: tuple[float, ...]
    camera_transform: tuple[float, ...]


_REQUIRED_FIELDS = (
    "protocol_version", "sequence", "timestamp_ns", "device_name", "orientation",
    "rgb_width", "rgb_height", "rgb_length", "depth_width", "depth_height",
    "depth_length", "confidence_length", "intrinsics", "rgb_to_depth",
    "camera_transform",
)


def parse_depth_frame(
    payload: bytes,
    *,
    received_monotonic: float,
    max_message_bytes: int,
) -> DepthFrame:
    """Parse one complete version-1 RGB-D datagram without retaining its buffer."""
    if len(payload) > max_message_bytes:
        raise DepthProtocolError("message exceeds maximum size")
    if len(payload) < 5:
        raise DepthProtocolError("message is too short")

    header_length = struct.unpack_from(">I", payload, 0)[0]
    if header_length < 2 or header_length > len(payload) - 4:
        raise DepthProtocolError("invalid header length")
    header_end = 4 + header_length
    try:
        header = json.loads(payload[4:header_end].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DepthProtocolError("invalid JSON header") from None
    if not isinstance(header, dict):
        raise DepthProtocolError("header must be an object")

    for field in _REQUIRED_FIELDS:
        if field not in header:
            raise DepthProtocolError(f"missing required field: {field}")
    if isinstance(header["protocol_version"], bool) or header["protocol_version"] != PROTOCOL_VERSION:
        raise DepthProtocolError("unsupported protocol version")

    sequence = _non_negative_integer(header["sequence"], "sequence")
    timestamp_ns = _non_negative_integer(header["timestamp_ns"], "timestamp_ns")
    rgb_width = _positive_integer(header["rgb_width"], "RGB dimensions")
    rgb_height = _positive_integer(header["rgb_height"], "RGB dimensions")
    depth_width = _positive_integer(header["depth_width"], "depth dimensions")
    depth_height = _positive_integer(header["depth_height"], "depth dimensions")
    rgb_length = _non_negative_integer(header["rgb_length"], "RGB length")
    depth_length = _non_negative_integer(header["depth_length"], "depth length")
    confidence_length = _non_negative_integer(header["confidence_length"], "confidence length")
    depth_pixels = depth_width * depth_height
    if depth_length != depth_pixels * 2:
        raise DepthProtocolError("invalid depth length")
    if confidence_length != depth_pixels:
        raise DepthProtocolError("invalid confidence length")

    body_length = rgb_length + depth_length + confidence_length
    if len(payload) - header_end != body_length:
        raise DepthProtocolError("invalid body length")

    intrinsics = _matrix(header["intrinsics"], 4, "intrinsics")
    rgb_to_depth = _matrix(header["rgb_to_depth"], 9, "rgb_to_depth")
    camera_transform = _matrix(header["camera_transform"], 16, "camera_transform")
    device_name = _string(header["device_name"], "device_name")
    orientation = _string(header["orientation"], "orientation")

    rgb_end = header_end + rgb_length
    depth_end = rgb_end + depth_length
    if rgb_length == 0:
        raise DepthProtocolError("invalid JPEG image")
    try:
        rgb_bgr = cv2.imdecode(
            np.frombuffer(payload[header_end:rgb_end], dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
    except cv2.error:
        raise DepthProtocolError("invalid JPEG image") from None
    if rgb_bgr is None:
        raise DepthProtocolError("invalid JPEG image")
    if rgb_bgr.shape != (rgb_height, rgb_width, 3):
        raise DepthProtocolError("JPEG dimensions do not match header")

    depth_mm = np.frombuffer(payload[rgb_end:depth_end], dtype="<u2").reshape(depth_height, depth_width).copy()
    confidence = np.frombuffer(payload[depth_end:], dtype=np.uint8).reshape(depth_height, depth_width).copy()
    return DepthFrame(
        sequence=sequence,
        timestamp_ns=timestamp_ns,
        received_monotonic=received_monotonic,
        device_name=device_name,
        orientation=orientation,
        rgb_bgr=rgb_bgr.copy(),
        depth_mm=depth_mm,
        confidence=confidence,
        intrinsics=(intrinsics[0], intrinsics[1], intrinsics[2], intrinsics[3]),
        rgb_to_depth=rgb_to_depth,
        camera_transform=camera_transform,
    )


def _non_negative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DepthProtocolError(f"invalid {field}")
    return value


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DepthProtocolError(f"invalid {field}")
    return value


def _matrix(value: object, length: int, field: str) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise DepthProtocolError(f"invalid {field}")
    try:
        matrix = tuple(float(item) for item in value)
    except (TypeError, ValueError, OverflowError):
        raise DepthProtocolError(f"invalid {field}") from None
    if not all(math.isfinite(item) for item in matrix):
        raise DepthProtocolError(f"invalid {field}")
    return matrix


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise DepthProtocolError(f"invalid {field}")
    return value
