# reCamera Armed Auto-Grasp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the operator to arm reCamera object recognition and automatically close the O6 after one eligible central target remains stable for exactly eight detector updates.

**Architecture:** Keep the existing Mac-side detector, `GraspStateMachine`, filtered O6 command path, and single web-console runner. Add reCamera to the existing RGB target-observation route, reject unsafe arming states in the backend, and expose both automatic arming and manual conservative grasp controls in the reCamera UI.

**Tech Stack:** Python 3, Flask, OpenCV, existing LinkerHand adapter, vanilla JavaScript, `unittest`/`pytest`.

---

## File Map

- Modify `apps/o6-camera-teleop/web_console.py`: validate reCamera arming, route reCamera detections through the grasp state machine, and reset stability when RTSP frames disappear.
- Modify `apps/o6-camera-teleop/web/app.js`: expose automatic and manual controls together and mirror backend arming gates.
- Modify `apps/o6-camera-teleop/tests/test_web_recamera_api.py`: cover reCamera arming, eight-frame triggering, target/hand cancellation, fallback rejection, and static UI behavior.
- Modify `apps/o6-camera-teleop/README.md`: document the new armed auto-grasp flow and its RGB-only limitation.

### Task 1: Backend reCamera arming gates

**Files:**
- Modify: `apps/o6-camera-teleop/tests/test_web_recamera_api.py`
- Modify: `apps/o6-camera-teleop/web_console.py`

- [x] **Step 1: Write failing arming tests**

Add a test that builds a reCamera object-mode runtime and calls `_apply_action("arm", ...)` in three states:

```python
def test_recamera_arm_requires_stream_and_rejects_hardware_fallback(self):
    runtime, config, config_path = self.runtime()
    mode_state = ConsoleModeState()
    mode_state.switch_source(VisionSource.RECAMERA)
    machine = self.machine()

    runtime._set_status(recamera_connected=False)
    self.apply(runtime, config, mode_state, machine, FakeController(), "arm")
    self.assertEqual(machine.state, GraspState.DISARMED)
    self.assertIn("RTSP", runtime.status_snapshot()["last_event"])

    runtime._set_status(recamera_connected=True)
    self.apply(runtime, config, mode_state, machine, FakeController("dry-run-fallback"), "arm")
    self.assertEqual(machine.state, GraspState.DISARMED)
    self.assertIn("拒绝", runtime.status_snapshot()["last_event"])

    self.apply(runtime, config, mode_state, machine, FakeController("dry-run"), "arm")
    self.assertEqual(machine.state, GraspState.ARMED)
    self.assertIn("稳定 8 帧", runtime.status_snapshot()["last_event"])
```

- [x] **Step 2: Run the focused test and confirm failure**

Run:

```bash
cd apps/o6-camera-teleop
python -m pytest tests/test_web_recamera_api.py::ReCameraWebTest::test_recamera_arm_requires_stream_and_rejects_hardware_fallback -v
```

Expected: FAIL because the current backend rejects all reCamera arming.

- [x] **Step 3: Implement the arming gates**

In the `arm` action branch, preserve the existing mode, emergency-stop, LiDAR calibration, and state checks. For reCamera, require a connected RTSP status and reject `dry-run-fallback`; intentional `dry-run` remains valid. Do not capture a foreground background for reCamera.

```python
status = self.status_snapshot()
if mode_state.vision_source == VisionSource.RECAMERA and not status["recamera_connected"]:
    self._set_status(last_event="reCamera RTSP 未连接，不能布防自动抓取")
elif mode_state.vision_source == VisionSource.RECAMERA and controller.backend == "dry-run-fallback":
    self._set_status(last_event="真机连接失败，拒绝布防自动抓取")
elif machine.state == GraspState.DISARMED:
    if mode_state.vision_source == VisionSource.MAC_CAMERA and frame is not None:
        foreground.capture_background(frame)
    machine.arm()
    if mode_state.vision_source == VisionSource.RECAMERA:
        self._set_status(last_event=f"已布防 reCamera；中央目标稳定 {machine.stable_frames} 帧后自动握合")
```

- [x] **Step 4: Run the focused test**

Run the Step 2 command. Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add apps/o6-camera-teleop/web_console.py apps/o6-camera-teleop/tests/test_web_recamera_api.py
git commit -m "feat: allow safe reCamera auto-grasp arming"
```

### Task 2: Eight-frame automatic transition and cancellation

**Files:**
- Modify: `apps/o6-camera-teleop/tests/test_web_recamera_api.py`
- Modify: `apps/o6-camera-teleop/web_console.py`

- [x] **Step 1: Write failing target-routing tests**

Import a new `_update_rgb_grasp` helper and test both the exact trigger threshold and cancellation:

```python
def test_recamera_stable_target_closes_on_eighth_update(self):
    machine = self.machine()
    machine.arm()
    target = detection("cell phone", 40, 40)
    for _ in range(7):
        _update_rgb_grasp(machine, VisionSource.RECAMERA, target, hand_blocked=False)
        self.assertEqual(machine.state, GraspState.ARMED)
    _update_rgb_grasp(machine, VisionSource.RECAMERA, target, hand_blocked=False)
    self.assertEqual(machine.state, GraspState.CLOSING)

def test_recamera_target_loss_or_hand_resets_stability(self):
    machine = self.machine()
    machine.arm()
    target = detection("cell phone", 40, 40)
    for _ in range(5):
        _update_rgb_grasp(machine, VisionSource.RECAMERA, target, hand_blocked=False)
    _update_rgb_grasp(machine, VisionSource.RECAMERA, None, hand_blocked=False)
    self.assertEqual(machine.stable_count, 0)
    for _ in range(5):
        _update_rgb_grasp(machine, VisionSource.RECAMERA, target, hand_blocked=False)
    _update_rgb_grasp(machine, VisionSource.RECAMERA, target, hand_blocked=True)
    self.assertEqual(machine.stable_count, 0)
    self.assertEqual(machine.state, GraspState.ARMED)
```

- [x] **Step 2: Run both tests and confirm import failure**

Run:

```bash
cd apps/o6-camera-teleop
python -m pytest tests/test_web_recamera_api.py -k "stable_target or target_loss" -v
```

Expected: collection FAIL because `_update_rgb_grasp` does not exist.

- [x] **Step 3: Implement the shared RGB update helper**

Add beside `_observation`:

```python
def _update_rgb_grasp(
    machine: GraspStateMachine,
    source: VisionSource,
    target: ObjectDetection | None,
    hand_blocked: bool,
) -> GraspState:
    if source not in (VisionSource.MAC_CAMERA, VisionSource.RECAMERA):
        return machine.state
    return machine.update(None if hand_blocked or target is None else _observation(target))
```

Replace the Mac-only update in the detector loop with this helper. In the reCamera `sample is None` branch, call `machine.update(None)` so RTSP loss clears any pre-trigger stability count while leaving `CLOSING`/`HOLDING` unchanged.

- [x] **Step 4: Run focused and state-machine tests**

```bash
cd apps/o6-camera-teleop
python -m pytest tests/test_web_recamera_api.py tests/test_object_grasp.py -v
```

Expected: all tests PASS.

- [x] **Step 5: Commit**

```bash
git add apps/o6-camera-teleop/web_console.py apps/o6-camera-teleop/tests/test_web_recamera_api.py
git commit -m "feat: trigger reCamera grasp after stable target"
```

### Task 3: Web controls and operator documentation

**Files:**
- Modify: `apps/o6-camera-teleop/web/app.js`
- Modify: `apps/o6-camera-teleop/tests/test_web_recamera_api.py`
- Modify: `apps/o6-camera-teleop/README.md`

- [x] **Step 1: Add a failing static UI assertion**

Extend `test_static_console_exposes_recamera_controls`:

```python
self.assertIn('document.querySelector("#automaticGraspActions").hidden = handMode;', script)
self.assertIn("可布防自动抓取，或手动保守握合", script)
self.assertIn("showRecamera && (!recameraConnected", script)
```

- [x] **Step 2: Run the static UI test and confirm failure**

```bash
cd apps/o6-camera-teleop
python -m pytest tests/test_web_recamera_api.py::ReCameraWebTest::test_static_console_exposes_recamera_controls -v
```

Expected: FAIL because automatic controls are currently hidden in reCamera mode.

- [x] **Step 3: Update the console UI**

Keep `recameraActions` visible for the manual path and show `automaticGraspActions` in every object-grasp source:

```javascript
document.querySelector("#recameraActions").hidden = !showRecamera;
document.querySelector("#automaticGraspActions").hidden = handMode;
```

Change the reCamera `DISARMED` safety text to `可布防自动抓取，或手动保守握合`. Extend the arm-button disabled expression so reCamera requires `recameraConnected` and rejects `dry-run-fallback`, while intentional `dry-run` remains clickable.

- [x] **Step 4: Document the workflow and limitation**

Add a concise reCamera automatic-grasp section to the README with these operator steps: select object mode and reCamera, verify RTSP/O6 diagnostics, click `布防识别`, wait for `8 / 8`, observe filtered closure, and use only `安全张开` to release. State explicitly that this version uses RGB box position/size rather than physical depth or centimeters.

- [x] **Step 5: Run the UI test and full suite**

```bash
cd apps/o6-camera-teleop
python -m pytest tests/test_web_recamera_api.py -v
python -m pytest -q
```

Expected: reCamera tests and the full suite PASS.

- [x] **Step 6: Commit**

```bash
git add apps/o6-camera-teleop/web/app.js apps/o6-camera-teleop/tests/test_web_recamera_api.py apps/o6-camera-teleop/README.md
git commit -m "feat: expose armed reCamera grasp controls"
```

### Task 4: Dry-run and rendered-browser verification

**Files:**
- Verify only; no planned source edits.

- [x] **Step 1: Start the runner in dry-run mode**

```bash
cd apps/o6-camera-teleop
./run_web.sh --dry-run --port 8765
```

Expected: the server reports `dry-run`, opens `http://127.0.0.1:8765`, and connects to the configured reCamera RTSP without opening O6 hardware.

- [x] **Step 2: Verify backend API state**

```bash
curl -s http://127.0.0.1:8765/api/status
curl -s -X POST -H 'Content-Type: application/json' -d '{"action":"source-recamera"}' http://127.0.0.1:8765/api/action
curl -s -X POST -H 'Content-Type: application/json' -d '{"action":"arm"}' http://127.0.0.1:8765/api/action
```

Expected: the status reports `vision_source: recamera`, `recamera_connected: true`, `backend: dry-run`, and `state: ARMED`; no hardware connection is attempted.

- [x] **Step 3: Verify rendered UI at desktop and at narrow width when the browser surface supports viewport control**

Use the browser testing workflow to confirm that reCamera mode simultaneously shows `布防识别`, `解除布防`, `保守握合`, `安全张开`, and `紧急停止`, that the video remains visible, and that no controls overlap. Record the actual viewport; add a narrow-width pass only when the selected browser surface exposes viewport control.

- [x] **Step 4: Leave real mode safe and disarmed**

Stop dry-run, restart with:

```bash
./run_web.sh --real --port 8765
```

Expected: `backend: mac-pcan-o6`, `connected: true`, left-hand `0x28`, RTSP connected, O6 at safe-open pose, and grasp state `DISARMED`. Do not arm automatically during startup.

- [x] **Step 5: Final verification**

```bash
git status --short
git log -4 --oneline
```

Expected: only intentional changes are present and all implementation commits are visible.
