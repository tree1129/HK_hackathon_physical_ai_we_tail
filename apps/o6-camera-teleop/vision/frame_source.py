from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

from control.console_mode import VisionSource
from vision.depth_protocol import DepthFrame


@dataclass(frozen=True)
class FrameSample:
    source: VisionSource
    bgr: np.ndarray
    depth: DepthFrame | None
    sequence: int | None = None


class FrameSourceManager:
    """Routes RGB input without opening the Mac camera in iPhone mode."""

    def __init__(
        self,
        camera_index: int,
        receiver,
        capture_factory: Callable[[int], object] = cv2.VideoCapture,
        mobile_receiver=None,
    ) -> None:
        self.camera_index = int(camera_index)
        self.receiver = receiver
        self.mobile_receiver = mobile_receiver
        self.capture_factory = capture_factory
        self.capture = None

    def read(self, source: VisionSource, now: float) -> FrameSample | None:
        if source == VisionSource.IPHONE_LIDAR:
            frame = self.receiver.latest(now)
            if frame is None:
                return None
            return FrameSample(source, frame.rgb_bgr.copy(), frame)

        if source == VisionSource.MOBILE_CAMERA:
            frame = None if self.mobile_receiver is None else self.mobile_receiver.latest(now)
            if frame is None:
                return None
            return FrameSample(source, frame.bgr, None, frame.sequence)

        if source != VisionSource.MAC_CAMERA:
            raise ValueError(f"unsupported vision source: {source!r}")
        if self.capture is None:
            self.capture = self.capture_factory(self.camera_index)
        ok, bgr = self.capture.read()
        if not ok or bgr is None:
            return None
        return FrameSample(source, bgr, None)

    def close(self) -> None:
        capture, self.capture = self.capture, None
        if capture is not None:
            capture.release()
