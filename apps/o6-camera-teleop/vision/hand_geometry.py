from __future__ import annotations

from collections import OrderedDict

import numpy as np

WRIST = 0
THUMB = [1, 2, 3, 4]
INDEX = [5, 6, 7, 8]
MIDDLE = [9, 10, 11, 12]
RING = [13, 14, 15, 16]
PINKY = [17, 18, 19, 20]


def joint_angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Return the smaller 3D angle ABC in degrees."""
    ba = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    bc = np.asarray(c, dtype=float) - np.asarray(b, dtype=float)
    denominator = np.linalg.norm(ba) * np.linalg.norm(bc)
    if denominator < 1e-9:
        return 180.0
    cosine = np.clip(np.dot(ba, bc) / denominator, -1.0, 1.0)
    return float(np.degrees(np.arccos(cosine)))


def _bend(angle: float, full_flex_degrees: float) -> float:
    return float(np.clip((180.0 - angle) / full_flex_degrees, 0.0, 1.0))


def finger_flexion(points: np.ndarray, indices: list[int]) -> float:
    mcp, pip, dip, tip = indices
    mcp_angle = joint_angle(points[WRIST], points[mcp], points[pip])
    pip_angle = joint_angle(points[mcp], points[pip], points[dip])
    dip_angle = joint_angle(points[pip], points[dip], points[tip])
    components = np.array(
        [_bend(mcp_angle, 85.0), _bend(pip_angle, 105.0), _bend(dip_angle, 80.0)]
    )
    return float(np.dot(components, [0.25, 0.50, 0.25]))


def thumb_flexion(points: np.ndarray) -> float:
    cmc, mcp, ip, tip = THUMB
    mcp_bend = _bend(joint_angle(points[cmc], points[mcp], points[ip]), 80.0)
    ip_bend = _bend(joint_angle(points[mcp], points[ip], points[tip]), 85.0)
    return float(0.45 * mcp_bend + 0.55 * ip_bend)


def thumb_abduction(points: np.ndarray) -> float:
    """Return 0 for adducted and 1 for abducted, relative to the palm."""
    wrist = points[WRIST]
    thumb_ray = points[THUMB[-1]] - wrist
    index_ray = points[INDEX[0]] - wrist
    spread = joint_angle(wrist + thumb_ray, wrist, wrist + index_ray)
    angular_amount = float(np.clip((spread - 12.0) / (68.0 - 12.0), 0.0, 1.0))

    palm_axis = points[INDEX[0]] - points[PINKY[0]]
    palm_width = float(np.linalg.norm(palm_axis))
    if palm_width < 1e-9:
        return angular_amount
    lateral_ratio = abs(
        float(np.dot(points[THUMB[-1]] - points[INDEX[0]], palm_axis / palm_width))
    ) / palm_width
    lateral_amount = float(np.clip((lateral_ratio - 0.12) / (0.78 - 0.12), 0.0, 1.0))
    return max(angular_amount, lateral_amount)


def control_values(points: np.ndarray) -> OrderedDict[str, float]:
    points = np.asarray(points, dtype=float)
    if points.shape != (21, 3) or not np.all(np.isfinite(points)):
        raise ValueError("MediaPipe landmarks must have shape (21, 3)")
    return OrderedDict(
        (
            ("thumb_flexion", thumb_flexion(points)),
            ("thumb_abduction", thumb_abduction(points)),
            ("index_flexion", finger_flexion(points, INDEX)),
            ("middle_flexion", finger_flexion(points, MIDDLE)),
            ("ring_flexion", finger_flexion(points, RING)),
            ("pinky_flexion", finger_flexion(points, PINKY)),
        )
    )
