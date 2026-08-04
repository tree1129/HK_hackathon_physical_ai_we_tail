from __future__ import annotations

from dataclasses import dataclass
import threading
import time

import cv2
import numpy as np


@dataclass(frozen=True)
class MobileFrame:
    sequence: int
    bgr: np.ndarray
    received_monotonic: float


class MobileFrameReceiver:
    """Thread-safe latest-frame buffer for browser camera uploads."""

    def __init__(self, timeout_seconds: float = 1.0, max_bytes: int = 1_000_000) -> None:
        self.timeout_seconds = float(timeout_seconds)
        self.max_bytes = int(max_bytes)
        self._lock = threading.Lock()
        self._latest: MobileFrame | None = None
        self._sequence = 0
        self._previous_received: float | None = None
        self._fps = 0.0

    def publish(self, jpeg: bytes, now: float | None = None) -> MobileFrame:
        if not jpeg or len(jpeg) > self.max_bytes:
            raise ValueError("mobile frame is empty or exceeds size limit")
        encoded = np.frombuffer(jpeg, dtype=np.uint8)
        bgr = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("mobile frame is not a valid JPEG")
        received = time.monotonic() if now is None else float(now)
        with self._lock:
            self._sequence += 1
            if self._previous_received is not None:
                instant = 1.0 / max(received - self._previous_received, 1e-6)
                self._fps = instant if self._fps == 0 else 0.85 * self._fps + 0.15 * instant
            self._previous_received = received
            self._latest = MobileFrame(self._sequence, bgr, received)
            return self._latest

    def latest(self, now: float | None = None) -> MobileFrame | None:
        current = time.monotonic() if now is None else float(now)
        with self._lock:
            frame = self._latest
            if frame is None or current - frame.received_monotonic > self.timeout_seconds:
                return None
            return MobileFrame(frame.sequence, frame.bgr.copy(), frame.received_monotonic)

    def status(self, now: float | None = None) -> dict:
        current = time.monotonic() if now is None else float(now)
        with self._lock:
            frame = self._latest
            age = None if frame is None else max(0.0, current - frame.received_monotonic)
            return {
                "connected": age is not None and age <= self.timeout_seconds,
                "age_ms": None if age is None else round(age * 1000.0, 1),
                "fps": round(self._fps, 1),
            }
