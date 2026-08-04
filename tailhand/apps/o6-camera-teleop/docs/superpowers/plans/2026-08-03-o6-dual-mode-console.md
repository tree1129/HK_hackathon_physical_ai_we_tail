# O6 Dual-Mode Web Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add mutually exclusive hand-follow and object-grasp modes to the existing local O6 web console, with explicit follow enablement and safe mode transitions.

**Architecture:** Keep one camera thread and one `O6Controller`. Add a small pure state object for mode/follow/lost-hand transitions, then let `WebConsoleRuntime` route frames and queued actions to either the existing grasp state machine or the existing `HandMapper` pipeline. The browser renders backend state and never writes CAN directly.

**Tech Stack:** Python 3.9, Flask, OpenCV, MediaPipe, NumPy, vanilla HTML/CSS/JavaScript, `unittest`.

**Repository note:** This project directory has no `.git` metadata, so commit steps are replaced by explicit test and file checks. Do not initialize a repository as part of this feature.

---

### Task 1: Pure dual-mode safety state

**Files:**
- Create: `control/console_mode.py`
- Modify: `tests/test_mapper.py`

- [ ] **Step 1: Write the failing state-transition test**

Add imports and a test proving default object mode, explicit hand enablement, lost-hand timeout, reacquisition, pause, and mode reset:

```python
from control.console_mode import ConsoleMode, ConsoleModeState, TrackingState

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
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_mapper.MapperAndFilterTest.test_console_modes_are_mutually_exclusive_and_follow_is_explicit -v
```

Expected: import failure for missing `control.console_mode`.

- [ ] **Step 3: Implement the minimal pure state object**

Create `control/console_mode.py` with string enums and methods:

```python
from dataclasses import dataclass
from enum import Enum

class ConsoleMode(str, Enum):
    HAND_FOLLOW = "hand-follow"
    OBJECT_GRASP = "object-grasp"

class TrackingState(str, Enum):
    WAITING_HAND = "WAITING_HAND"
    TRACKING = "TRACKING"
    HOLDING_LAST = "HOLDING_LAST"
    PAUSED_LOST = "PAUSED_LOST"

@dataclass
class ConsoleModeState:
    mode: ConsoleMode = ConsoleMode.OBJECT_GRASP
    follow_enabled: bool = False
    tracking_state: TrackingState = TrackingState.WAITING_HAND
    last_hand_time: float | None = None

    def switch(self, mode: ConsoleMode) -> None:
        self.mode = mode
        self.follow_enabled = False
        self.tracking_state = TrackingState.WAITING_HAND
        self.last_hand_time = None

    def enable_follow(self, emergency_stopped: bool) -> bool:
        if self.mode != ConsoleMode.HAND_FOLLOW or emergency_stopped:
            return False
        self.follow_enabled = True
        self.tracking_state = TrackingState.WAITING_HAND
        self.last_hand_time = None
        return True

    def pause_follow(self) -> None:
        self.follow_enabled = False
        self.tracking_state = TrackingState.WAITING_HAND
        self.last_hand_time = None
```

Complete `observe_hand` and `can_send_hand` so the test's exact state transitions hold. Treat the timeout boundary as paused when `now - last_hand_time > lost_timeout`.

- [ ] **Step 4: Run the focused and full tests**

```bash
.venv/bin/python -m unittest tests.test_mapper.MapperAndFilterTest.test_console_modes_are_mutually_exclusive_and_follow_is_explicit -v
.venv/bin/python -m unittest tests/test_mapper.py -v
```

Expected: all tests pass.

### Task 2: Expand the web action contract

**Files:**
- Modify: `web_console.py`
- Modify: `tests/test_mapper.py`

- [ ] **Step 1: Extend the failing HTTP contract test**

Update `FakeRuntime.enqueue_action` to accept these actions and assert all four new actions return HTTP 202:

```python
allowed = {
    "arm", "disarm", "open", "stop",
    "mode-hand", "mode-object", "follow-enable", "follow-pause",
}
for action in ("mode-hand", "mode-object", "follow-enable", "follow-pause"):
    response = client.post("/api/action", json={"action": action})
    self.assertEqual(response.status_code, 202)
```

- [ ] **Step 2: Run the focused test and verify RED**

```bash
.venv/bin/python -m unittest tests.test_mapper.MapperAndFilterTest.test_web_console_status_and_actions -v
```

Expected: new actions return HTTP 400 because `ALLOWED_ACTIONS` does not include them.

- [ ] **Step 3: Extend `ALLOWED_ACTIONS` only**

```python
ALLOWED_ACTIONS = {
    "arm", "disarm", "open", "stop",
    "mode-hand", "mode-object", "follow-enable", "follow-pause",
}
```

- [ ] **Step 4: Run the focused test and verify GREEN**

```bash
.venv/bin/python -m unittest tests.test_mapper.MapperAndFilterTest.test_web_console_status_and_actions -v
```

Expected: pass, while unknown actions remain HTTP 400.

### Task 3: Route the camera loop to hand follow or object grasp

**Files:**
- Modify: `web_console.py`
- Use existing: `control/hand_mapper.py`
- Use existing: `control/filters.py`

- [ ] **Step 1: Add imports and initial status**

Import `HandMapper`, `CHANNEL_ORDER`, `ConsoleMode`, `ConsoleModeState`, and `TrackingState`. Initialize status with:

```python
"mode": ConsoleMode.OBJECT_GRASP.value,
"follow_enabled": False,
"tracking_state": TrackingState.WAITING_HAND.value,
"handedness": None,
"hand_score": None,
```

- [ ] **Step 2: Initialize independent hand and grasp pipelines**

Create one `HandMapper` using `o6.channels` and `calibration`. Keep separate `CommandFilter` instances for hand follow and grasp so switching cannot leak EMA state. Reset both to `safe_open`. Derive `lost_timeout` from `lost_hand_timeout_ms`.

- [ ] **Step 3: Implement serialized mode actions**

Extend `_apply_action` with `ConsoleModeState` and both filters. For `mode-hand` and `mode-object`:

1. call `controller.send_safe_open(safe_open)`;
2. reset both filters;
3. call `machine.reset_after_open()` and `foreground.clear()`;
4. call `mode_state.switch(...)`;
5. return a safe-open pose.

For `follow-enable`, call `mode_state.enable_follow(controller.emergency_stopped)` and reset the hand filter to `safe_open` on success. For `follow-pause`, stop hand output without changing the last pose. Reject `arm/disarm` outside object mode and follow actions outside hand mode with a clear `last_event`. `open` must disable follow and disarm grasp.

- [ ] **Step 4: Process hand landmarks once per frame**

Call `hand_tracker.process(frame, timestamp_ms)` once on every successful frame. In hand mode, compute:

```python
mapped_pose, raw_sample = hand_mapper.map_landmarks(hand_detection.geometry_landmarks)
normalized = hand_mapper.apply_calibration(raw_sample)
```

When follow is disabled, expose `mapped_pose` as preview but do not increment `commands`. When enabled, pass it through the hand filter and send only at `command_hz` while `mode_state.can_send_hand(...)` is true. On command exception, trigger emergency stop.

- [ ] **Step 5: Keep object processing isolated**

Only call EfficientDet, background detection, target stability updates, and grasp closure when `mode_state.mode == OBJECT_GRASP`. Keep the existing hand-in-zone emergency behavior. Clear object detections and targets on hand mode entry.

- [ ] **Step 6: Make frame annotation mode-aware**

In object mode draw the grasp zone, detection boxes, target, and hand skeleton. In hand mode draw only the hand skeleton so users can verify tracking without seeing an irrelevant grasp zone.

- [ ] **Step 7: Publish complete status each frame**

Include mode, follow enablement, tracking state, handedness, score, normalized values, correct current state label, pose preview/command, command count, object fields, backend, and emergency state. Object mode uses the grasp machine state; hand mode uses tracking state.

- [ ] **Step 8: Run Python verification**

```bash
.venv/bin/python -m py_compile web_console.py control/*.py
.venv/bin/python -m unittest tests/test_mapper.py -v
```

Expected: compile exit 0 and all tests pass.

### Task 4: Add the two-mode browser controls

**Files:**
- Modify: `web/index.html`
- Modify: `web/styles.css`
- Modify: `web/app.js`

- [ ] **Step 1: Add the segmented mode control**

Above the action grid add a stable two-button group:

```html
<div class="mode-switch" role="group" aria-label="控制模式">
  <button id="handModeButton" data-action="mode-hand" type="button">手势跟随</button>
  <button id="objectModeButton" data-action="mode-object" type="button">物品抓取</button>
</div>
```

- [ ] **Step 2: Split mode-specific and common actions**

Add `#handActions` with `follow-enable` and `follow-pause`, retain `#objectActions` with arm/disarm, and keep safe-open/emergency in `#commonActions`. Use the HTML `hidden` attribute to expose only the current mode group.

- [ ] **Step 3: Style a compact segmented control**

Use a 36 px fixed-height two-column group, 5 px maximum radius, clear selected state, keyboard focus, and no layout shift. Add `[hidden] { display: none !important; }`. Keep existing responsive breakpoints and button heights.

- [ ] **Step 4: Render mode-specific status in JavaScript**

Update `updateStatus` so it:

- marks the selected mode button;
- toggles hand/object action groups;
- enables follow only in hand mode and when not emergency-stopped;
- enables arm only in object mode and `DISARMED`;
- shows handedness/score and tracking state in hand mode;
- shows target/stability in object mode;
- updates the recognition-strip label and progress without changing its dimensions.

- [ ] **Step 5: Run static checks**

```bash
node --check web/app.js
rg -n "mode-hand|mode-object|follow-enable|follow-pause" web/index.html web/app.js web_console.py
```

Expected: JavaScript exit 0 and all actions appear in HTML, JavaScript, and Python.

### Task 5: Document and verify end-to-end behavior

**Files:**
- Modify: `README.md`
- Verify: `web_console.py`, `web/*`, `config.yaml`

- [ ] **Step 1: Document both modes**

Update the web-console section with the mode switch, explicit follow enablement, lost-hand pause, object arming, safe mode switch, and the rule that only one process may own camera/CAN.

- [ ] **Step 2: Stop the existing real server before testing**

Send Ctrl-C to the current `web_console.py --real` process and verify port 8765 is free. Do not use a broad process kill.

- [ ] **Step 3: Start dry-run and verify hand mode**

```bash
./run_web.sh --camera 0 --dry-run
```

In the browser verify default object mode, switch to hand mode, confirm no commands before enable, enable follow, show a hand, verify six values and command count change, remove the hand for more than 0.5 seconds, and verify output pauses.

- [ ] **Step 4: Verify object-mode reset**

Switch back to object mode and verify safe-open pose, `DISARMED`, zero stability, hidden hand-follow controls, and visible arm/disarm controls. Do not trigger an automatic grasp during browser layout testing.

- [ ] **Step 5: Verify desktop and mobile rendering**

Use the real browser at default viewport and `390x844`. Confirm no horizontal overflow, all buttons remain 40 px high, no text overlap, and no browser console errors. Reset the viewport afterward.

- [ ] **Step 6: Run the full automated verification**

```bash
.venv/bin/python -m unittest tests/test_mapper.py -v
.venv/bin/python -m py_compile app.py object_grasp.py web_console.py control/*.py vision/*.py
node --check web/app.js
zsh -n run_web.sh run_mac.sh
```

Expected: all tests pass and every static command exits 0.

- [ ] **Step 7: Restart the verified real server safely**

Stop dry-run, start:

```bash
./run_web.sh --camera 0 --real
```

Verify `/api/status` reports `backend=mac-pcan-o6`, `connected=true`, `dry_run=false`, default object mode, and `DISARMED`. Leave hand follow disabled and do not generate an unsolicited movement during final handoff.
