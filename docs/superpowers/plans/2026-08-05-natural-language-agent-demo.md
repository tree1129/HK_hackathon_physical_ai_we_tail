# O6 Natural Language Agent Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a responsive, deterministic front-end demo where text or voice commands select Mock visual targets, create multi-step plans, require confirmation, and play safe execution states without calling an Agent backend or O6 action endpoint.

**Architecture:** A standalone `agent_demo.js` owns Mock scene data, constrained natural-language parsing, the task state machine, speech progressive enhancement, timers, and Agent DOM rendering. Existing `app.js` keeps global navigation and runtime status, while the Agent page markup and CSS become an Agent-first 38/62 split that stacks cleanly on mobile.

**Tech Stack:** HTML5, CSS, browser JavaScript, Web Speech API progressive enhancement, Node.js built-in test runner, Python `unittest`, Playwright browser verification.

---

## File Map

- Create `apps/o6-camera-teleop/web/agent_demo.js`: deterministic Agent core and page controller.
- Create `apps/o6-camera-teleop/web/assets/agent-demo-scene.png`: local tabletop Mock scene.
- Create `apps/o6-camera-teleop/tests/test_agent_demo.js`: state-machine behavior tests.
- Create `apps/o6-camera-teleop/tests/test_agent_demo_ui.py`: static UI and safety-contract tests.
- Modify `apps/o6-camera-teleop/web/index.html`: Agent-first semantic workspace and script loading.
- Modify `apps/o6-camera-teleop/web/styles.css`: desktop, tablet, and mobile Agent layout.
- Modify `apps/o6-camera-teleop/web/app.js`: remove the old demo timer and forward global emergency stop to the Mock controller.

### Task 1: Deterministic Agent Core

**Files:**
- Create: `apps/o6-camera-teleop/tests/test_agent_demo.js`
- Create: `apps/o6-camera-teleop/web/agent_demo.js`

- [ ] **Step 1: Write failing state-machine tests**

Create Node tests that load the browser script in a VM and verify the public core:

```javascript
const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(new URL("../web/agent_demo.js", `file://${__filename}`), "utf8");
const context = { console, globalThis: {} };
vm.runInNewContext(source, context);
const { AgentDemoMachine } = context.globalThis.AgentDemoCore;

test("plans a specific multi-step task but waits for confirmation", () => {
  const machine = new AgentDemoMachine();
  const state = machine.submit("抓住红色杯子，然后放到左侧托盘");
  assert.equal(state.phase, "planned");
  assert.equal(state.target.id, "red-cup");
  assert.equal(state.destination.id, "left-tray");
  assert.equal(state.plan.length, 4);
  assert.equal(state.currentStep, -1);
});

test("asks for clarification when a cup is ambiguous", () => {
  const machine = new AgentDemoMachine();
  const state = machine.submit("抓住杯子");
  assert.equal(state.phase, "clarifying");
  assert.deepEqual(Array.from(state.candidates, item => item.id), ["red-cup", "blue-cup"]);
});

test("runs only after explicit confirmation", () => {
  const machine = new AgentDemoMachine();
  machine.submit("把红色杯子放到左侧托盘");
  assert.equal(machine.advance().phase, "planned");
  assert.equal(machine.confirm().phase, "running");
  assert.equal(machine.advance().currentStep, 0);
});

test("pauses on target loss and stops immediately", () => {
  const machine = new AgentDemoMachine();
  machine.submit("把红色杯子放到左侧托盘");
  machine.confirm();
  machine.advance();
  assert.equal(machine.loseTarget().phase, "paused");
  assert.equal(machine.stop().phase, "stopped");
});
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
cd apps/o6-camera-teleop
node --test tests/test_agent_demo.js
```

Expected: FAIL because `web/agent_demo.js` and `AgentDemoMachine` do not exist.

- [ ] **Step 3: Implement the minimal pure state machine**

Define immutable Mock objects for `red-cup`, `blue-cup`, and `left-tray`. Implement `submit`, `clarify`, `confirm`, `advance`, `loseTarget`, `resume`, `stop`, and `reset`. `submit` must recognize red/红, blue/蓝, cup/杯, tray/托盘, left/左, confirmation phrases, and stop phrases. A specific target produces a four-step plan; an ambiguous cup enters `clarifying`; an unknown task enters `idle` with an error message. Export through:

```javascript
globalThis.AgentDemoCore = {
  AgentDemoMachine,
  MOCK_OBJECTS,
  isConfirmCommand,
  isStopCommand,
};
```

- [ ] **Step 4: Run tests and verify GREEN**

Run `node --test tests/test_agent_demo.js`.

Expected: all core state tests pass with zero failures.

- [ ] **Step 5: Commit the core**

```bash
git add apps/o6-camera-teleop/web/agent_demo.js apps/o6-camera-teleop/tests/test_agent_demo.js
git commit -m "feat: add deterministic agent demo core"
```

### Task 2: Agent-First Workspace And Mock Scene

**Files:**
- Create: `apps/o6-camera-teleop/tests/test_agent_demo_ui.py`
- Create: `apps/o6-camera-teleop/web/assets/agent-demo-scene.png`
- Modify: `apps/o6-camera-teleop/web/index.html`

- [ ] **Step 1: Write failing UI contract tests**

Create a `unittest.TestCase` that reads the static files and asserts:

```python
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
        self.assertIn(marker, self.html)

def test_agent_demo_loads_without_calling_a_new_backend(self):
    self.assertIn('/assets/agent_demo.js', self.html)
    self.assertNotIn('/api/agent', self.agent_js)
    self.assertNotIn('fetch(', self.agent_js)
```

- [ ] **Step 2: Run UI tests and verify RED**

Run:

```bash
cd apps/o6-camera-teleop
.venv/bin/python -m unittest tests.test_agent_demo_ui -v
```

Expected: FAIL because the new Agent markup and script are absent.

- [ ] **Step 3: Add the local Mock scene asset**

Generate one clear 16:9 tabletop image containing a red cup, a blue cup, and a shallow tray on the left. Keep the scene bright, inspectable, and free of text so HTML overlays can supply labels. Save it as `web/assets/agent-demo-scene.png`.

- [ ] **Step 4: Replace the existing Agent page markup**

Use two sibling panels inside `.agent-demo-layout`. The left `.agent-perception-panel` contains the image, object overlays, candidate chips, and Mock status. The right `.agent-workspace-panel` contains the conversation log, plan list, confirmation controls, wake-word toggle, voice-demo trigger, text input, microphone, and send button. Keep every control as a real `button`, `input`, or `textarea` with an accessible label.

Load scripts in this order at the end of `body`:

```html
<script src="/assets/agent_demo.js"></script>
<script src="/assets/app.js"></script>
```

- [ ] **Step 5: Run UI tests and verify GREEN**

Run `.venv/bin/python -m unittest tests.test_agent_demo_ui -v`.

Expected: all Agent UI contract tests pass.

- [ ] **Step 6: Commit the workspace**

```bash
git add apps/o6-camera-teleop/web/index.html \
  apps/o6-camera-teleop/web/assets/agent-demo-scene.png \
  apps/o6-camera-teleop/tests/test_agent_demo_ui.py
git commit -m "feat: build agent demo workspace"
```

### Task 3: Interaction, Speech, And Responsive Rendering

**Files:**
- Modify: `apps/o6-camera-teleop/web/agent_demo.js`
- Modify: `apps/o6-camera-teleop/web/app.js`
- Modify: `apps/o6-camera-teleop/web/styles.css`
- Modify: `apps/o6-camera-teleop/tests/test_agent_demo.js`
- Modify: `apps/o6-camera-teleop/tests/test_agent_demo_ui.py`

- [ ] **Step 1: Extend failing tests for speech and safety**

Add tests proving that “确认执行” begins a planned task, “停止” enters `stopped`, clarification selection generates a plan, resuming after target loss returns to `running`, and repeated confirmation does not create a second run. Add UI assertions for `@media (max-width: 960px)`, `.agent-demo-layout`, `grid-template-columns`, `aspect-ratio: 16 / 9`, and wrapping action controls.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
cd apps/o6-camera-teleop
node --test tests/test_agent_demo.js
.venv/bin/python -m unittest tests.test_agent_demo_ui -v
```

Expected: new speech, safety, and responsive assertions fail.

- [ ] **Step 3: Implement Agent page rendering and timers**

Initialize the controller only when required DOM nodes exist. Render every state into the conversation log, target overlays, plan items, badges, and enabled controls. Use one stored timer for `running`; each tick calls `advance`, and completion clears it. `stop`, `cancel`, page departure, and global emergency stop clear the timer immediately. Expose:

```javascript
globalThis.agentDemoController = {
  stop: () => controller.stop(),
  destroy: () => controller.destroy(),
};
```

- [ ] **Step 4: Implement progressive voice interaction**

Use `SpeechRecognition || webkitSpeechRecognition` with `lang = "zh-CN"`, interim status text, and final transcripts routed through the same submit path as typed text. When unavailable or denied, the microphone and explicit voice-demo button play deterministic transcripts. Wake mode restarts recognition after `onend`; only phrases containing `Tail`, `tail`, `泰尔`, or `小助手` begin a new task. Stop phrases bypass the wake requirement.

- [ ] **Step 5: Integrate global emergency stop without Agent API calls**

Remove `demoStep`, `demoTimer`, and `runAgentDemo` from `app.js`. Before existing real stop handling, call `globalThis.agentDemoController?.stop()`. Do not add any Agent endpoint or Agent action to `REAL_ACTIONS`.

- [ ] **Step 6: Add responsive CSS**

At desktop widths use `grid-template-columns: minmax(260px, .62fr) minmax(430px, 1fr)`. At `960px` use one column with the Agent workspace first through CSS grid areas. At `620px`, use a 16:9 scene, vertical plan items, wrapping action controls, 44px minimum touch targets, and `min-width: 0` on all shrinking children. Honor `prefers-reduced-motion` and preserve bottom navigation clearance.

- [ ] **Step 7: Run focused and full tests**

Run:

```bash
cd apps/o6-camera-teleop
node --test tests/test_agent_demo.js
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Expected: JavaScript tests pass and the Python suite reports zero failures.

- [ ] **Step 8: Commit the complete interaction**

```bash
git add apps/o6-camera-teleop/web/agent_demo.js \
  apps/o6-camera-teleop/web/app.js \
  apps/o6-camera-teleop/web/styles.css \
  apps/o6-camera-teleop/tests/test_agent_demo.js \
  apps/o6-camera-teleop/tests/test_agent_demo_ui.py
git commit -m "feat: complete voice agent demo interactions"
```

### Task 4: Browser Verification And Publish

**Files:**
- Modify: `apps/o6-camera-teleop/README.md`

- [ ] **Step 1: Document the demo**

Add a concise section covering the Agent page, primary success phrase, ambiguity phrase, voice fallback, confirmation requirement, and the guarantee that the Mock Agent never sends additional hardware commands.

- [ ] **Step 2: Start the local application**

Run:

```bash
cd apps/o6-camera-teleop
./run_web.sh --dry-run
```

Expected: Flask serves the existing console and the Agent page loads at the printed local URL.

- [ ] **Step 3: Verify desktop and mobile behavior**

With Playwright, visit the Agent page at `1440x900`, `1024x768`, `430x932`, and `390x844`. Capture screenshots and verify no horizontal overflow, clipped controls, overlapping fixed docks, or blank Mock image. Exercise success, ambiguity, resume-after-loss, voice-demo, and emergency-stop paths.

- [ ] **Step 4: Run final verification**

Run:

```bash
cd apps/o6-camera-teleop
node --test tests/test_agent_demo.js
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
git diff --check
git status -sb
```

Expected: all tests pass, `git diff --check` is clean, and only intentional Agent files plus README are modified.

- [ ] **Step 5: Commit and push**

```bash
git add apps/o6-camera-teleop/README.md
git commit -m "docs: explain natural language agent demo"
git push hk codex/agent-improvements-20260805
```
