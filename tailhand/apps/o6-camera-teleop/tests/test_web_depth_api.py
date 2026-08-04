from pathlib import Path
import unittest

import yaml

from web_console import (
    ALLOWED_ACTIONS,
    WebConsoleRuntime,
    confidence_value,
    create_app,
)


NEW_ACTIONS = {
    "source-mac-camera",
    "source-iphone-lidar",
    "depth-calibrate-contact",
    "depth-clear-calibration",
}


class FakeRuntime:
    def status_snapshot(self):
        return {
            "vision_source": "iphone-lidar",
            "pairing_code": "123456",
            "depth_phase": "PREGRASP_OPEN",
        }

    def enqueue_action(self, action):
        return action in ALLOWED_ACTIONS

    def mjpeg_stream(self):
        return iter(())

    def depth_mjpeg_stream(self):
        return iter(())


class WebDepthApiTest(unittest.TestCase):
    def test_depth_routes_and_actions_are_exposed(self):
        self.assertTrue(NEW_ACTIONS <= ALLOWED_ACTIONS)
        client = create_app(FakeRuntime()).test_client()
        self.assertEqual(client.get("/depth_feed").status_code, 200)
        for action in NEW_ACTIONS:
            with self.subTest(action=action):
                response = client.post("/api/action", json={"action": action})
                self.assertEqual(response.status_code, 202)

    def test_status_contract_includes_lidar_safety_fields(self):
        config_path = Path(__file__).parents[1] / "config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        runtime = WebConsoleRuntime(config, 0, True, config_path)
        status = runtime.status_snapshot()
        self.assertTrue(
            {
                "vision_source",
                "iphone_connected",
                "iphone_device",
                "depth_fps",
                "depth_latency_ms",
                "depth_valid_ratio",
                "depth_calibrated",
                "contact_depth_mm",
                "signed_distance_mm",
                "depth_phase",
                "pairing_code",
            }
            <= status.keys()
        )
        self.assertEqual(len(status["pairing_code"]), 6)
        self.assertTrue(status["pairing_code"].isdigit())

    def test_confidence_lookup_is_strict(self):
        self.assertEqual(confidence_value("low"), 0)
        self.assertEqual(confidence_value("medium"), 1)
        self.assertEqual(confidence_value("high"), 2)
        with self.assertRaises(ValueError):
            confidence_value("unknown")


if __name__ == "__main__":
    unittest.main()
