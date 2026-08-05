import tempfile
from pathlib import Path
import unittest

import numpy as np
import yaml

from config_store import save_contact_depth
from control.console_mode import VisionSource
from tests.depth_test_utils import make_depth_frame
from vision.frame_source import FrameSourceManager


class FakeReceiver:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def latest(self, now):
        self.calls.append(now)
        return self.frame


class FakeCapture:
    def __init__(self, frame=None):
        self.frame = frame
        self.released = False

    def read(self):
        return (self.frame is not None, self.frame)

    def release(self):
        self.released = True


class FrameSourceTest(unittest.TestCase):
    def test_iphone_source_does_not_open_mac_camera(self):
        opened = []
        frame = make_depth_frame(received_monotonic=1.0)
        manager = FrameSourceManager(
            0,
            FakeReceiver(frame),
            lambda index: opened.append(index),
        )

        sample = manager.read(VisionSource.IPHONE_LIDAR, now=1.0)

        self.assertEqual(sample.source, VisionSource.IPHONE_LIDAR)
        self.assertIs(sample.depth, frame)
        self.assertEqual(opened, [])
        self.assertFalse(np.shares_memory(sample.bgr, frame.rgb_bgr))

    def test_missing_or_stale_iphone_frame_returns_none(self):
        receiver = FakeReceiver(None)
        manager = FrameSourceManager(0, receiver)

        self.assertIsNone(manager.read(VisionSource.IPHONE_LIDAR, now=2.0))
        self.assertEqual(receiver.calls, [2.0])

    def test_mac_camera_opens_lazily_and_is_released(self):
        capture = FakeCapture(np.zeros((2, 3, 3), dtype=np.uint8))
        opened = []

        def factory(index):
            opened.append(index)
            return capture

        manager = FrameSourceManager(4, FakeReceiver(None), factory)
        self.assertEqual(opened, [])
        self.assertIsNotNone(manager.read(VisionSource.MAC_CAMERA, now=1.0))
        self.assertIsNotNone(manager.read(VisionSource.MAC_CAMERA, now=2.0))
        self.assertEqual(opened, [4])
        manager.close()
        self.assertTrue(capture.released)
        self.assertIsNone(manager.capture)

    def test_mac_camera_reopens_after_a_failed_read(self):
        failed = FakeCapture()
        recovered = FakeCapture(np.zeros((2, 3, 3), dtype=np.uint8))
        captures = iter((failed, recovered))
        opened = []

        def factory(index):
            opened.append(index)
            return next(captures)

        manager = FrameSourceManager(2, FakeReceiver(None), factory)

        self.assertIsNone(manager.read(VisionSource.MAC_CAMERA, now=1.0))
        self.assertTrue(failed.released)
        self.assertIsNotNone(manager.read(VisionSource.MAC_CAMERA, now=2.0))
        self.assertEqual(opened, [2, 2])

    def test_atomic_contact_save_preserves_existing_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(
                "o6:\n  hand_type: left\niphone_lidar:\n  enabled: true\n  contact_depth_mm: null\n",
                encoding="utf-8",
            )

            save_contact_depth(path, 432.0)
            saved = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["iphone_lidar"]["contact_depth_mm"], 432.0)
            self.assertTrue(saved["iphone_lidar"]["enabled"])
            self.assertEqual(saved["o6"]["hand_type"], "left")

            save_contact_depth(path, None)
            saved = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertIsNone(saved["iphone_lidar"]["contact_depth_mm"])

    def test_contact_save_rejects_invalid_values_without_changing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            original = "o6:\n  hand_type: left\n"
            path.write_text(original, encoding="utf-8")
            for value in (True, 0, -1, float("nan")):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    save_contact_depth(path, value)
                self.assertEqual(path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
