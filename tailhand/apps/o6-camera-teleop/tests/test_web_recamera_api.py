from pathlib import Path
import unittest

import yaml

from control.console_mode import ConsoleModeState, VisionSource
from control.grasp_state import GraspState, GraspStateMachine
from vision.object_detector import ObjectDetection
from web_console import (
    ALLOWED_ACTIONS,
    WebConsoleRuntime,
    _closest_target_to_center,
    _update_rgb_grasp,
    create_app,
)


def detection(label, x, y):
    return ObjectDetection(label, 0.8, x, y, 20, 20, 100, 100)


class FakeRuntime:
    def status_snapshot(self):
        return {"vision_source": "recamera", "recamera_connected": True}

    def enqueue_action(self, action):
        return action in ALLOWED_ACTIONS

    def mjpeg_stream(self):
        return iter(())

    def depth_mjpeg_stream(self):
        return iter(())


class FakeController:
    def __init__(self, backend="dry-run", emergency_stopped=False):
        self.backend = backend
        self.emergency_stopped = emergency_stopped


class ReCameraWebTest(unittest.TestCase):
    def test_actions_and_status_contract(self):
        self.assertIn("source-recamera", ALLOWED_ACTIONS)
        self.assertIn("manual-grasp", ALLOWED_ACTIONS)
        client = create_app(FakeRuntime()).test_client()
        for action in ("source-recamera", "manual-grasp"):
            with self.subTest(action=action):
                response = client.post("/api/action", json={"action": action})
                self.assertEqual(response.status_code, 202)

        config_path = Path(__file__).parents[1] / "config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        status = WebConsoleRuntime(config, 0, True, config_path).status_snapshot()
        self.assertTrue(
            {
                "recamera_connected",
                "recamera_fps",
                "recamera_frame_age_ms",
                "recamera_last_error",
            }
            <= status.keys()
        )

    def test_center_target_prefers_smallest_center_distance(self):
        selected = _closest_target_to_center(
            [
                detection("edge", 0, 0),
                detection("center", 40, 40),
            ]
        )

        self.assertEqual(selected.label, "center")
        self.assertIsNone(_closest_target_to_center([]))

    def test_manual_close_uses_explicit_state_transition(self):
        machine = GraspStateMachine((0.2, 0.2, 0.8, 0.8), 0.01, 0.5, 8, 0.1)

        self.assertTrue(machine.start_manual_close())
        self.assertEqual(machine.state, GraspState.CLOSING)
        self.assertFalse(machine.start_manual_close())

    def test_recamera_recovery_replaces_stale_disconnect_event(self):
        config_path = Path(__file__).parents[1] / "config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        runtime = WebConsoleRuntime(config, 0, True, config_path)
        runtime._set_status(
            recamera_connected=False,
            last_event="reCamera RTSP 未连接，不能执行保守握合",
        )

        self.assertTrue(hasattr(runtime, "_set_recamera_status"))
        runtime._set_recamera_status(True, 12.3, 59.0, None)

        status = runtime.status_snapshot()
        self.assertTrue(status["recamera_connected"])
        self.assertIn("RTSP 已连接", status["last_event"])
        self.assertIn("自动抓取", status["last_event"])

    def test_manual_grasp_allows_intentional_dry_run_and_rejects_fallback(self):
        config_path = Path(__file__).parents[1] / "config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        runtime = WebConsoleRuntime(config, 0, True, config_path)
        runtime._set_status(recamera_connected=True)
        mode_state = ConsoleModeState()
        mode_state.switch_source(VisionSource.RECAMERA)
        safe_open = config["o6"]["safe_open_pose"]

        machine = GraspStateMachine((0.2, 0.2, 0.8, 0.8), 0.01, 0.5, 8, 0.1)
        result = runtime._apply_action(
            "manual-grasp",
            None,
            mode_state,
            machine,
            None,
            FakeController(),
            None,
            None,
            None,
            None,
            safe_open,
        )
        self.assertIsNone(result)
        self.assertEqual(machine.state, GraspState.CLOSING)

        machine.reset_after_open()
        runtime._apply_action(
            "manual-grasp",
            None,
            mode_state,
            machine,
            None,
            FakeController(backend="dry-run-fallback"),
            None,
            None,
            None,
            None,
            safe_open,
        )
        self.assertEqual(machine.state, GraspState.DISARMED)
        self.assertIn("拒绝伪装", runtime.status_snapshot()["last_event"])

    def test_recamera_arm_requires_stream_and_rejects_hardware_fallback(self):
        config_path = Path(__file__).parents[1] / "config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        runtime = WebConsoleRuntime(config, 0, True, config_path)
        mode_state = ConsoleModeState()
        mode_state.switch_source(VisionSource.RECAMERA)
        safe_open = config["o6"]["safe_open_pose"]

        def apply_arm(machine, controller):
            return runtime._apply_action(
                "arm",
                None,
                mode_state,
                machine,
                None,
                controller,
                None,
                None,
                None,
                None,
                safe_open,
            )

        machine = GraspStateMachine((0.2, 0.2, 0.8, 0.8), 0.01, 0.5, 8, 0.1)
        runtime._set_status(recamera_connected=False)
        apply_arm(machine, FakeController())
        self.assertEqual(machine.state, GraspState.DISARMED)
        self.assertIn("RTSP", runtime.status_snapshot()["last_event"])

        runtime._set_status(recamera_connected=True)
        apply_arm(machine, FakeController(backend="dry-run-fallback"))
        self.assertEqual(machine.state, GraspState.DISARMED)
        self.assertIn("拒绝", runtime.status_snapshot()["last_event"])

        apply_arm(machine, FakeController())
        self.assertEqual(machine.state, GraspState.ARMED)
        self.assertIn("稳定 8 帧", runtime.status_snapshot()["last_event"])

    def test_recamera_stable_target_closes_on_eighth_update(self):
        machine = GraspStateMachine((0.2, 0.2, 0.8, 0.8), 0.01, 0.5, 8, 0.1)
        machine.arm()
        target = detection("cell phone", 40, 40)

        for _ in range(7):
            _update_rgb_grasp(
                machine,
                VisionSource.RECAMERA,
                target,
                hand_blocked=False,
            )
            self.assertEqual(machine.state, GraspState.ARMED)

        _update_rgb_grasp(
            machine,
            VisionSource.RECAMERA,
            target,
            hand_blocked=False,
        )
        self.assertEqual(machine.state, GraspState.CLOSING)

    def test_recamera_target_loss_or_hand_resets_stability(self):
        machine = GraspStateMachine((0.2, 0.2, 0.8, 0.8), 0.01, 0.5, 8, 0.1)
        machine.arm()
        target = detection("cell phone", 40, 40)

        for _ in range(5):
            _update_rgb_grasp(
                machine,
                VisionSource.RECAMERA,
                target,
                hand_blocked=False,
            )
        _update_rgb_grasp(
            machine,
            VisionSource.RECAMERA,
            None,
            hand_blocked=False,
        )
        self.assertEqual(machine.stable_count, 0)

        for _ in range(5):
            _update_rgb_grasp(
                machine,
                VisionSource.RECAMERA,
                target,
                hand_blocked=False,
            )
        _update_rgb_grasp(
            machine,
            VisionSource.RECAMERA,
            target,
            hand_blocked=True,
        )
        self.assertEqual(machine.stable_count, 0)
        self.assertEqual(machine.state, GraspState.ARMED)

    def test_static_console_exposes_recamera_controls(self):
        web = Path(__file__).parents[1] / "web"
        html = (web / "index.html").read_text(encoding="utf-8")
        script = (web / "app.js").read_text(encoding="utf-8")

        self.assertIn('data-action="source-recamera"', html)
        self.assertIn('data-action="manual-grasp"', html)
        self.assertIn('id="recameraDiagnostics"', html)
        self.assertIn('status.vision_source === "recamera"', script)
        self.assertIn("recamera_frame_age_ms", script)
        self.assertIn(
            'document.querySelector("#automaticGraspActions").hidden = handMode;',
            script,
        )
        self.assertIn("可布防自动抓取，或手动保守握合", script)
        self.assertIn("showRecamera && (!recameraConnected", script)

    def test_default_config_points_to_connected_recamera(self):
        config_path = Path(__file__).parents[1] / "config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

        self.assertEqual(
            config["recamera"]["rtsp_url"],
            "rtsp://admin:admin@192.168.254.153:554/live",
        )
        self.assertGreater(config["recamera"]["stale_timeout_ms"], 0)


if __name__ == "__main__":
    unittest.main()
