from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np


@dataclass(frozen=True)
class ObjectDetection:
    label: str
    score: float
    x: int
    y: int
    width: int
    height: int
    frame_width: int
    frame_height: int

    @property
    def center_normalized(self) -> tuple[float, float]:
        return (
            (self.x + self.width / 2) / self.frame_width,
            (self.y + self.height / 2) / self.frame_height,
        )

    @property
    def area_ratio(self) -> float:
        return (self.width * self.height) / (self.frame_width * self.frame_height)


class ObjectTracker:
    def __init__(
        self,
        model_path: str | Path,
        score_threshold: float = 0.45,
        max_results: int = 5,
        denylist: list[str] | None = None,
    ) -> None:
        model_path = Path(model_path).expanduser().resolve()
        if not model_path.is_file():
            raise FileNotFoundError(f"MediaPipe object model not found: {model_path}")
        options = mp.tasks.vision.ObjectDetectorOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            max_results=int(max_results),
            score_threshold=float(score_threshold),
            category_denylist=list(denylist or []),
        )
        self._detector = mp.tasks.vision.ObjectDetector.create_from_options(options)
        self._last_timestamp_ms = -1

    def process(self, bgr_frame: np.ndarray, timestamp_ms: int) -> list[ObjectDetection]:
        timestamp_ms = max(int(timestamp_ms), self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = self._detector.detect_for_video(image, timestamp_ms)
        height, width = bgr_frame.shape[:2]
        output: list[ObjectDetection] = []
        for detection in result.detections:
            if not detection.categories:
                continue
            category = detection.categories[0]
            box = detection.bounding_box
            output.append(
                ObjectDetection(
                    label=category.category_name or "object",
                    score=float(category.score or 0.0),
                    x=max(0, int(box.origin_x)),
                    y=max(0, int(box.origin_y)),
                    width=max(1, min(int(box.width), width)),
                    height=max(1, min(int(box.height), height)),
                    frame_width=width,
                    frame_height=height,
                )
            )
        return output

    def close(self) -> None:
        self._detector.close()
