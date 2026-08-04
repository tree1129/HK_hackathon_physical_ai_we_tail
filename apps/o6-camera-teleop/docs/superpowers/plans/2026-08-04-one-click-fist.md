# O6 One-Click Fist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real one-click fist control that pauses gesture following and holds the active O6 hand in a mapped fist pose.

**Architecture:** Extend the existing `/api/action` command queue with `fist`. Compute the pose from `HandMapper` and pass it into the runtime action handler, keeping hardware movement and safety state in the existing runtime thread. Add one responsive button to the gesture action grid and reuse the existing real-control request path.

**Tech Stack:** Python 3.9, Flask, unittest, vanilla JavaScript, HTML, CSS

---

### Task 1: Lock the backend fist contract with tests

**Files:**
- Modify: `tests/test_mapper.py`
- Modify: `web_console.py`

- [ ] **Step 1: Write failing tests**

Add tests that require `fist` in `ALLOWED_ACTIONS`, verify `_fist_pose(HandMapper(CHANNELS), "right")` maps to `[20, 30, 20, 20, 20, 20]`, and call `_apply_action("fist", ...)` with a recording controller to require follow pause, one `move` call, returned pose, and `已握拳` status text.

- [ ] **Step 2: Verify the tests fail**

Run: `.venv/bin/python -m unittest tests.test_mapper.MapperAndFilterTest.test_fist_pose_uses_active_hand_mapping tests.test_mapper.MapperAndFilterTest.test_fist_action_pauses_follow_and_moves_once -v`

Expected: FAIL because `_fist_pose` and the `fist` action do not exist.

- [ ] **Step 3: Implement the minimal backend action**

In `web_console.py`, add:

```python
def _fist_pose(mapper: HandMapper, hand_type: str) -> list[int]:
    return mapper.map_normalized(
        {name: 1.0 for name in CHANNEL_ORDER},
        hand_type=hand_type,
    )
```

Add `fist` to `ALLOWED_ACTIONS`, pass the computed pose into `_apply_action`, and handle it before `open`:

```python
elif action == "fist":
    if controller.emergency_stopped:
        self._set_status(last_event="急停已锁定，无法执行一键握拳")
        return None
    mode_state.pause_follow()
    controller.move(fist_pose)
    hand_filter.reset(fist_pose)
    self._set_status(last_event="已暂停跟随并执行一键握拳")
    return fist_pose.copy()
```

- [ ] **Step 4: Verify focused backend tests pass**

Run the Step 2 command again.

Expected: PASS.

### Task 2: Add the real gesture-panel control

**Files:**
- Modify: `tests/test_mapper.py`
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/styles.css`

- [ ] **Step 1: Extend the static web test first**

Require `data-action="fist"`, visible text `一键握拳`, JavaScript action string `"fist"`, and `.gesture-action-grid` in the CSS.

- [ ] **Step 2: Verify the static test fails**

Run: `.venv/bin/python -m unittest tests.test_mapper.MapperAndFilterTest.test_web_assets_expose_tail3_shell_and_real_controls -v`

Expected: FAIL because the button and action are missing.

- [ ] **Step 3: Implement the button and responsive layout**

Add `"fist"` to `REAL_ACTIONS`. Add this third real-control button to the gesture action grid:

```html
<button id="fistButton" class="button secondary fist real-control" data-action="fist" type="button">一键握拳</button>
```

Give that grid a dedicated class and three stable tracks:

```css
.gesture-action-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
```

- [ ] **Step 4: Verify the static test and JavaScript syntax**

Run: `.venv/bin/python -m unittest tests.test_mapper.MapperAndFilterTest.test_web_assets_expose_tail3_shell_and_real_controls -v`

Run: `node --check web/app.js`

Expected: both PASS.

### Task 3: Regression and real-hardware verification

**Files:**
- Modify: none

- [ ] **Step 1: Run the complete automated suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 2: Restart the real runtime safely**

Pause following, stop the current process, then run `.venv/bin/python web_console.py --camera 1 --real`.

Expected: `backend=mac-pcan-o6`, `connected=true`, `hand_type=right`, `emergency_stopped=false`.

- [ ] **Step 3: Verify the browser layout**

Open the gesture page at `http://127.0.0.1:8765/`, confirm the three controls fit without overflow, and confirm there are no browser console errors.

- [ ] **Step 4: Verify the hardware workflow and restore safety**

POST `fist`, confirm `follow_enabled=false`, the status event says `已暂停跟随并执行一键握拳`, and the returned pose is the right-hand fist pose. Then POST `open` and confirm the pose returns to the configured safe-open values.
