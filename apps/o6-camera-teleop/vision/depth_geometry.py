from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real

import numpy as np


@dataclass(frozen=True)
class DepthMeasurement:
    target_depth_mm: float | None
    signed_distance_mm: float | None
    valid_ratio: float
    depth_roi: tuple[int, int, int, int]


def measure_depth(
    depth_mm,
    confidence,
    *,
    rgb_box,
    rgb_size,
    inner_ratio,
    min_confidence,
    min_valid_ratio,
    contact_depth_mm,
) -> DepthMeasurement:
    """Measure a robust target depth from a box mapped into the depth image."""
    depth = _depth_array(depth_mm, "depth_mm")
    confidence_array = _depth_array(confidence, "confidence")
    if depth.shape != confidence_array.shape:
        raise ValueError("depth_mm and confidence must have the same shape")
    rgb_width, rgb_height = _positive_pair(rgb_size, "rgb_size")
    box_x, box_y, box_width, box_height = _box(rgb_box)
    if not isinstance(inner_ratio, Real) or isinstance(inner_ratio, bool) or not 0 < inner_ratio <= 1:
        raise ValueError("inner_ratio must be in (0, 1]")
    if (
        not isinstance(min_valid_ratio, Real)
        or isinstance(min_valid_ratio, bool)
        or not math.isfinite(float(min_valid_ratio))
        or not 0 <= min_valid_ratio <= 1
    ):
        raise ValueError("min_valid_ratio must be in [0, 1]")
    if not isinstance(min_confidence, Integral) or isinstance(min_confidence, bool):
        raise ValueError("min_confidence must be an integer")
    contact_depth = _finite_number_or_none(contact_depth_mm, "contact_depth_mm")

    depth_height, depth_width = depth.shape
    inset_x = box_x + box_width * (1 - inner_ratio) / 2
    inset_y = box_y + box_height * (1 - inner_ratio) / 2
    inset_width = box_width * inner_ratio
    inset_height = box_height * inner_ratio
    start_x = _clamp(math.floor(inset_x * depth_width / rgb_width), 0, depth_width)
    start_y = _clamp(math.floor(inset_y * depth_height / rgb_height), 0, depth_height)
    end_x = _clamp(math.ceil((inset_x + inset_width) * depth_width / rgb_width), 0, depth_width)
    end_y = _clamp(math.ceil((inset_y + inset_height) * depth_height / rgb_height), 0, depth_height)
    if start_x >= end_x or start_y >= end_y:
        raise ValueError("mapped depth ROI is empty")

    roi = (start_x, start_y, end_x - start_x, end_y - start_y)
    depth_values = depth[start_y:end_y, start_x:end_x]
    confidence_values = confidence_array[start_y:end_y, start_x:end_x]
    valid = (
        np.isfinite(depth_values)
        & (depth_values > 0)
        & (confidence_values >= min_confidence)
    )
    valid_ratio = float(np.count_nonzero(valid) / valid.size)
    if valid_ratio < min_valid_ratio or not np.any(valid):
        return DepthMeasurement(None, None, valid_ratio, roi)

    target_depth = _robust_median(depth_values[valid])
    signed_distance = None if contact_depth is None else target_depth - contact_depth
    return DepthMeasurement(target_depth, signed_distance, valid_ratio, roi)


class ContactCalibrator:
    def __init__(self, required_samples: int = 15) -> None:
        if not isinstance(required_samples, Integral) or isinstance(required_samples, bool) or required_samples < 1:
            raise ValueError("required_samples must be at least 1")
        self.required_samples = int(required_samples)
        self._samples: list[float] = []

    def reset(self) -> None:
        self._samples.clear()

    def add(self, depth_mm: float | None) -> float | None:
        depth = _finite_number_or_none(depth_mm, "depth_mm")
        if depth is None:
            return None
        self._samples.append(depth)
        if len(self._samples) < self.required_samples:
            return None
        result = _robust_median(np.asarray(self._samples[-self.required_samples:]))
        self.reset()
        return result


def _depth_array(value, name: str) -> np.ndarray:
    if not isinstance(value, np.ndarray) or value.ndim != 2:
        raise ValueError(f"{name} must be a 2D NumPy array")
    return value


def _positive_pair(value, name: str) -> tuple[float, float]:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError(f"{name} must contain width and height")
    width = _positive_number(value[0], f"{name} width")
    height = _positive_number(value[1], f"{name} height")
    return width, height


def _box(value) -> tuple[float, float, float, float]:
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise ValueError("rgb_box must contain x, y, width, and height")
    x = _finite_number_or_none(value[0], "rgb_box x")
    y = _finite_number_or_none(value[1], "rgb_box y")
    width = _positive_number(value[2], "rgb_box width")
    height = _positive_number(value[3], "rgb_box height")
    assert x is not None and y is not None
    return x, y, width, height


def _positive_number(value, name: str) -> float:
    number = _finite_number_or_none(value, name)
    if number is None or number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _finite_number_or_none(value, name: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, Real) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _robust_median(values: np.ndarray) -> float:
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    if mad > 0:
        retained = values[np.abs(values - median) <= 3 * 1.4826 * mad]
        median = float(np.median(retained))
    if not math.isfinite(median):
        raise ValueError("valid depth values must be finite")
    return median


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))
