from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import cv2


@dataclass(frozen=True)
class RtspStatus:
    connected: bool
    fps: float
    frame_age_ms: float | None
    last_error: str | None


def _open_capture(url: str):
    params = [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
        3000,
        cv2.CAP_PROP_READ_TIMEOUT_MSEC,
        1000,
    ]
    return cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)


class RtspFrameSource:
    def __init__(
        self,
        url: str,
        retry_seconds: float,
        capture_factory: Callable[[str], object] = _open_capture,
    ) -> None:
        if not isinstance(url, str) or not url.startswith(("rtsp://", "rtsps://")):
            raise ValueError("reCamera RTSP URL must start with rtsp:// or rtsps://")
        if retry_seconds <= 0:
            raise ValueError("retry_seconds must be positive")
        self.url = url
        self.retry_seconds = float(retry_seconds)
        self.capture_factory = capture_factory
        self.capture = None
        self.next_retry_at = 0.0
        self.connected = False
        self.fps = 0.0
        self.last_frame_at: float | None = None
        self.last_error: str | None = None

    def read(self, now: float):
        if self.capture is None:
            if now < self.next_retry_at:
                return None
            self.capture = self.capture_factory(self.url)
            if hasattr(self.capture, "isOpened") and not self.capture.isOpened():
                return self._fail(now, "RTSP open failed")
        ok, frame = self.capture.read()
        if not ok or frame is None:
            return self._fail(now, "RTSP read failed")
        if self.last_frame_at is not None:
            instant_fps = 1.0 / max(now - self.last_frame_at, 1e-6)
            self.fps = (
                instant_fps
                if self.fps == 0
                else 0.9 * self.fps + 0.1 * instant_fps
            )
        self.last_frame_at = now
        self.connected = True
        self.last_error = None
        return frame

    def status(self, now: float) -> RtspStatus:
        frame_age_ms = (
            None
            if self.last_frame_at is None
            else max(0.0, now - self.last_frame_at) * 1000
        )
        return RtspStatus(
            connected=self.connected,
            fps=self.fps,
            frame_age_ms=frame_age_ms,
            last_error=self.last_error,
        )

    def close(self) -> None:
        capture, self.capture = self.capture, None
        if capture is not None:
            capture.release()
        self.connected = False

    def _fail(self, now: float, message: str):
        self.close()
        self.next_retry_at = now + self.retry_seconds
        self.last_error = message
        return None
