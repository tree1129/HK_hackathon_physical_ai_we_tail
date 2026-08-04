import unittest

import numpy as np

from control.hand_mapper import CHANNEL_ORDER, HandMapper
from vision.hand_geometry import thumb_abduction
from vision.hand_tracker import HandTracker


CHANNELS = {
    "thumb_flexion": {"open": 250, "closed": 102},
    "thumb_abduction": {"min": 18, "max": 250},
    "index_flexion": {"open": 250, "closed": 0},
    "middle_flexion": {"open": 250, "closed": 0},
    "ring_flexion": {"open": 250, "closed": 0},
    "pinky_flexion": {"open": 250, "closed": 0},
}


def _thumb_pose(mirrored: bool, lateral: float) -> np.ndarray:
    points = np.zeros((21, 3), dtype=float)
    direction = -1.0 if mirrored else 1.0
    points[0] = [0.0, 0.0, 0.0]
    points[5] = [0.0, 1.0, 0.0]
    points[17] = [direction, 1.0, 0.0]
    points[4] = [-direction * lateral, 1.1, 0.0]
    return points


class ThumbGeometryTest(unittest.TestCase):
    def test_right_hand_reverses_only_thumb_abduction_motor_endpoints(self):
        mapper = HandMapper(CHANNELS)
        spread = {name: 0.0 for name in CHANNEL_ORDER}
        spread["thumb_abduction"] = 1.0

        left_pose = mapper.map_normalized(spread, hand_type="left")
        right_pose = mapper.map_normalized(spread, hand_type="right")

        self.assertEqual(left_pose[1], CHANNELS["thumb_abduction"]["max"])
        self.assertEqual(right_pose[1], CHANNELS["thumb_abduction"]["min"])
        self.assertEqual(left_pose[:1] + left_pose[2:], right_pose[:1] + right_pose[2:])

    def test_wide_thumb_uses_palm_normalized_lateral_spread(self):
        left = thumb_abduction(_thumb_pose(mirrored=False, lateral=0.7))
        right = thumb_abduction(_thumb_pose(mirrored=True, lateral=0.7))

        self.assertGreater(left, 0.85)
        self.assertAlmostEqual(left, right)

    def test_adducted_thumb_stays_near_zero(self):
        amount = thumb_abduction(_thumb_pose(mirrored=False, lateral=0.05))

        self.assertLess(amount, 0.1)

    def test_unmirrored_camera_handedness_is_reported_as_physical_side(self):
        self.assertEqual(HandTracker.physical_handedness("Left"), "Right")
        self.assertEqual(HandTracker.physical_handedness("Right"), "Left")
        self.assertEqual(HandTracker.physical_handedness("Unknown"), "Unknown")


if __name__ == "__main__":
    unittest.main()
