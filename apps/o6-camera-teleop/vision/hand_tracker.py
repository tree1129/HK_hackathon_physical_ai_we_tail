from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)


@dataclass(frozen=True)
class HandDetection:
    image_landmarks: np.ndarray
    geometry_landmarks: np.ndarray
    handedness: str
    score: float


class HandTracker:
    def __init__(
        self,
        model_path: str | Path,
        detection_confidence: float = 0.5,
        presence_confidence: float = 0.5,
        tracking_confidence: float = 0.5,
    ) -> None:
        model_path = Path(model_path).expanduser().resolve()
        if not model_path.is_file():
            raise FileNotFoundError(f"MediaPipe model not found: {model_path}")
        options = mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=float(detection_confidence),
            min_hand_presence_confidence=float(presence_confidence),
            min_tracking_confidence=float(tracking_confidence),
        )
        self._landmarker = mp.tasks.vision.HandLandmarker.create_from_options(options)
        self._last_timestamp_ms = -1

    def process(self, bgr_frame: np.ndarray, timestamp_ms: int) -> HandDetection | None:
        timestamp_ms = max(int(timestamp_ms), self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        if not result.hand_landmarks:
            return None

        image_points = self._to_array(result.hand_landmarks[0])
        if result.hand_world_landmarks:
            geometry_points = self._to_array(result.hand_world_landmarks[0])
        else:
            geometry_points = image_points.copy()
        category = result.handedness[0][0]
        return HandDetection(
            image_landmarks=image_points,
            geometry_landmarks=geometry_points,
            handedness=self.physical_handedness(category.category_name or "Unknown"),
            score=float(category.score or 0.0),
        )

    @staticmethod
    def draw(frame: np.ndarray, detection: HandDetection, mirrored: bool = False) -> None:
        height, width = frame.shape[:2]
        points = detection.image_landmarks.copy()
        if mirrored:
            points[:, 0] = 1.0 - points[:, 0]
        pixels = np.column_stack((points[:, 0] * width, points[:, 1] * height)).astype(int)
        for start, end in HAND_CONNECTIONS:
            cv2.line(frame, tuple(pixels[start]), tuple(pixels[end]), (72, 210, 130), 2)
        for point in pixels:
            cv2.circle(frame, tuple(point), 4, (30, 215, 255), -1)

    def close(self) -> None:
        self._landmarker.close()

    @staticmethod
    def physical_handedness(name: str) -> str:
        """Convert MediaPipe's mirrored-input label to the physical hand side."""
        return {"Left": "Right", "Right": "Left"}.get(name, name)

    @staticmethod
    def _to_array(landmarks: list) -> np.ndarray:
        return np.asarray([[item.x, item.y, item.z] for item in landmarks], dtype=np.float64)
