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


class FrameSourceManager:
    """Routes RGB input without opening the Mac camera in iPhone mode."""

    def __init__(
        self,
        camera_index: int,
        receiver,
        capture_factory: Callable[[int], object] = cv2.VideoCapture,
        rtsp_source=None,
    ) -> None:
        self.camera_index = int(camera_index)
        self.receiver = receiver
        self.capture_factory = capture_factory
        self.rtsp_source = rtsp_source
        self.capture = None

    def read(self, source: VisionSource, now: float) -> FrameSample | None:
        if source == VisionSource.IPHONE_LIDAR:
            frame = self.receiver.latest(now)
            if frame is None:
                return None
            return FrameSample(source, frame.rgb_bgr.copy(), frame)

        if source == VisionSource.RECAMERA:
            if self.rtsp_source is None:
                return None
            bgr = self.rtsp_source.read(now)
            return None if bgr is None else FrameSample(source, bgr, None)

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
        if self.rtsp_source is not None:
            self.rtsp_source.close()
