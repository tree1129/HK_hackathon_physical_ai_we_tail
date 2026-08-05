from pathlib import Path
import unittest


PROJECT_DIR = Path(__file__).parents[1]
WEB_DIR = PROJECT_DIR / "web"


class GestureCameraUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        cls.app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    def test_mobile_camera_controls_are_hidden_by_default(self):
        for control_id in ("gestureMobileSourceButton", "mobileCameraControls"):
            marker = f'id="{control_id}"'
            start = self.html.index(marker)
            tag_end = self.html.index(">", start)
            self.assertIn("hidden", self.html[start:tag_end])

    def test_mobile_camera_controls_require_a_touch_device(self):
        self.assertIn('navigator.maxTouchPoints > 0', self.app_js)
        self.assertIn('matchMedia("(pointer: coarse)").matches', self.app_js)
        self.assertIn('mobileSourceButton.hidden = !mobileCameraClient', self.app_js)
        self.assertIn('mobileControls.hidden = !mobileCameraClient', self.app_js)

    def test_mobile_camera_is_labeled_as_the_current_device(self):
        self.assertIn('id="gestureMobileSourceButton"', self.html)
        self.assertIn('>本机相机</button>', self.html)


if __name__ == "__main__":
    unittest.main()
