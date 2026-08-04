# reCamera Eye-in-Hand MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream the wrist-mounted reCamera into the existing Mac web console, show central object detections, and manually drive the connected O6 left hand through safe-open, conservative-grasp, and emergency-stop controls.

**Architecture:** reCamera runs the official Node-RED `Camera -> Stream` flow and exposes H.264 RTSP. The existing single Mac runtime owns RTSP decoding, object inference, web visualization, command filtering, and the only O6 controller; no camera event automatically moves the hand in this milestone.

**Tech Stack:** Python 3, OpenCV/FFmpeg, MediaPipe Tasks, Flask, vanilla HTML/CSS/JavaScript, pytest/unittest, Seeed reCamera Node-RED, LinkerHand O6 MacCAN adapter.

---

## File Structure

- Create `apps/o6-camera-teleop/vision/rtsp_source.py`: one reconnecting RTSP capture and its transport status.
- Modify `apps/o6-camera-teleop/vision/frame_source.py`: route the new `recamera` source without disturbing Mac camera or iPhone LiDAR routing.
- Modify `apps/o6-camera-teleop/control/console_mode.py`: add the reCamera source enum and object-mode constraint.
- Modify `apps/o6-camera-teleop/control/grasp_state.py`: add an explicit manual transition into the existing filtered closing state.
- Modify `apps/o6-camera-teleop/web_console.py`: expose source/action/status contracts, central target highlighting, stream health, and manual grasp.
- Modify `apps/o6-camera-teleop/web/index.html`: add reCamera source and conservative-grasp controls.
- Modify `apps/o6-camera-teleop/web/app.js`: render reCamera status and enforce button states.
- Modify `apps/o6-camera-teleop/web/styles.css`: fit a stable three-way source selector.
- Modify `apps/o6-camera-teleop/config.yaml`: hold RTSP connection settings.
- Create `apps/o6-camera-teleop/tests/test_recamera_source.py`: unit tests for reconnect, routing, and stream status.
- Create `apps/o6-camera-teleop/tests/test_web_recamera_api.py`: API, state-machine, selection, and static UI contract tests.
- Modify `apps/o6-camera-teleop/README.md`: exact reCamera setup, dry-run, real-mode, and failure recovery instructions.

### Task 1: Reconnecting RTSP Frame Source

**Files:**
- Create: `apps/o6-camera-teleop/vision/rtsp_source.py`
- Modify: `apps/o6-camera-teleop/vision/frame_source.py:13-53`
- Modify: `apps/o6-camera-teleop/control/console_mode.py:12-40`
- Create: `apps/o6-camera-teleop/tests/test_recamera_source.py`

- [ ] **Step 1: Write failing RTSP and routing tests**

Create `tests/test_recamera_source.py` with deterministic fake captures:

```python
import unittest

import numpy as np

from control.console_mode import ConsoleMode, ConsoleModeState, VisionSource
from vision.frame_source import FrameSourceManager
from vision.rtsp_source import RtspFrameSource


class FakeCapture:
    def __init__(self, reads, opened=True):
        self.reads = list(reads)
        self.opened = opened
        self.released = False

    def isOpened(self):
        return self.opened

    def read(self):
        return self.reads.pop(0) if self.reads else (False, None)

    def release(self):
        self.released = True


class RtspSourceTest(unittest.TestCase):
    def test_success_reports_connection_fps_and_age(self):
        frame = np.zeros((2, 3, 3), dtype=np.uint8)
        source = RtspFrameSource(
            "rtsp://camera/live",
            retry_seconds=1.0,
            capture_factory=lambda _url: FakeCapture([(True, frame), (True, frame)]),
        )
        self.assertIs(source.read(10.0), frame)
        self.assertIs(source.read(10.1), frame)
        status = source.status(10.15)
        self.assertTrue(status.connected)
        self.assertGreater(status.fps, 0)
        self.assertAlmostEqual(status.frame_age_ms, 50.0)

    def test_failure_releases_and_retries_after_deadline(self):
        first = FakeCapture([(False, None)])
        frame = np.zeros((2, 3, 3), dtype=np.uint8)
        second = FakeCapture([(True, frame)])
        captures = iter([first, second])
        opened = []

        def factory(url):
            opened.append(url)
            return next(captures)

        source = RtspFrameSource("rtsp://camera/live", 1.0, factory)
        self.assertIsNone(source.read(1.0))
        self.assertTrue(first.released)
        self.assertIsNone(source.read(1.5))
        self.assertIsNotNone(source.read(2.0))
        self.assertEqual(opened, ["rtsp://camera/live", "rtsp://camera/live"])

    def test_manager_routes_recamera_without_opening_mac_camera(self):
        frame = np.zeros((2, 3, 3), dtype=np.uint8)
        rtsp = RtspFrameSource(
            "rtsp://camera/live", 1.0, lambda _url: FakeCapture([(True, frame)])
        )
        opened = []
        manager = FrameSourceManager(
            0, receiver=None, capture_factory=lambda index: opened.append(index), rtsp_source=rtsp
        )
        sample = manager.read(VisionSource.RECAMERA, now=1.0)
        self.assertEqual(sample.source, VisionSource.RECAMERA)
        self.assertIs(sample.bgr, frame)
        self.assertEqual(opened, [])

    def test_recamera_forces_object_mode_and_pauses_follow(self):
        state = ConsoleModeState(mode=ConsoleMode.HAND_FOLLOW, follow_enabled=True)
        state.switch_source(VisionSource.RECAMERA)
        self.assertEqual(state.mode, ConsoleMode.OBJECT_GRASP)
        self.assertFalse(state.follow_enabled)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify the new types are missing**

Run:

```bash
cd apps/o6-camera-teleop
.venv/bin/python -m unittest tests.test_recamera_source -v
```

Expected: FAIL because `vision.rtsp_source` and `VisionSource.RECAMERA` do not exist.

- [ ] **Step 3: Implement the minimal reconnecting capture**

Create `vision/rtsp_source.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import cv2


@dataclass(frozen=True)
class RtspStatus:
    connected: bool
    fps: float
    frame_age_ms: float | None
    last_error: str | None


def _open_capture(url: str):
    params = [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000,
        cv2.CAP_PROP_READ_TIMEOUT_MSEC, 1000,
    ]
    return cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)


class RtspFrameSource:
    def __init__(
        self,
        url: str,
        retry_seconds: float,
        capture_factory: Callable[[str], object] = _open_capture,
    ) -> None:
        if not isinstance(url, str) or not url.startswith(("rtsp://", "rtsps://")):
            raise ValueError("reCamera RTSP URL must start with rtsp:// or rtsps://")
        if retry_seconds <= 0:
            raise ValueError("retry_seconds must be positive")
        self.url = url
        self.retry_seconds = float(retry_seconds)
        self.capture_factory = capture_factory
        self.capture = None
        self.next_retry_at = 0.0
        self.connected = False
        self.fps = 0.0
        self.last_frame_at: float | None = None
        self.last_error: str | None = None

    def read(self, now: float):
        if self.capture is None:
            if now < self.next_retry_at:
                return None
            self.capture = self.capture_factory(self.url)
            if hasattr(self.capture, "isOpened") and not self.capture.isOpened():
                return self._fail(now, "RTSP open failed")
        ok, frame = self.capture.read()
        if not ok or frame is None:
            return self._fail(now, "RTSP read failed")
        if self.last_frame_at is not None:
            instant = 1.0 / max(now - self.last_frame_at, 1e-6)
            self.fps = instant if self.fps == 0 else 0.9 * self.fps + 0.1 * instant
        self.last_frame_at = now
        self.connected = True
        self.last_error = None
        return frame

    def status(self, now: float) -> RtspStatus:
        age = None if self.last_frame_at is None else max(0.0, now - self.last_frame_at) * 1000
        return RtspStatus(self.connected, self.fps, age, self.last_error)

    def close(self) -> None:
        capture, self.capture = self.capture, None
        if capture is not None:
            capture.release()
        self.connected = False

    def _fail(self, now: float, message: str):
        self.close()
        self.next_retry_at = now + self.retry_seconds
        self.last_error = message
        return None
```

Add the source enum and object-mode constraint:

```python
class VisionSource(str, Enum):
    MAC_CAMERA = "mac-camera"
    IPHONE_LIDAR = "iphone-lidar"
    RECAMERA = "recamera"


def switch_source(self, source: VisionSource) -> None:
    self.vision_source = source
    if source in (VisionSource.IPHONE_LIDAR, VisionSource.RECAMERA):
        self.mode = ConsoleMode.OBJECT_GRASP
    self.pause_follow()
```

Extend `FrameSourceManager` with an injected RTSP source and keep all ownership in one place:

```python
def __init__(
    self,
    camera_index: int,
    receiver,
    capture_factory: Callable[[int], object] = cv2.VideoCapture,
    rtsp_source=None,
) -> None:
    self.camera_index = int(camera_index)
    self.receiver = receiver
    self.capture_factory = capture_factory
    self.rtsp_source = rtsp_source
    self.capture = None

def read(self, source: VisionSource, now: float) -> FrameSample | None:
    if source == VisionSource.IPHONE_LIDAR:
        frame = self.receiver.latest(now)
        if frame is None:
            return None
        return FrameSample(source, frame.rgb_bgr.copy(), frame)
    if source == VisionSource.RECAMERA:
        if self.rtsp_source is None:
            return None
        bgr = self.rtsp_source.read(now)
        return None if bgr is None else FrameSample(source, bgr, None)
    if source != VisionSource.MAC_CAMERA:
        raise ValueError(f"unsupported vision source: {source!r}")
    if self.capture is None:
        self.capture = self.capture_factory(self.camera_index)
    ok, bgr = self.capture.read()
    return FrameSample(source, bgr, None) if ok and bgr is not None else None

def close(self) -> None:
    capture, self.capture = self.capture, None
    if capture is not None:
        capture.release()
    if self.rtsp_source is not None:
        self.rtsp_source.close()
```

- [ ] **Step 4: Run source tests and the existing frame-source tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_recamera_source tests.test_frame_source -v
```

Expected: all tests PASS; existing Mac-camera and iPhone tests remain green.

- [ ] **Step 5: Commit the source layer**

```bash
git add apps/o6-camera-teleop/control/console_mode.py \
  apps/o6-camera-teleop/vision/frame_source.py \
  apps/o6-camera-teleop/vision/rtsp_source.py \
  apps/o6-camera-teleop/tests/test_recamera_source.py
git commit -m "feat: add reconnecting reCamera RTSP source"
```

### Task 2: Runtime Source, Central Target, And Manual Grasp

**Files:**
- Modify: `apps/o6-camera-teleop/control/grasp_state.py:50-95`
- Modify: `apps/o6-camera-teleop/web_console.py:27-41,277-352,461-673,675-1148`
- Create: `apps/o6-camera-teleop/tests/test_web_recamera_api.py`

- [ ] **Step 1: Write failing runtime contract tests**

Create `tests/test_web_recamera_api.py`:

```python
from pathlib import Path
import unittest

import yaml

from control.console_mode import ConsoleModeState, VisionSource
from control.grasp_state import GraspState, GraspStateMachine
from web_console import ALLOWED_ACTIONS, WebConsoleRuntime, _closest_target_to_center, create_app
from vision.object_detector import ObjectDetection


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


class ReCameraWebTest(unittest.TestCase):
    def test_actions_and_status_contract(self):
        self.assertIn("source-recamera", ALLOWED_ACTIONS)
        self.assertIn("manual-grasp", ALLOWED_ACTIONS)
        client = create_app(FakeRuntime()).test_client()
        for action in ("source-recamera", "manual-grasp"):
            self.assertEqual(client.post("/api/action", json={"action": action}).status_code, 202)

        config_path = Path(__file__).parents[1] / "config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        status = WebConsoleRuntime(config, 0, True, config_path).status_snapshot()
        self.assertTrue({
            "recamera_connected", "recamera_fps", "recamera_frame_age_ms",
            "recamera_last_error",
        } <= status.keys())

    def test_center_target_prefers_smallest_center_distance(self):
        selected = _closest_target_to_center([
            detection("edge", 0, 0),
            detection("center", 40, 40),
        ])
        self.assertEqual(selected.label, "center")

    def test_manual_close_uses_explicit_state_transition(self):
        machine = GraspStateMachine((0.2, 0.2, 0.8, 0.8), 0.01, 0.5, 8, 0.1)
        self.assertTrue(machine.start_manual_close())
        self.assertEqual(machine.state, GraspState.CLOSING)
        self.assertFalse(machine.start_manual_close())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify missing actions/status/helper**

Run:

```bash
.venv/bin/python -m unittest tests.test_web_recamera_api -v
```

Expected: FAIL for missing `source-recamera`, `manual-grasp`, stream status fields, center helper, and manual transition.

- [ ] **Step 3: Add the explicit state transition and runtime contracts**

Add to `GraspStateMachine`:

```python
def start_manual_close(self) -> bool:
    if self.state != GraspState.DISARMED:
        return False
    self.state = GraspState.CLOSING
    self.stable_count = 0
    self.target = None
    return True
```

Add a center helper that uses normalized detection centers:

```python
def _closest_target_to_center(detections: list[ObjectDetection]) -> ObjectDetection | None:
    return min(
        detections,
        key=lambda item: (item.center_normalized[0] - 0.5) ** 2
        + (item.center_normalized[1] - 0.5) ** 2,
        default=None,
    )
```

Extend `ALLOWED_ACTIONS`, initial status, and source mapping. Construct `FrameSourceManager` with `RtspFrameSource(config["recamera"]["rtsp_url"], retry_ms / 1000)`. On each loop, copy `RtspStatus` into `recamera_connected`, `recamera_fps`, `recamera_frame_age_ms`, and `recamera_last_error`.

For `VisionSource.RECAMERA`, skip foreground/background differencing, highlight `_closest_target_to_center(detections)`, and never call the automatic `machine.update()` transition. Failed reads must set `camera_ok=False`, clear the target fields, and report a reCamera-specific event without producing a pose.

- [ ] **Step 4: Add guarded manual grasp to the existing filtered closing path**

Handle `manual-grasp` inside `_apply_action()`:

```python
elif action == "manual-grasp":
    if mode_state.mode != ConsoleMode.OBJECT_GRASP:
        self._set_status(last_event="请先切换到物品模式")
    elif mode_state.vision_source != VisionSource.RECAMERA:
        self._set_status(last_event="请先切换到 reCamera 腕部视角")
    elif controller.emergency_stopped:
        self._set_status(last_event="急停已锁定，不能执行保守握合")
    elif controller.backend == "dry-run-fallback":
        self._set_status(last_event="真机连接失败，拒绝伪装执行握合")
    elif machine.start_manual_close():
        self._set_status(last_event="已确认保守握合，正在按限速闭合")
    else:
        self._set_status(last_event="当前状态不能握合，请先安全张开")
```

Do not send a pose from the action handler. The existing `GraspState.CLOSING` loop must continue to call `grasp_filter.apply(grasp_pose)` at `command_hz`, then mark `HOLDING`. Dry-run therefore prints the same filtered pose sequence while real mode uses the genuine backend. The existing `open` and `stop` paths remain authoritative.

- [ ] **Step 5: Run targeted and regression tests**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_web_recamera_api \
  tests.test_web_depth_api \
  tests.test_depth_grasp \
  tests.test_frame_source -v
```

Expected: all tests PASS, including existing iPhone depth safety behavior.

- [ ] **Step 6: Commit runtime behavior**

```bash
git add apps/o6-camera-teleop/control/grasp_state.py \
  apps/o6-camera-teleop/web_console.py \
  apps/o6-camera-teleop/tests/test_web_recamera_api.py
git commit -m "feat: add reCamera preview and manual O6 grasp"
```

### Task 3: Web Controls, Configuration, And Documentation

**Files:**
- Modify: `apps/o6-camera-teleop/web/index.html:116-137,151-171`
- Modify: `apps/o6-camera-teleop/web/app.js:80-300`
- Modify: `apps/o6-camera-teleop/web/styles.css:347-420`
- Modify: `apps/o6-camera-teleop/config.yaml:19-26`
- Modify: `apps/o6-camera-teleop/tests/test_web_recamera_api.py`
- Modify: `apps/o6-camera-teleop/README.md`

- [ ] **Step 1: Add failing static UI contract assertions**

Append to `test_web_recamera_api.py`:

```python
def test_static_console_exposes_recamera_controls(self):
    web = Path(__file__).parents[1] / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    script = (web / "app.js").read_text(encoding="utf-8")
    self.assertIn('data-action="source-recamera"', html)
    self.assertIn('data-action="manual-grasp"', html)
    self.assertIn('id="recameraDiagnostics"', html)
    self.assertIn('status.vision_source === "recamera"', script)
    self.assertIn("recamera_frame_age_ms", script)
```

Run:

```bash
.venv/bin/python -m unittest tests.test_web_recamera_api.ReCameraWebTest.test_static_console_exposes_recamera_controls -v
```

Expected: FAIL because the controls do not exist.

- [ ] **Step 2: Add the reCamera source and manual action controls**

Add a third source button:

```html
<button id="recameraSourceButton" class="source-button"
        data-action="source-recamera" type="button">reCamera</button>
```

Wrap the existing automatic arm/disarm buttons in `id="automaticGraspActions"`, and add a reCamera-only block:

```html
<div id="recameraActions" class="action-grid" hidden>
  <button id="manualGraspButton" class="button primary"
          data-action="manual-grasp" type="button">保守握合</button>
</div>
```

Keep `Safe Open` and `Emergency Stop` as common controls. Add diagnostics for RTSP state, FPS, and latest-frame age. Change `.source-switch` to three stable equal-width tracks and allow labels to wrap without resizing the control rail.

- [ ] **Step 3: Render source-specific status and safety states**

In `updateStatus()` define:

```javascript
const recameraSource = status.vision_source === "recamera";
const lidarSource = status.vision_source === "iphone-lidar";
const macSource = !recameraSource && !lidarSource;
const recameraConnected = Boolean(status.recamera_connected);
const recameraAge = finiteNumber(status.recamera_frame_age_ms);
```

Use these flags to select exactly one source button, show `reCamera 腕部视角`, hide automatic arm/disarm in reCamera mode, show the manual grasp button, and display `RTSP 已连接/已断开`, FPS, and age. Disable conservative grasp when stopped, not ready, not in reCamera mode, `camera_ok` is false, state is not `DISARMED`, or backend is `dry-run-fallback`. Keep it enabled in intentional dry-run so the filtered pose sequence can be observed without hardware.

- [ ] **Step 4: Add explicit configuration and operating instructions**

Add to `config.yaml`:

```yaml
recamera:
  enabled: true
  rtsp_url: rtsp://admin:admin@192.168.254.153:554/live
  reconnect_interval_ms: 1000
  stale_timeout_ms: 1500
```

Update the README with:

1. Open `http://192.168.254.153/#/workspace`.
2. Add official `Camera` and `Stream` nodes.
3. Configure the Stream node as RTSP, port `554`, session `live`, and credentials matching `config.yaml`.
4. Deploy and verify port `554` before starting tailhand.
5. Start `./run_web.sh --dry-run`, select `物品抓取 -> reCamera`, and verify live video and boxes.
6. Use `保守握合` only in dry-run first; use `安全张开` to reset.
7. Start `./run_web.sh --real` only after clearing the workspace and confirming `backend=mac-pcan-o6`, `connected=true`, and `左手 / 0x28`.

- [ ] **Step 5: Run unit tests and browser smoke test**

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
./run_web.sh --dry-run
```

Open `http://127.0.0.1:8765` at desktop and mobile widths. Verify all three source buttons fit, the reCamera diagnostics do not overlap controls, and Open/Grasp/Stop buttons retain stable dimensions. Stop with `Ctrl-C`.

- [ ] **Step 6: Commit UI, configuration, and docs**

```bash
git add apps/o6-camera-teleop/web/index.html \
  apps/o6-camera-teleop/web/app.js \
  apps/o6-camera-teleop/web/styles.css \
  apps/o6-camera-teleop/config.yaml \
  apps/o6-camera-teleop/tests/test_web_recamera_api.py \
  apps/o6-camera-teleop/README.md
git commit -m "feat: expose reCamera MVP in O6 console"
```

### Task 4: Configure reCamera And Verify The Real Chain

**Files:**
- Verify only: reCamera Node-RED workspace at `http://192.168.254.153/#/workspace`
- Verify only: `apps/o6-camera-teleop/config.yaml`
- Verify only: `apps/o6-camera-teleop/README.md`

- [ ] **Step 1: Deploy the official reCamera stream flow**

In the reCamera workspace, deploy `Camera -> Stream` using RTSP port `554`, session `live`, and the credentials in local configuration. Do not add CAN or robot-control nodes.

Verify:

```bash
nc -G 2 -zv 192.168.254.153 554
```

Expected: connection to TCP port `554` succeeds.

- [ ] **Step 2: Verify frames independently from the O6 runner**

Run:

```bash
cd apps/o6-camera-teleop
.venv/bin/python - <<'PY'
import cv2
url = "rtsp://admin:admin@192.168.254.153:554/live"
capture = cv2.VideoCapture(url)
ok, frame = capture.read()
capture.release()
print({"ok": ok, "shape": None if frame is None else frame.shape})
raise SystemExit(0 if ok and frame is not None else 1)
PY
```

Expected: `ok` is `True` and `shape` contains nonzero height, width, and 3 channels.

- [ ] **Step 3: Verify the complete chain in dry-run**

Start:

```bash
./run_web.sh --dry-run
```

Use the web console to select `物品抓取 -> reCamera`. Verify video, central detections, RTSP health, and the following action sequence:

```text
Safe Open -> Conservative Grasp -> Safe Open -> Emergency Stop
```

Expected: terminal prints filtered six-value poses; no CAN device is opened; after emergency stop, another grasp request is rejected.

- [ ] **Step 4: Run the automated regression suite**

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests PASS.

- [ ] **Step 5: Verify the connected O6 left hand with bounded motion**

Secure the wrist and camera, clear the finger workspace, keep physical power disconnection in reach, then start:

```bash
./run_web.sh --real
```

Do not press grasp until status simultaneously reports:

```text
backend = mac-pcan-o6
hardware = connected
device = left / 0x28
RTSP = connected
```

Press `Safe Open`, then `Conservative Grasp`, observe the limited filtered transition to configured pose `[110, 35, 55, 55, 55, 55]`, and press `Safe Open` to release. If state feedback, temperatures, unexpected motion, or stream status are abnormal, press emergency stop and physically disconnect power.

- [ ] **Step 6: Record verification without committing generated artifacts**

Run:

```bash
git status --short
git log -4 --oneline
```

Expected: only known user-owned Xcode and `.superpowers` files remain uncommitted; the three implementation commits and design/plan commits are present. Do not commit screenshots, local credentials, Xcode user data, or visualization session files.
