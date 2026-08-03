from __future__ import annotations

import cv2
import numpy as np

from vision.object_detector import ObjectDetection


class ForegroundDetector:
    """Detect a newly inserted generic object against an armed background frame."""

    def __init__(
        self,
        pixel_threshold: int = 30,
        min_contour_area_ratio: float = 0.015,
        max_changed_area_ratio: float = 0.65,
    ) -> None:
        self.pixel_threshold = int(pixel_threshold)
        self.min_contour_area_ratio = float(min_contour_area_ratio)
        self.max_changed_area_ratio = float(max_changed_area_ratio)
        self._background: np.ndarray | None = None

    def capture_background(self, frame: np.ndarray) -> None:
        self._background = self._gray(frame)

    def clear(self) -> None:
        self._background = None

    @property
    def ready(self) -> bool:
        return self._background is not None

    def detect(
        self,
        frame: np.ndarray,
        zone: tuple[float, float, float, float],
    ) -> ObjectDetection | None:
        if self._background is None:
            return None
        current = self._gray(frame)
        if current.shape != self._background.shape:
            self.clear()
            return None

        height, width = current.shape
        x1, y1, x2, y2 = zone
        left, top = int(x1 * width), int(y1 * height)
        right, bottom = int(x2 * width), int(y2 * height)
        difference = cv2.absdiff(self._background[top:bottom, left:right], current[top:bottom, left:right])
        _, mask = cv2.threshold(difference, self.pixel_threshold, 255, cv2.THRESH_BINARY)
        kernel = np.ones((5, 5), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        roi_area = max(1, mask.shape[0] * mask.shape[1])
        changed_ratio = cv2.countNonZero(mask) / roi_area
        if changed_ratio > self.max_changed_area_ratio:
            return None

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        contour = max(contours, key=cv2.contourArea)
        contour_ratio = cv2.contourArea(contour) / roi_area
        if contour_ratio < self.min_contour_area_ratio:
            return None
        x, y, box_width, box_height = cv2.boundingRect(contour)
        return ObjectDetection(
            label="generic-object",
            score=min(0.99, 0.5 + contour_ratio),
            x=left + x,
            y=top + y,
            width=box_width,
            height=box_height,
            frame_width=width,
            frame_height=height,
        )

    @staticmethod
    def _gray(frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.GaussianBlur(gray, (7, 7), 0)
