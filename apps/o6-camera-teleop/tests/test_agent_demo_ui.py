from pathlib import Path
import unittest


PROJECT_DIR = Path(__file__).parents[1]
WEB_DIR = PROJECT_DIR / "web"


class AgentDemoUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        cls.css = (WEB_DIR / "styles.css").read_text(encoding="utf-8")
        cls.agent_js = (WEB_DIR / "agent_demo.js").read_text(encoding="utf-8")

    def test_agent_workspace_exposes_mock_visual_and_conversation_controls(self):
        for marker in (
            'class="agent-demo-layout"',
            'id="agentMockScene"',
            'id="agentConversation"',
            'id="agentPlan"',
            'id="agentTaskInput"',
            'id="agentMicButton"',
            'id="agentWakeToggle"',
            'id="agentConfirmButton"',
            'id="agentCancelButton"',
            'id="agentVoiceDemoButton"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_agent_workspace_uses_focused_task_structure(self):
        for marker in (
            'id="agentTaskMeta"',
            'id="agentEvidenceSummary"',
            'id="agentProgressTrack"',
            'id="agentCurrentStep"',
            'id="agentOutcome"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        self.assertNotIn('class="agent-object-list"', self.html)

    def test_agent_actions_start_contextually_hidden(self):
        for control_id in (
            "agentConfirmButton",
            "agentLoseTargetButton",
            "agentCancelButton",
            "agentRecoveryActions",
        ):
            marker = f'id="{control_id}"'
            start = self.html.index(marker)
            tag_end = self.html.index(">", start)
            self.assertIn("hidden", self.html[start:tag_end])

    def test_agent_demo_uses_a_local_scene_asset(self):
        self.assertIn('/assets/assets/agent-demo-scene.png', self.html)
        asset = WEB_DIR / "assets" / "agent-demo-scene.png"
        self.assertTrue(asset.is_file())
        self.assertGreater(asset.stat().st_size, 10_000)

    def test_agent_demo_loads_without_a_new_backend_contract(self):
        self.assertIn('<script src="/assets/agent_demo.js"></script>', self.html)
        self.assertLess(
            self.html.index('/assets/agent_demo.js'),
            self.html.index('/assets/app.js'),
        )
        self.assertNotIn('/api/agent', self.agent_js)
        self.assertNotIn('fetch(', self.agent_js)

    def test_agent_layout_defines_mobile_adaptation(self):
        self.assertIn(".agent-demo-layout", self.css)
        self.assertIn("grid-template-columns", self.css)
        self.assertIn("@media (max-width: 960px)", self.css)
        self.assertIn("aspect-ratio: 16 / 9", self.css)
        self.assertIn("min-height: 44px", self.css)

    def test_agent_layout_uses_task_first_density(self):
        self.assertIn("minmax(250px, .48fr) minmax(520px, 1fr)", self.css)
        self.assertIn(".agent-evidence-summary", self.css)
        self.assertIn(".agent-current-step", self.css)
        self.assertIn('.agent-workspace-panel[data-phase="completed"]', self.css)
        self.assertIn('grid-template-areas: "workspace" "perception"', self.css)

    def test_agent_controls_are_separate_from_real_actions(self):
        for control_id in (
            "agentMicButton",
            "agentConfirmButton",
            "agentCancelButton",
            "agentVoiceDemoButton",
        ):
            marker = f'id="{control_id}"'
            start = self.html.index(marker)
            tag_start = self.html.rfind("<button", 0, start)
            tag_end = self.html.index(">", start)
            self.assertNotIn("real-control", self.html[tag_start:tag_end])
            self.assertNotIn("data-action", self.html[tag_start:tag_end])

    def test_agent_controller_supports_browser_speech_and_mock_fallback(self):
        for marker in (
            "SpeechRecognition",
            "webkitSpeechRecognition",
            "agentDemoController",
            "triggerVoiceDemo",
            "startWakeMode",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.agent_js)

    def test_agent_controller_renders_compact_contextual_states(self):
        for marker in (
            "_trimConversation",
            "_renderOutcome",
            "workspace.dataset.phase",
            "progressTrack.style.width",
            "confirmButton.hidden",
            "loseTargetButton.hidden",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.agent_js)

    def test_global_emergency_stop_also_stops_the_demo(self):
        app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("agentDemoController?.stop()", app_js)
        self.assertNotIn("function runAgentDemo()", app_js)
        self.assertNotIn('$("#agentDemoButton")', app_js)


if __name__ == "__main__":
    unittest.main()
