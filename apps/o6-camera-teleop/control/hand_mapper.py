from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from vision.hand_geometry import control_values

CHANNEL_ORDER = [
    "thumb_flexion",
    "thumb_abduction",
    "index_flexion",
    "middle_flexion",
    "ring_flexion",
    "pinky_flexion",
]
FLEXION_CHANNELS = [name for name in CHANNEL_ORDER if name != "thumb_abduction"]


class HandMapper:
    def __init__(
        self,
        channels: Mapping[str, Mapping[str, float]],
        calibration: Mapping[str, Mapping[str, float]] | None = None,
    ) -> None:
        self.channels = {name: dict(channels[name]) for name in CHANNEL_ORDER}
        calibration = calibration or {}
        self.open_sample = self._sample_or_none(calibration.get("geometry_open"))
        self.closed_sample = self._sample_or_none(calibration.get("geometry_closed"))

    def geometry(self, landmarks: np.ndarray) -> dict[str, float]:
        return dict(control_values(landmarks))

    def map_landmarks(
        self, landmarks: np.ndarray, hand_type: str = "left"
    ) -> tuple[list[int], dict[str, float]]:
        raw = self.geometry(landmarks)
        normalized = self.apply_calibration(raw)
        return self.map_normalized(normalized, hand_type=hand_type), raw

    def apply_calibration(self, raw: Mapping[str, float]) -> dict[str, float]:
        if self.open_sample is None or self.closed_sample is None:
            return {name: float(np.clip(raw[name], 0.0, 1.0)) for name in CHANNEL_ORDER}

        result: dict[str, float] = {}
        for name in FLEXION_CHANNELS:
            result[name] = self._normalize(
                raw[name], self.open_sample[name], self.closed_sample[name]
            )
        result["thumb_abduction"] = self._normalize(
            raw["thumb_abduction"],
            self.closed_sample["thumb_abduction"],
            self.open_sample["thumb_abduction"],
        )
        return result

    def map_normalized(
        self, normalized: Mapping[str, float], hand_type: str = "left"
    ) -> list[int]:
        if hand_type not in ("left", "right"):
            raise ValueError("hand_type must be left or right")
        pose: list[int] = []
        for name in CHANNEL_ORDER:
            amount = float(np.clip(normalized[name], 0.0, 1.0))
            channel = self.channels[name]
            if name == "thumb_abduction":
                if hand_type == "right":
                    amount = 1.0 - amount
                value = channel["min"] + amount * (channel["max"] - channel["min"])
            else:
                value = channel["open"] + amount * (channel["closed"] - channel["open"])
            pose.append(int(np.clip(round(value), 0, 255)))
        return pose

    def record_open(self, sample: Mapping[str, float]) -> None:
        self.open_sample = self._validated_sample(sample)

    def record_closed(self, sample: Mapping[str, float]) -> None:
        self.closed_sample = self._validated_sample(sample)

    def reset_calibration(self) -> None:
        self.open_sample = None
        self.closed_sample = None

    def calibration_data(self) -> dict[str, dict[str, float] | None]:
        return {
            "geometry_open": self.open_sample,
            "geometry_closed": self.closed_sample,
        }

    @staticmethod
    def _normalize(value: float, start: float, end: float) -> float:
        span = end - start
        if abs(span) < 1e-5:
            return float(np.clip(value, 0.0, 1.0))
        return float(np.clip((value - start) / span, 0.0, 1.0))

    @staticmethod
    def _sample_or_none(sample: Mapping[str, float] | None) -> dict[str, float] | None:
        return None if sample is None else HandMapper._validated_sample(sample)

    @staticmethod
    def _validated_sample(sample: Mapping[str, float]) -> dict[str, float]:
        if any(name not in sample for name in CHANNEL_ORDER):
            raise ValueError("calibration sample must contain all 6 channels")
        return {name: float(np.clip(sample[name], 0.0, 1.0)) for name in CHANNEL_ORDER}
