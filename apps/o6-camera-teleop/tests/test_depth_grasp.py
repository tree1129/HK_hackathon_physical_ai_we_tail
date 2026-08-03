import math
import unittest

from control.depth_grasp import DepthGraspGate, DepthPhase


class DepthGraspGateTest(unittest.TestCase):
    def test_depth_progresses_from_open_zone_to_confirmed_contact(self):
        gate = DepthGraspGate(50, 0, 3)

        outside = gate.update(80, armed=True, hand_blocked=False)
        self.assertEqual(outside.phase, DepthPhase.OUTSIDE_OPEN_ZONE)
        self.assertFalse(outside.should_open)

        pregrasp = gate.update(40, armed=True, hand_blocked=False)
        self.assertEqual(pregrasp.phase, DepthPhase.PREGRASP_OPEN)
        self.assertTrue(pregrasp.should_open)
        self.assertFalse(pregrasp.contact_confirmed)

        for distance, count in ((-1, 1), (-2, 2)):
            decision = gate.update(distance, armed=True, hand_blocked=False)
            self.assertEqual(decision.phase, DepthPhase.PREGRASP_OPEN)
            self.assertEqual(decision.stable_count, count)
            self.assertFalse(decision.contact_confirmed)

        confirmed = gate.update(-1, armed=True, hand_blocked=False)
        self.assertEqual(confirmed.phase, DepthPhase.CONTACT_CONFIRMED)
        self.assertTrue(confirmed.should_open)
        self.assertTrue(confirmed.contact_confirmed)
        self.assertEqual(confirmed.stable_count, 3)

    def test_contact_count_saturates_and_intervening_samples_reset_it(self):
        gate = DepthGraspGate(50, 0, 2)

        gate.update(-1, armed=True, hand_blocked=False)
        confirmed = gate.update(-1, armed=True, hand_blocked=False)
        self.assertTrue(confirmed.contact_confirmed)
        self.assertEqual(gate.update(-1, armed=True, hand_blocked=False).stable_count, 2)

        for distance, armed, blocked in (
            (80, True, False),
            (40, True, False),
            (None, True, False),
            (-1, False, False),
            (-1, True, True),
            (math.nan, True, False),
            (math.inf, True, False),
        ):
            decision = gate.update(distance, armed=armed, hand_blocked=blocked)
            self.assertEqual(decision.stable_count, 0)
            self.assertFalse(decision.contact_confirmed)
            gate.update(-1, armed=True, hand_blocked=False)
            self.assertEqual(gate.update(-1, armed=True, hand_blocked=False).stable_count, 2)

    def test_thresholds_are_inclusive_on_the_safe_sides(self):
        gate = DepthGraspGate(50, 0, 1)

        at_open = gate.update(50, armed=True, hand_blocked=False)
        self.assertEqual(at_open.phase, DepthPhase.PREGRASP_OPEN)
        self.assertTrue(at_open.should_open)
        self.assertEqual(gate.update(50.001, armed=True, hand_blocked=False).phase, DepthPhase.OUTSIDE_OPEN_ZONE)

        at_contact = gate.update(0, armed=True, hand_blocked=False)
        self.assertEqual(at_contact.phase, DepthPhase.CONTACT_CONFIRMED)
        self.assertTrue(at_contact.contact_confirmed)
        self.assertEqual(gate.update(0.001, armed=True, hand_blocked=False).phase, DepthPhase.PREGRASP_OPEN)

    def test_constructor_rejects_invalid_configuration(self):
        invalid_configs = (
            (True, 0, 1),
            (50, False, 1),
            (math.nan, 0, 1),
            (50, math.inf, 1),
            (0, 0, 1),
            (50, 0, True),
            (50, 0, 1.0),
            (50, 0, 0),
        )

        for config in invalid_configs:
            with self.subTest(config=config):
                with self.assertRaises((TypeError, ValueError)):
                    DepthGraspGate(*config)


if __name__ == "__main__":
    unittest.main()
