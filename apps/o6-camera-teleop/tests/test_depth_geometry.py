import math
import unittest

import numpy as np

from vision.depth_geometry import ContactCalibrator, measure_depth


class DepthGeometryTest(unittest.TestCase):
    def test_maps_inner_rgb_box_to_scale_independent_depth_roi(self):
        result = measure_depth(
            np.full((20, 40), 600, dtype=np.uint16),
            np.full((20, 40), 2, dtype=np.uint8),
            rgb_box=(20, 10, 40, 40),
            rgb_size=(100, 80),
            inner_ratio=0.5,
            min_confidence=2,
            min_valid_ratio=1.0,
            contact_depth_mm=None,
        )

        self.assertEqual(result.depth_roi, (12, 5, 8, 5))
        self.assertEqual(result.target_depth_mm, 600.0)

    def test_rejects_large_depth_outlier_and_reports_positive_distance(self):
        depth = np.full((3, 3), 550, dtype=np.uint16)
        depth[0, 0] = 5000
        result = measure_depth(
            depth, np.full((3, 3), 2, dtype=np.uint8),
            rgb_box=(0, 0, 30, 30), rgb_size=(30, 30), inner_ratio=1.0,
            min_confidence=2, min_valid_ratio=1.0, contact_depth_mm=500,
        )

        self.assertEqual(result.target_depth_mm, 550.0)
        self.assertEqual(result.signed_distance_mm, 50.0)

    def test_reports_negative_distance_when_target_is_closer_than_contact(self):
        result = measure_depth(
            np.full((2, 2), 450, dtype=np.uint16),
            np.full((2, 2), 2, dtype=np.uint8),
            rgb_box=(0, 0, 20, 20), rgb_size=(20, 20), inner_ratio=1.0,
            min_confidence=2, min_valid_ratio=1.0, contact_depth_mm=500,
        )

        self.assertEqual(result.signed_distance_mm, -50.0)

    def test_excludes_zero_and_low_confidence_pixels_before_validity_threshold(self):
        depth = np.array([[550, 0], [550, 550]], dtype=np.uint16)
        confidence = np.array([[2, 2], [1, 1]], dtype=np.uint8)
        result = measure_depth(
            depth, confidence, rgb_box=(0, 0, 20, 20), rgb_size=(20, 20),
            inner_ratio=1.0, min_confidence=2, min_valid_ratio=0.5,
            contact_depth_mm=None,
        )

        self.assertEqual(result.valid_ratio, 0.25)
        self.assertIsNone(result.target_depth_mm)
        self.assertIsNone(result.signed_distance_mm)

    def test_rejects_invalid_inputs_and_configuration(self):
        depth = np.ones((2, 2), dtype=np.uint16)
        confidence = np.ones((2, 2), dtype=np.uint8)
        common = dict(rgb_box=(0, 0, 20, 20), rgb_size=(20, 20), inner_ratio=1.0,
                      min_confidence=1, min_valid_ratio=0.0, contact_depth_mm=None)
        with self.assertRaises(ValueError):
            measure_depth(np.ones((2, 2, 1)), confidence, **common)
        with self.assertRaises(ValueError):
            measure_depth(depth, np.ones((2, 3)), **common)
        with self.assertRaises(ValueError):
            measure_depth(depth, confidence, **{**common, "rgb_size": (0, 20)})
        with self.assertRaises(ValueError):
            measure_depth(depth, confidence, **{**common, "rgb_box": (0, 0, 0, 20)})
        with self.assertRaises(ValueError):
            measure_depth(depth, confidence, **{**common, "inner_ratio": 0.0})
        with self.assertRaises(ValueError):
            measure_depth(depth, confidence, **{**common, "min_valid_ratio": 1.1})
        with self.assertRaises(ValueError):
            measure_depth(depth, confidence, **{**common, "min_confidence": 1.5})
        with self.assertRaises(ValueError):
            measure_depth(depth, confidence, **{**common, "contact_depth_mm": math.inf})
        with self.assertRaises(ValueError):
            measure_depth(depth, confidence, **{**common, "rgb_box": (30, 0, 10, 10)})

    def test_calibrator_returns_median_for_exact_batch_then_resets(self):
        calibrator = ContactCalibrator(required_samples=3)
        self.assertIsNone(calibrator.add(None))
        self.assertIsNone(calibrator.add(500))
        self.assertIsNone(calibrator.add(700))
        self.assertEqual(calibrator.add(600), 600.0)
        self.assertIsNone(calibrator.add(100))
        self.assertIsNone(calibrator.add(300))
        self.assertEqual(calibrator.add(200), 200.0)

    def test_calibrator_validates_configuration_and_samples(self):
        with self.assertRaises(ValueError):
            ContactCalibrator(required_samples=0)
        calibrator = ContactCalibrator()
        with self.assertRaises(ValueError):
            calibrator.add(math.nan)
        with self.assertRaises(ValueError):
            calibrator.add(math.inf)

    def test_consumes_read_only_depth_frame_arrays_without_mutation(self):
        depth = np.full((2, 2), 550, dtype=np.uint16)
        confidence = np.full((2, 2), 2, dtype=np.uint8)
        depth.setflags(write=False)
        confidence.setflags(write=False)

        result = measure_depth(
            depth, confidence, rgb_box=(0, 0, 20, 20), rgb_size=(20, 20),
            inner_ratio=1.0, min_confidence=2, min_valid_ratio=1.0,
            contact_depth_mm=None,
        )

        self.assertEqual(result.target_depth_mm, 550.0)
        self.assertFalse(depth.flags.writeable)
        self.assertFalse(confidence.flags.writeable)


if __name__ == "__main__":
    unittest.main()
