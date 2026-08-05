import unittest

import numpy as np
import web_console

from control.filters import CommandFilter
from control.console_mode import ConsoleMode, ConsoleModeState, TrackingState, VisionSource
from control.grasp_state import GraspState, GraspStateMachine, TargetObservation
from control.hand_mapper import CHANNEL_ORDER, HandMapper
from control.o6_controller import _resolve_can_id
from vision.foreground_detector import ForegroundDetector
from web_console import ALLOWED_ACTIONS, WebConsoleRuntime, create_app


CHANNELS = {
    "thumb_flexion": {"open": 255, "closed": 20},
    "thumb_abduction": {"min": 30, "max": 220},
    "index_flexion": {"open": 255, "closed": 20},
    "middle_flexion": {"open": 255, "closed": 20},
    "ring_flexion": {"open": 255, "closed": 20},
    "pinky_flexion": {"open": 255, "closed": 20},
}


class MapperAndFilterTest(unittest.TestCase):
    def test_fist_pose_uses_active_hand_mapping(self):
        mapper = HandMapper(CHANNELS)

        self.assertEqual(
            web_console._fist_pose(mapper, "right"),
            [20, 30, 20, 20, 20, 20],
        )
        self.assertEqual(
            web_console._fist_pose(mapper, "left"),
            [20, 220, 20, 20, 20, 20],
        )

    def test_fist_action_pauses_follow_and_moves_once(self):
        class RecordingController:
            emergency_stopped = False

            def __init__(self):
                self.moves = []
                self.config = {"hand_type": "right"}

            def move(self, pose):
                self.moves.append(pose.copy())

        runtime = object.__new__(WebConsoleRuntime)
        events = {}
        runtime._set_status = lambda **values: events.update(values)
        mode_state = ConsoleModeState()
        mode_state.switch(ConsoleMode.HAND_FOLLOW)
        mode_state.enable_follow(emergency_stopped=False)
        controller = RecordingController()
        hand_filter = CommandFilter(ema_alpha=0.25, deadband=3, max_delta=12)
        expected_fist_pose = [20, 30, 20, 20, 20, 20]

        changed_pose = runtime._apply_action(
            action="fist",
            frame=None,
            mode_state=mode_state,
            machine=None,
            foreground=None,
            controller=controller,
            hand_filter=hand_filter,
            grasp_filter=None,
            depth_gate=None,
            calibrator=None,
            safe_open=[255] * 6,
            hand_mapper=HandMapper(CHANNELS),
        )

        self.assertFalse(mode_state.follow_enabled)
        self.assertEqual(controller.moves, [expected_fist_pose])
        self.assertEqual(changed_pose, expected_fist_pose)
        self.assertIn("已暂停跟随并执行一键握拳", events["last_event"])

    def test_legacy_console_mode_state_positional_arguments_are_preserved(self):
        state = ConsoleModeState(ConsoleMode.HAND_FOLLOW, True, TrackingState.TRACKING, 1.0)

        self.assertEqual(state.mode, ConsoleMode.HAND_FOLLOW)
        self.assertTrue(state.follow_enabled)
        self.assertEqual(state.tracking_state, TrackingState.TRACKING)
        self.assertEqual(state.last_hand_time, 1.0)
        self.assertEqual(state.vision_source, VisionSource.MAC_CAMERA)

    def test_mac_camera_source_switch_pauses_follow_without_changing_mode(self):
        state = ConsoleModeState()
        state.switch(ConsoleMode.HAND_FOLLOW)
        self.assertTrue(state.enable_follow(emergency_stopped=False))

        state.switch_source(VisionSource.MAC_CAMERA)

        self.assertEqual(state.vision_source, VisionSource.MAC_CAMERA)
        self.assertEqual(state.mode, ConsoleMode.HAND_FOLLOW)
        self.assertFalse(state.follow_enabled)

    def test_vision_source_switch_resets_active_controls(self):
        state = ConsoleModeState()
        state.switch(ConsoleMode.HAND_FOLLOW)
        self.assertTrue(state.enable_follow(emergency_stopped=False))
        state.switch_source(VisionSource.IPHONE_LIDAR)
        self.assertEqual(state.vision_source, VisionSource.IPHONE_LIDAR)
        self.assertEqual(state.mode, ConsoleMode.OBJECT_GRASP)
        self.assertFalse(state.follow_enabled)

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

    def test_object_grasp_accumulates_stability_while_depth_close_is_blocked(self):
        machine = GraspStateMachine(
            grasp_zone=(0.3, 0.2, 0.7, 0.8),
            min_area_ratio=0.01,
            max_area_ratio=0.4,
            stable_frames=3,
            center_tolerance=0.08,
            auto_arm=True,
        )
        target = TargetObservation("cup", 0.9, 0.5, 0.5, 0.08)

        for _ in range(3):
            self.assertEqual(machine.update(target, allow_close=False), GraspState.ARMED)
        self.assertEqual(machine.stable_count, 3)
        self.assertEqual(machine.update(target, allow_close=True), GraspState.CLOSING)

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
                "fist",
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
                    "fist",
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
            "fist",
            "hand-left",
            "hand-right",
        ):
            response = client.post("/api/action", json={"action": action})
            self.assertEqual(response.status_code, 202)

        response = client.post("/api/action", json={"action": "unknown"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["accepted"], False)

    def test_web_assets_expose_tail3_shell_and_real_controls(self):
        class FakeRuntime:
            def status_snapshot(self):
                return {"state": "DISARMED", "backend": "dry-run", "pose": [250] * 6}

            def enqueue_action(self, action):
                return action in ALLOWED_ACTIONS

            def mjpeg_stream(self):
                return iter(())

            def depth_mjpeg_stream(self):
                return iter(())

        client = create_app(FakeRuntime()).test_client()
        responses = [
            client.get("/"),
            client.get("/assets/styles.css"),
            client.get("/assets/app.js"),
        ]
        try:
            html, css, javascript = [response.get_data(as_text=True) for response in responses]
        finally:
            for response in responses:
                response.close()

        for page in ("home", "gesture", "agent", "devices", "history", "settings"):
            self.assertIn(f'id="page-{page}"', html)
        self.assertIn('class="mobile-safety-dock"', html)
        self.assertIn('data-src="/video_feed"', html)
        self.assertIn('src="/assets/assets/agent-demo-scene.png"', html)
        self.assertIn('src="/assets/agent_demo.js"', html)
        self.assertIn('data-action="fist"', html)
        self.assertIn("一键握拳", html)
        self.assertIn("演示", html)
        self.assertIn("@media", css)
        self.assertIn("@keyframes toast-in", css)
        self.assertIn(".button { min-height: 44px;", css)
        self.assertIn(".gesture-action-grid", css)

        for action in (
            "hand-left",
            "hand-right",
            "mode-hand",
            "mode-object",
            "source-mac-camera",
            "source-iphone-lidar",
            "depth-calibrate-contact",
            "depth-clear-calibration",
            "follow-enable",
            "follow-pause",
            "fist",
            "arm",
            "disarm",
            "open",
            "stop",
        ):
            self.assertIn(f'"{action}"', javascript)
        self.assertIn('WAITING_MODE', javascript)


if __name__ == "__main__":
    unittest.main()
