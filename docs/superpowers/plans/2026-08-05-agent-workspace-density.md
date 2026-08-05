# Agent Workspace Density Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Agent page calmer and more credible by prioritizing the task workflow, showing only contextual controls, and driving deterministic perception/task metadata through the existing front-end state machine.

**Architecture:** Keep `AgentDemoMachine` as the deterministic source of truth and extend its snapshots with object evidence, task identity, timing, and result metadata. Keep the existing DOM controller, but render a compact transcript, focused current-step detail, contextual actions, and completion summary. Simplify the existing HTML/CSS rather than introducing a framework or backend contract.

**Tech Stack:** Vanilla JavaScript, HTML, CSS, Node built-in test runner, Python `unittest`, in-app Browser/Playwright verification.

---

### Task 1: Add deterministic perception and task metadata

**Files:**
- Modify: `apps/o6-camera-teleop/tests/test_agent_demo.js`
- Modify: `apps/o6-camera-teleop/web/agent_demo.js`

- [ ] **Step 1: Write failing metadata tests**

Add tests asserting that `MOCK_OBJECTS["red-cup"]` exposes `confidence`, `depthM`, `center`, `bbox`, and `graspStrategy`, and that a planned task exposes an ID, source, safety result, event timeline, and per-step duration:

```js
test("exposes realistic deterministic perception evidence", () => {
  const redCup = MOCK_OBJECTS["red-cup"];
  assert.equal(redCup.confidence, 0.92);
  assert.equal(redCup.depthM, 0.46);
  assert.deepEqual(Array.from(redCup.center), [0.22, 0.72]);
  assert.equal(redCup.graspStrategy, "top-pinch");
});

test("creates an auditable task with deterministic timing", () => {
  const machine = new AgentDemoMachine();
  const state = machine.submit("把红色杯子放到左侧托盘", "voice");
  assert.match(state.task.id, /^TASK-\d{3}$/);
  assert.equal(state.task.source, "voice");
  assert.equal(state.task.safety, "clear");
  assert.equal(state.plan[0].durationMs, 900);
  assert.equal(state.events[0].type, "task.created");
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `node --test tests/test_agent_demo.js`

Expected: FAIL because perception metadata, `task`, `events`, and `durationMs` are absent.

- [ ] **Step 3: Implement the minimal metadata model**

Extend frozen object fixtures with deterministic fields, accept `source` in `submit`, create sequential `TASK-001` identifiers, add `task`, `events`, and `result` to state, and define fixed step durations:

```js
"red-cup": Object.freeze({
  id: "red-cup", label: "红色杯子", kind: "cup", color: "red",
  confidence: 0.92, depthM: 0.46, center: [0.22, 0.72],
  bbox: [0.08, 0.58, 0.26, 0.32], graspStrategy: "top-pinch",
})
```

Snapshot arrays and nested task/result/event values so consumers cannot mutate machine state. On completion, populate elapsed time and a deterministic audit result.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `node --test tests/test_agent_demo.js`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/o6-camera-teleop/tests/test_agent_demo.js apps/o6-camera-teleop/web/agent_demo.js
git commit -m "feat: add realistic agent demo telemetry"
```

### Task 2: Simplify the Agent workspace structure

**Files:**
- Modify: `apps/o6-camera-teleop/tests/test_agent_demo_ui.py`
- Modify: `apps/o6-camera-teleop/web/index.html`

- [ ] **Step 1: Write failing structure tests**

Add assertions for the focused UI contracts and removal of the duplicate object list:

```python
def test_agent_workspace_uses_focused_task_structure(self):
    for marker in (
        'id="agentTaskMeta"',
        'id="agentEvidenceSummary"',
        'id="agentProgressTrack"',
        'id="agentCurrentStep"',
        'id="agentOutcome"',
    ):
        self.assertIn(marker, self.html)
    self.assertNotIn('class="agent-object-list"', self.html)
```

Add a test that the contextual action buttons include `hidden` in their initial markup instead of rendering a full disabled action wall.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m unittest tests.test_agent_demo_ui -v`

Expected: FAIL because the focused structure does not exist and the duplicate object list remains.

- [ ] **Step 3: Implement the focused HTML structure**

In `#page-agent`:

- Replace the three-row evidence list and object button list with `#agentEvidenceSummary`, containing target/depth, confidence, and safety values.
- Add `#agentTaskMeta` in the workspace header for task ID and source.
- Keep the transcript but add a compact completion surface `#agentOutcome`.
- Add `#agentProgressTrack` and `#agentCurrentStep` below the step rail.
- Keep existing button IDs for compatibility, but hide them initially and rename visible copy to the contextual commands described by the spec.
- Keep quick examples directly above the composer.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `.venv/bin/python -m unittest tests.test_agent_demo_ui -v`

Expected: all Agent UI tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/o6-camera-teleop/tests/test_agent_demo_ui.py apps/o6-camera-teleop/web/index.html
git commit -m "refactor: focus agent workspace structure"
```

### Task 3: Render compact state-specific interaction surfaces

**Files:**
- Modify: `apps/o6-camera-teleop/tests/test_agent_demo.js`
- Modify: `apps/o6-camera-teleop/tests/test_agent_demo_ui.py`
- Modify: `apps/o6-camera-teleop/web/agent_demo.js`

- [ ] **Step 1: Write failing interaction tests**

Add machine assertions that step evidence updates on advance, pause preserves the active step and accumulated time, and completion exposes a result summary. Add static assertions for `data-phase` rendering, transcript trimming, and outcome rendering helpers.

```js
test("completion produces a concise audit result", () => {
  const machine = new AgentDemoMachine();
  machine.submit("把红色杯子放到左侧托盘");
  machine.confirm();
  for (let index = 0; index < 4; index += 1) machine.advance();
  const state = machine.snapshot();
  assert.equal(state.result.status, "completed");
  assert.equal(state.result.elapsedMs, 5800);
  assert.equal(state.events.at(-1).type, "task.completed");
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `node --test tests/test_agent_demo.js && .venv/bin/python -m unittest tests.test_agent_demo_ui -v`

Expected: FAIL on result timing and compact-render helper contracts.

- [ ] **Step 3: Implement contextual rendering**

Update the controller to:

- Pass command source into the machine.
- Retain only the latest two `.agent-message` elements.
- Set `data-phase` on `.agent-workspace-panel`.
- Render task ID/source, target evidence, progress percentage, active-step detail, and completion result.
- Toggle `hidden` for action groups by phase: planned confirmation, running target-loss/cancel, paused recovery, and completed/stopped restart.
- Avoid appending four separate assistant chat messages during execution; update the current-step surface instead and append only pause, recovery, stop, and completion messages.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `node --test tests/test_agent_demo.js && .venv/bin/python -m unittest tests.test_agent_demo_ui -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/o6-camera-teleop/tests/test_agent_demo.js apps/o6-camera-teleop/tests/test_agent_demo_ui.py apps/o6-camera-teleop/web/agent_demo.js
git commit -m "feat: streamline agent demo interaction states"
```

### Task 4: Apply the calmer responsive visual system

**Files:**
- Modify: `apps/o6-camera-teleop/tests/test_agent_demo_ui.py`
- Modify: `apps/o6-camera-teleop/web/styles.css`

- [ ] **Step 1: Write failing layout tests**

Assert the CSS contains the 32/68 split, compact transcript, evidence summary grid, contextual hidden-state rules, focused current-step surface, and mobile Agent-first stacking:

```python
def test_agent_layout_uses_task_first_density(self):
    self.assertIn("minmax(250px, .48fr) minmax(520px, 1fr)", self.css)
    self.assertIn(".agent-evidence-summary", self.css)
    self.assertIn(".agent-current-step", self.css)
    self.assertIn('.agent-workspace-panel[data-phase="completed"]', self.css)
    self.assertIn('grid-template-areas: "workspace" "perception"', self.css)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m unittest tests.test_agent_demo_ui -v`

Expected: FAIL because the new density tokens and components are absent.

- [ ] **Step 3: Implement desktop and mobile styling**

- Set the desktop grid to `minmax(250px, .48fr) minmax(520px, 1fr)`.
- Reduce panel padding and shadow strength, keep radii at 8px or below, and use whitespace between workflow bands rather than nested cards.
- Make evidence a three-column compact strip.
- Limit transcript height and visually de-emphasize older context.
- Render plan steps as a slim rail; put detail in the single current-step surface.
- Keep only the phase-appropriate action row visible and style one clear primary action.
- At 960px stack workspace before perception; at 620px use one-column evidence, a vertical step list, 44px controls, and sufficient bottom padding for fixed controls.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `.venv/bin/python -m unittest tests.test_agent_demo_ui -v`

Expected: all Agent UI tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/o6-camera-teleop/tests/test_agent_demo_ui.py apps/o6-camera-teleop/web/styles.css
git commit -m "style: reduce agent workspace visual density"
```

### Task 5: Full verification and delivery

**Files:**
- Modify only if verification exposes a regression.

- [ ] **Step 1: Run complete automated verification**

```bash
cd apps/o6-camera-teleop
node --test tests/test_agent_demo.js
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
cd ../..
git diff --check
```

Expected: 0 failures and no whitespace errors.

- [ ] **Step 2: Verify the desktop workflow in the in-app browser**

Reload `http://127.0.0.1:8876/`, enter Agent, and verify idle, clarification, planned, running, paused/recovered, and completed states. Confirm only contextual actions are visible and task telemetry changes deterministically.

- [ ] **Step 3: Verify responsive behavior**

At 390x844, confirm Agent-first stacking, no horizontal overflow, no clipped labels, and no overlap between composer content and fixed mobile safety controls.

- [ ] **Step 4: Capture and inspect screenshots**

Capture desktop and mobile screenshots and inspect them with `view_image` against the user-provided reference screenshot. Record at least five fidelity points: layout ratio, transcript density, plan focus, action hierarchy, evidence treatment, and mobile stacking.

- [ ] **Step 5: Push the completed branch**

```bash
git status --short --branch
git push hk codex/agent-improvements-20260805
```

Expected: local and remote branch tips match.
