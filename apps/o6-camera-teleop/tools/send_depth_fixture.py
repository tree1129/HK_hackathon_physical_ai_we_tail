#!/usr/bin/env python3
"""Send deterministic RGB-D frames to the O6 depth receiver."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import math
import re
import struct
import sys
import time

import cv2
import numpy as np
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException


PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1_572_864
MAX_FRAMES = 10_000
MAX_FPS = 20.0
DEVICE_NAME = "synthetic-depth"
RGB_WIDTH, RGB_HEIGHT = 640, 480
DEPTH_WIDTH, DEPTH_HEIGHT = 256, 192
_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def _bounded_int(name: str, minimum: int, maximum: int):
    def parse(value: str) -> int:
        try:
            parsed = int(value, 10)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{name} must be an integer") from None
        if not minimum <= parsed <= maximum:
            raise argparse.ArgumentTypeError(
                f"{name} must be between {minimum} and {maximum}"
            )
        return parsed

    return parse


def _fps(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("fps must be a number") from None
    if not math.isfinite(parsed) or not 0.1 <= parsed <= MAX_FPS:
        raise argparse.ArgumentTypeError(f"fps must be between 0.1 and {MAX_FPS:g}")
    return parsed


def _pairing_code(value: str) -> str:
    if len(value) != 6 or not value.isascii() or not value.isdigit():
        raise argparse.ArgumentTypeError("pairing-code must contain exactly 6 ASCII digits")
    return value


def _host(value: str) -> str:
    host = value.strip()
    if not host or len(host) > 253 or host != value:
        raise argparse.ArgumentTypeError("host must be a nonempty hostname or IP address")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if any(character.isspace() or ord(character) < 33 for character in host):
        raise argparse.ArgumentTypeError("host must not contain whitespace")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    if any(character in host for character in "/:@?#[]"):
        raise argparse.ArgumentTypeError("host must not include a URL scheme, port, or path")
    labels = host.rstrip(".").split(".")
    if not labels or any(not _HOST_LABEL.fullmatch(label) for label in labels):
        raise argparse.ArgumentTypeError("host is not a valid hostname or IP address")
    return host


def _uri_host(host: str) -> str:
    try:
        return f"[{host}]" if ipaddress.ip_address(host).version == 6 else host
    except ValueError:
        return host


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send high-contrast synthetic RGB-D frames to the O6 Mac receiver."
    )
    parser.add_argument("--host", type=_host, default="127.0.0.1")
    parser.add_argument("--port", type=_bounded_int("port", 1, 65_535), default=8766)
    parser.add_argument("--pairing-code", required=True, type=_pairing_code)
    parser.add_argument(
        "--depth-mm",
        required=True,
        type=_bounded_int("depth-mm", 1, 65_535),
    )
    parser.add_argument(
        "--frames",
        type=_bounded_int("frames", 1, MAX_FRAMES),
        default=30,
    )
    parser.add_argument(
        "--lead-blank-frames",
        type=_bounded_int("lead-blank-frames", 0, MAX_FRAMES),
        default=0,
        help="send this many blank background frames before the target appears",
    )
    parser.add_argument("--fps", type=_fps, default=15.0)
    return parser


def _fixture_buffers(
    depth_mm: int,
    *,
    object_visible: bool = True,
) -> tuple[bytes, np.ndarray, np.ndarray]:
    rgb = np.zeros((RGB_HEIGHT, RGB_WIDTH, 3), dtype=np.uint8)
    if object_visible:
        cv2.rectangle(rgb, (225, 135), (415, 345), (245, 245, 245), -1)
        cv2.rectangle(rgb, (225, 135), (415, 345), (0, 210, 255), 8)
        cv2.circle(rgb, (320, 240), 34, (20, 20, 20), -1)
    ok, encoded = cv2.imencode(".jpg", rgb, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    depth = np.full((DEPTH_HEIGHT, DEPTH_WIDTH), depth_mm, dtype="<u2")
    confidence = np.full((DEPTH_HEIGHT, DEPTH_WIDTH), 2, dtype=np.uint8)
    return encoded.tobytes(), depth, confidence


def _packet(
    sequence: int,
    jpeg: bytes,
    depth: np.ndarray,
    confidence: np.ndarray,
) -> bytes:
    header = {
        "protocol_version": PROTOCOL_VERSION,
        "sequence": sequence,
        "timestamp_ns": time.time_ns(),
        "device_name": DEVICE_NAME,
        "orientation": "landscapeRight",
        "rgb_width": RGB_WIDTH,
        "rgb_height": RGB_HEIGHT,
        "rgb_length": len(jpeg),
        "depth_width": DEPTH_WIDTH,
        "depth_height": DEPTH_HEIGHT,
        "depth_length": int(depth.nbytes),
        "confidence_length": int(confidence.nbytes),
        "intrinsics": [500.0, 500.0, 320.0, 240.0],
        "rgb_to_depth": [0.4, 0.0, 0.0, 0.0, 0.4, 0.0, 0.0, 0.0, 1.0],
        "camera_transform": [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ],
        "depth_unit": "millimeters",
    }
    encoded_header = json.dumps(header, separators=(",", ":")).encode("utf-8")
    packet = (
        struct.pack(">I", len(encoded_header))
        + encoded_header
        + jpeg
        + depth.tobytes(order="C")
        + confidence.tobytes(order="C")
    )
    if len(packet) > MAX_MESSAGE_BYTES:
        raise RuntimeError("generated frame exceeds receiver message limit")
    return packet


async def send(args: argparse.Namespace) -> None:
    uri = f"ws://{_uri_host(args.host)}:{args.port}"
    jpeg, depth, confidence = _fixture_buffers(args.depth_mm)
    blank_jpeg, _, _ = _fixture_buffers(args.depth_mm, object_visible=False)
    async with connect(
        uri,
        max_size=MAX_MESSAGE_BYTES,
        open_timeout=5,
        close_timeout=2,
        compression=None,
    ) as socket:
        hello = {
            "type": "hello",
            "protocol_version": PROTOCOL_VERSION,
            "pairing_code": args.pairing_code,
            "device_name": DEVICE_NAME,
            "supports_scene_depth": True,
        }
        await socket.send(json.dumps(hello, separators=(",", ":")))
        response = await asyncio.wait_for(socket.recv(), timeout=5)
        if not isinstance(response, str):
            raise RuntimeError("pairing rejected: hello_ack was not text")
        try:
            ack = json.loads(response)
        except (TypeError, ValueError):
            raise RuntimeError("pairing rejected: invalid hello_ack JSON") from None
        if (
            not isinstance(ack, dict)
            or ack.get("type") != "hello_ack"
            or ack.get("accepted") is not True
            or ack.get("protocol_version") != PROTOCOL_VERSION
        ):
            raise RuntimeError("pairing rejected by Mac receiver")

        interval = 1.0 / args.fps
        deadline = time.monotonic()
        for sequence in range(args.frames):
            if sequence:
                deadline += interval
                await asyncio.sleep(max(0.0, deadline - time.monotonic()))
            frame_jpeg = blank_jpeg if sequence < args.lead_blank_frames else jpeg
            await socket.send(_packet(sequence, frame_jpeg, depth, confidence))

    print(
        f"sent {args.frames} frame(s) at {args.depth_mm} mm "
        f"to {args.host}:{args.port} ({args.fps:g} FPS)"
    )


def main() -> int:
    args = _parser().parse_args()
    if args.lead_blank_frames > args.frames:
        print("error: lead-blank-frames must not exceed frames", file=sys.stderr)
        return 2
    try:
        asyncio.run(send(args))
    except KeyboardInterrupt:
        print("cancelled", file=sys.stderr)
        return 130
    except (asyncio.TimeoutError, OSError, RuntimeError, WebSocketException) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
