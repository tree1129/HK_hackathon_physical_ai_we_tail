import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from o6_driver import (
    HAND_ID_LEFT,
    O6CanDriver,
    four_finger_wave_position,
    interpolate,
    six_or_scalar,
    six_uint8,
)


class FakeMessage:
    def __init__(self, arbitration_id, data):
        self.arbitration_id = arbitration_id
        self.data = data


class FakeBus:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.sent = []
        self.closed = False

    def send(self, message, timeout=None):
        self.sent.append((message, timeout))

    def recv(self, timeout=None):
        return self.responses.pop(0) if self.responses else None

    def shutdown(self):
        self.closed = True


class DriverTests(unittest.TestCase):
    def test_six_uint8_validation(self):
        self.assertEqual(six_uint8([0, 1, 2, 3, 254, 255]), [0, 1, 2, 3, 254, 255])
        with self.assertRaises(ValueError):
            six_uint8([1, 2])
        with self.assertRaises(ValueError):
            six_uint8([0, 1, 2, 3, 4, 256])

    def test_scalar_expands_to_six(self):
        self.assertEqual(six_or_scalar([50], "speed"), [50] * 6)
        self.assertEqual(six_or_scalar([1, 2, 3, 4, 5, 6]), [1, 2, 3, 4, 5, 6])
        with self.assertRaises(ValueError):
            six_or_scalar([1, 2])

    def test_interpolation_bounds_each_step(self):
        path = interpolate([250] * 6, [102, 18, 0, 0, 0, 0], max_step=8)
        previous = [250] * 6
        for point in path:
            self.assertLessEqual(max(abs(a - b) for a, b in zip(previous, point)), 8)
            previous = point
        self.assertEqual(path[-1], [102, 18, 0, 0, 0, 0])

    def test_four_finger_wave_has_fixed_thumb_and_soft_edges(self):
        options = dict(duration=5.0, frequency=0.8, amplitude=90, phase_delay=0.12, ramp_time=1.0)
        self.assertEqual(four_finger_wave_position(0.0, **options), [250] * 6)
        self.assertEqual(four_finger_wave_position(5.0, **options), [250] * 6)
        middle = four_finger_wave_position(2.0, **options)
        self.assertEqual(middle[:2], [250, 250])
        self.assertTrue(all(160 <= value <= 250 for value in middle[2:]))
        self.assertGreater(len(set(middle[2:])), 1)

    def test_full_amplitude_wave_can_request_closed_position(self):
        options = dict(duration=8.0, frequency=0.25, amplitude=250, phase_delay=0.25, ramp_time=1.0)
        sampled = [
            four_finger_wave_position(index / 100, **options)
            for index in range(801)
        ]
        per_finger_min = [min(pose[joint] for pose in sampled) for joint in range(2, 6)]
        self.assertEqual(per_finger_min, [0, 0, 0, 0])

    def test_request_ignores_unrelated_frames(self):
        bus = FakeBus(
            [
                FakeMessage(0x27, [0x01, 9, 9, 9, 9, 9, 9]),
                FakeMessage(HAND_ID_LEFT, [0x05, 1, 2, 3, 4, 5, 6]),
                FakeMessage(HAND_ID_LEFT, [0x01, 10, 20, 30, 40, 50, 60]),
            ]
        )
        with O6CanDriver("fake", "fake", bus=bus, execute=True) as driver:
            self.assertEqual(driver.request(0x01), [10, 20, 30, 40, 50, 60])
        self.assertTrue(bus.closed)

    def test_speed_is_sent_twice(self):
        bus = FakeBus()
        with O6CanDriver("fake", "fake", bus=bus, execute=True) as driver:
            driver.set_speed([40] * 6)
        self.assertEqual(len(bus.sent), 2)
        self.assertEqual(list(bus.sent[0][0].data), [0x05, 40, 40, 40, 40, 40, 40])


if __name__ == "__main__":
    unittest.main()
