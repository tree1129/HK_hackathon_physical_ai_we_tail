import unittest

import numpy as np

from control.console_mode import ConsoleMode, ConsoleModeState, VisionSource
from vision.frame_source import FrameSourceManager
from vision.rtsp_source import RtspFrameSource


class FakeCapture:
    def __init__(self, reads, opened=True):
        self.reads = list(reads)
        self.opened = opened
        self.released = False

    def isOpened(self):
        return self.opened

    def read(self):
        return self.reads.pop(0) if self.reads else (False, None)

    def release(self):
        self.released = True


class RtspSourceTest(unittest.TestCase):
    def test_success_reports_connection_fps_and_age(self):
        frame = np.zeros((2, 3, 3), dtype=np.uint8)
        source = RtspFrameSource(
            "rtsp://camera/live",
            retry_seconds=1.0,
            capture_factory=lambda _url: FakeCapture([(True, frame), (True, frame)]),
        )

        self.assertIs(source.read(10.0), frame)
        self.assertIs(source.read(10.1), frame)
        status = source.status(10.15)

        self.assertTrue(status.connected)
        self.assertGreater(status.fps, 0)
        self.assertAlmostEqual(status.frame_age_ms, 50.0)

    def test_failure_releases_and_retries_after_deadline(self):
        first = FakeCapture([(False, None)])
        frame = np.zeros((2, 3, 3), dtype=np.uint8)
        second = FakeCapture([(True, frame)])
        captures = iter([first, second])
        opened = []

        def factory(url):
            opened.append(url)
            return next(captures)

        source = RtspFrameSource("rtsp://camera/live", 1.0, factory)

        self.assertIsNone(source.read(1.0))
        self.assertTrue(first.released)
        self.assertIsNone(source.read(1.5))
        self.assertIsNotNone(source.read(2.0))
        self.assertEqual(opened, ["rtsp://camera/live", "rtsp://camera/live"])

    def test_open_failure_releases_capture(self):
        capture = FakeCapture([], opened=False)
        source = RtspFrameSource(
            "rtsp://camera/live", 1.0, lambda _url: capture
        )

        self.assertIsNone(source.read(1.0))

        self.assertTrue(capture.released)
        self.assertFalse(source.status(1.0).connected)
        self.assertEqual(source.status(1.0).last_error, "RTSP open failed")

    def test_manager_routes_recamera_without_opening_mac_camera(self):
        frame = np.zeros((2, 3, 3), dtype=np.uint8)
        rtsp = RtspFrameSource(
            "rtsp://camera/live",
            1.0,
            lambda _url: FakeCapture([(True, frame)]),
        )
        opened = []
        manager = FrameSourceManager(
            0,
            receiver=None,
            capture_factory=lambda index: opened.append(index),
            rtsp_source=rtsp,
        )

        sample = manager.read(VisionSource.RECAMERA, now=1.0)

        self.assertEqual(sample.source, VisionSource.RECAMERA)
        self.assertIs(sample.bgr, frame)
        self.assertEqual(opened, [])
        manager.close()
        self.assertFalse(rtsp.status(1.0).connected)

    def test_recamera_forces_object_mode_and_pauses_follow(self):
        state = ConsoleModeState(
            mode=ConsoleMode.HAND_FOLLOW,
            follow_enabled=True,
        )

        state.switch_source(VisionSource.RECAMERA)

        self.assertEqual(state.mode, ConsoleMode.OBJECT_GRASP)
        self.assertFalse(state.follow_enabled)


if __name__ == "__main__":
    unittest.main()
