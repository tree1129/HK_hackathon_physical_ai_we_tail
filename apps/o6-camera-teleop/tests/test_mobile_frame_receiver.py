import unittest

import cv2
import numpy as np

from vision.mobile_frame_receiver import MobileFrameReceiver


class MobileFrameReceiverTest(unittest.TestCase):
    def test_keeps_latest_valid_jpeg_and_expires_it(self):
        receiver = MobileFrameReceiver(timeout_seconds=1.0)
        image = np.full((8, 10, 3), 127, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", image)
        self.assertTrue(ok)

        first = receiver.publish(encoded.tobytes(), now=10.0)
        second = receiver.publish(encoded.tobytes(), now=10.1)

        self.assertEqual(first.sequence, 1)
        self.assertEqual(second.sequence, 2)
        self.assertEqual(receiver.latest(now=10.2).bgr.shape, (8, 10, 3))
        self.assertIsNone(receiver.latest(now=11.2))

    def test_rejects_invalid_or_oversized_payload(self):
        receiver = MobileFrameReceiver(max_bytes=4)
        with self.assertRaises(ValueError):
            receiver.publish(b"")
        with self.assertRaises(ValueError):
            receiver.publish(b"not-jpeg")


if __name__ == "__main__":
    unittest.main()
