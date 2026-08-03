import unittest

import numpy as np

from control.filters import CommandFilter
from control.console_mode import ConsoleMode, ConsoleModeState, TrackingState
from control.grasp_state import GraspState, GraspStateMachine, TargetObservation
from control.hand_mapper import CHANNEL_ORDER, HandMapper
from control.o6_controller import _resolve_can_id
from vision.foreground_detector import ForegroundDetector
from web_console import ALLOWED_ACTIONS, create_app


CHANNELS = {
    "thumb_flexion": {"open": 255, "closed": 20},
    "thumb_abduction": {"min": 30, "max": 220},
    "index_flexion": {"open": 255, "closed": 20},
    "middle_flexion": {"open": 255, "closed": 20},
    "ring_flexion": {"open": 255, "closed": 20},
    "pinky_flexion": {"open": 255, "closed": 20},
}


class MapperAndFilterTest(unittest.TestCase):
    def test_can_id_override_preserves_physical_hand_type(self):
        self.assertEqual(_resolve_can_id("right", None), 0x27)
        self.assertEqual(_resolve_can_id("left", None), 0x28)
        self.assertEqual(_resolve_can_id("right", "0x28"), 0x28)

    def test_console_modes_are_mutually_exclusive_and_follow_is_explicit(self):
        state = ConsoleModeState()
        self.assertEqual(state.mode, ConsoleMode.OBJECT_GRASP)
        self.assertFalse(state.follow_enabled)

        state.switch(ConsoleMode.HAND_FOLLOW)
        self.assertFalse(state.can_send_hand(now=1.0, lost_timeout=0.5))
        self.assertTrue(state.enable_follow(emergency_stopped=False))
        state.observe_hand(detected=True, now=1.0, lost_timeout=0.5)
        self.assertEqual(state.tracking_state, TrackingState.TRACKING)
        self.assertTrue(state.can_send_hand(now=1.1, lost_timeout=0.5))

        state.observe_hand(detected=False, now=1.3, lost_timeout=0.5)
        self.assertEqual(state.tracking_state, TrackingState.HOLDING_LAST)
        state.observe_hand(detected=False, now=1.6, lost_timeout=0.5)
        self.assertEqual(state.tracking_state, TrackingState.PAUSED_LOST)
        self.assertFalse(state.can_send_hand(now=1.6, lost_timeout=0.5))

        state.observe_hand(detected=True, now=1.7, lost_timeout=0.5)
        self.assertTrue(state.can_send_hand(now=1.7, lost_timeout=0.5))
        state.switch(ConsoleMode.OBJECT_GRASP)
        self.assertFalse(state.follow_enabled)

    def test_mapping_and_safety_contract(self):
        mapper = HandMapper(CHANNELS)
        opened = mapper.map_normalized({name: 0.0 for name in CHANNEL_ORDER})
        closed_input = {name: 1.0 for name in CHANNEL_ORDER}
        closed_input["thumb_abduction"] = 0.0
        closed = mapper.map_normalized(closed_input)

        self.assertEqual(len(opened), 6)
        self.assertTrue(all(0 <= value <= 255 for value in opened + closed))
        for index in (0, 2, 3, 4, 5):
            self.assertGreater(opened[index], closed[index])
        self.assertEqual(opened[1], CHANNELS["thumb_abduction"]["min"])
        self.assertEqual(
            mapper.map_normalized({**closed_input, "thumb_abduction": 1.0})[1],
            CHANNELS["thumb_abduction"]["max"],
        )

        command_filter = CommandFilter(ema_alpha=0.25, deadband=3, max_delta=12)
        first = command_filter.apply([0] * 6)
        second = command_filter.apply([255] * 6)
        third = command_filter.apply([255] * 6)
        self.assertEqual(first, [0] * 6)
        self.assertTrue(all(0 < value <= 12 for value in second))
        self.assertTrue(all(0 < b - a <= 12 for a, b in zip(second, third)))

    def test_object_grasp_requires_arming_and_stable_target(self):
        machine = GraspStateMachine(
            grasp_zone=(0.3, 0.2, 0.7, 0.8),
            min_area_ratio=0.01,
            max_area_ratio=0.4,
            stable_frames=3,
            center_tolerance=0.08,
        )
        target = TargetObservation("cup", 0.9, 0.5, 0.5, 0.08)
        outside = TargetObservation("cup", 0.9, 0.9, 0.5, 0.08)

        machine.update(target)
        self.assertEqual(machine.state, GraspState.DISARMED)
        machine.arm()
        machine.update(outside)
        self.assertEqual(machine.stable_count, 0)
        machine.update(target)
        machine.update(TargetObservation("cup", 0.9, 0.52, 0.49, 0.08))
        self.assertEqual(machine.state, GraspState.ARMED)
        machine.update(TargetObservation("cup", 0.9, 0.51, 0.50, 0.08))
        self.assertEqual(machine.state, GraspState.CLOSING)
        machine.mark_closed()
        machine.update(None)
        self.assertEqual(machine.state, GraspState.HOLDING)
        machine.reset_after_open()
        self.assertEqual(machine.state, GraspState.DISARMED)

    def test_generic_foreground_detects_new_object_in_grasp_zone(self):
        detector = ForegroundDetector(
            pixel_threshold=25,
            min_contour_area_ratio=0.01,
            max_changed_area_ratio=0.7,
        )
        background = np.zeros((200, 300, 3), dtype=np.uint8)
        frame = background.copy()
        frame[70:140, 120:185] = 255
        detector.capture_background(background)

        self.assertIsNone(detector.detect(background, (0.25, 0.2, 0.7, 0.8)))
        detection = detector.detect(frame, (0.25, 0.2, 0.7, 0.8))
        self.assertIsNotNone(detection)
        self.assertEqual(detection.label, "generic-object")
        center_x, center_y = detection.center_normalized
        self.assertTrue(0.4 < center_x < 0.6)
        self.assertTrue(0.4 < center_y < 0.6)

    def test_web_console_status_and_actions(self):
        self.assertTrue(
            {
                "mode-hand",
                "mode-object",
                "follow-enable",
                "follow-pause",
                "hand-left",
                "hand-right",
            }
            <= ALLOWED_ACTIONS
        )

        class FakeRuntime:
            def status_snapshot(self):
                return {
                    "state": "DISARMED",
                    "backend": "dry-run",
                    "pose": [250] * 6,
                }

            def enqueue_action(self, action):
                return action in {
                    "arm",
                    "disarm",
                    "open",
                    "stop",
                    "mode-hand",
                    "mode-object",
                    "follow-enable",
                    "follow-pause",
                    "hand-left",
                    "hand-right",
                }

            def mjpeg_stream(self):
                return iter(())

        app = create_app(FakeRuntime())
        client = app.test_client()

        response = client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["pose"], [250] * 6)

        response = client.post("/api/action", json={"action": "arm"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json(), {"accepted": True, "action": "arm"})

        for action in (
            "mode-hand",
            "mode-object",
            "follow-enable",
            "follow-pause",
            "hand-left",
            "hand-right",
        ):
            response = client.post("/api/action", json={"action": action})
            self.assertEqual(response.status_code, 202)

        response = client.post("/api/action", json={"action": "unknown"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["accepted"], False)


if __name__ == "__main__":
    unittest.main()
