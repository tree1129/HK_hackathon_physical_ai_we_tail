# O6 iPhone 17 Pro LiDAR Grasp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an iPhone 17 Pro wrist-mounted LiDAR sensor client and a Mac-hosted depth pipeline that visualizes signed object distance and safely triggers LinkerHand O6 pre-open and grasp behavior.

**Architecture:** The SwiftUI/ARKit iPhone app sends RGB, depth, confidence, camera metadata, and timestamps over a paired local WebSocket. The existing Mac `WebConsoleRuntime` remains the sole O6 owner; it validates the latest sensor frame, performs object/depth geometry, applies explicit arming and safety gates, and publishes RGB/depth/status to the localhost dashboard.

**Tech Stack:** Python 3.9+, Flask, OpenCV, NumPy, MediaPipe, `websockets`, `zeroconf`, Swift 5.9+, SwiftUI, ARKit, Network.framework, Xcode 26.6, XCTest.

---

## File Map

### Mac: create

- `apps/o6-camera-teleop/vision/depth_protocol.py`: strict binary protocol and immutable frame model.
- `apps/o6-camera-teleop/vision/depth_geometry.py`: target ROI mapping, robust depth, signed distance, and calibration samples.
- `apps/o6-camera-teleop/vision/depth_receiver.py`: paired WebSocket receiver, Bonjour publication, single-client and freshness state.
- `apps/o6-camera-teleop/vision/frame_source.py`: lazy Mac camera plus latest iPhone frame selection.
- `apps/o6-camera-teleop/control/depth_grasp.py`: pre-grasp/contact state and stable-contact gate.
- `apps/o6-camera-teleop/config_store.py`: atomic calibration persistence.
- `apps/o6-camera-teleop/tests/test_depth_protocol.py`
- `apps/o6-camera-teleop/tests/depth_test_utils.py`
- `apps/o6-camera-teleop/tests/test_depth_geometry.py`
- `apps/o6-camera-teleop/tests/test_depth_grasp.py`
- `apps/o6-camera-teleop/tests/test_depth_receiver.py`
- `apps/o6-camera-teleop/tests/test_frame_source.py`
- `apps/o6-camera-teleop/tests/test_web_depth_api.py`
- `apps/o6-camera-teleop/tools/send_depth_fixture.py`: local protocol and dry-run fixture sender.

### Mac: modify

- `apps/o6-camera-teleop/control/console_mode.py`: add the mutually exclusive vision source state.
- `apps/o6-camera-teleop/control/grasp_state.py`: allow target tracking while an external depth gate blocks closure.
- `apps/o6-camera-teleop/web_console.py`: own the receiver, calibration, source routing, depth visualization, actions, and status.
- `apps/o6-camera-teleop/config.yaml`: add `iphone_lidar` defaults.
- `apps/o6-camera-teleop/requirements.txt`: add pinned-major network dependencies.
- `apps/o6-camera-teleop/web/index.html`: add source, pairing, depth, distance, and calibration controls.
- `apps/o6-camera-teleop/web/app.js`: render depth state and send new actions.
- `apps/o6-camera-teleop/web/styles.css`: responsive two-stream control layout.
- `apps/o6-camera-teleop/README.md`: deployment, calibration, dry-run, real mode, and troubleshooting.

### iPhone: create

- `apps/o6-depth-streamer-ios/project.yml`: reproducible XcodeGen project definition.
- `apps/o6-depth-streamer-ios/O6DepthStreamer/App/O6DepthStreamerApp.swift`
- `apps/o6-depth-streamer-ios/O6DepthStreamer/App/ContentView.swift`
- `apps/o6-depth-streamer-ios/O6DepthStreamer/Capture/ARDepthCapture.swift`
- `apps/o6-depth-streamer-ios/O6DepthStreamer/Models/DepthFramePayload.swift`
- `apps/o6-depth-streamer-ios/O6DepthStreamer/Network/DepthPacketEncoder.swift`
- `apps/o6-depth-streamer-ios/O6DepthStreamer/Network/DepthStreamClient.swift`
- `apps/o6-depth-streamer-ios/O6DepthStreamer/Network/MacServiceBrowser.swift`
- `apps/o6-depth-streamer-ios/O6DepthStreamer/Resources/Info.plist`
- `apps/o6-depth-streamer-ios/O6DepthStreamerTests/DepthPacketEncoderTests.swift`
- `apps/o6-depth-streamer-ios/README.md`
- Generated and committed `apps/o6-depth-streamer-ios/O6DepthStreamer.xcodeproj/`.

## Task 1: Establish Baseline and Vision Source State

**Files:**
- Modify: `apps/o6-camera-teleop/control/console_mode.py`
- Modify: `apps/o6-camera-teleop/tests/test_mapper.py`

- [ ] **Step 1: Run the existing baseline**

Run:

```bash
cd apps/o6-camera-teleop
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all existing tests pass before feature changes.

- [ ] **Step 2: Write the failing source-switch test**

Add to `MapperAndFilterTest`:

```python
def test_vision_source_switch_resets_active_controls(self):
    state = ConsoleModeState()
    state.switch(ConsoleMode.HAND_FOLLOW)
    self.assertTrue(state.enable_follow(emergency_stopped=False))
    state.switch_source(VisionSource.IPHONE_LIDAR)
    self.assertEqual(state.vision_source, VisionSource.IPHONE_LIDAR)
    self.assertEqual(state.mode, ConsoleMode.OBJECT_GRASP)
    self.assertFalse(state.follow_enabled)
```

Import `VisionSource` from `control.console_mode`.

- [ ] **Step 3: Verify the new test fails**

Run: `.venv/bin/python -m unittest tests.test_mapper.MapperAndFilterTest.test_vision_source_switch_resets_active_controls -v`

Expected: FAIL because `VisionSource` does not exist.

- [ ] **Step 4: Implement the source state**

Add to `control/console_mode.py`:

```python
class VisionSource(str, Enum):
    MAC_CAMERA = "mac-camera"
    IPHONE_LIDAR = "iphone-lidar"


@dataclass
class ConsoleModeState:
    mode: ConsoleMode = ConsoleMode.OBJECT_GRASP
    vision_source: VisionSource = VisionSource.MAC_CAMERA
    follow_enabled: bool = False
    tracking_state: TrackingState = TrackingState.WAITING_HAND
    last_hand_time: float | None = None

    def switch_source(self, source: VisionSource) -> None:
        self.vision_source = source
        if source == VisionSource.IPHONE_LIDAR:
            self.mode = ConsoleMode.OBJECT_GRASP
        self.pause_follow()
```

Preserve the existing `switch`, `enable_follow`, `pause_follow`, `observe_hand`, and `can_send_hand` implementations in the class.

- [ ] **Step 5: Run the focused and baseline tests**

Run: `.venv/bin/python -m unittest tests.test_mapper -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/o6-camera-teleop/control/console_mode.py apps/o6-camera-teleop/tests/test_mapper.py
git commit -m "feat: add O6 vision source state"
```

## Task 2: Implement the Binary Depth Protocol

**Files:**
- Create: `apps/o6-camera-teleop/vision/depth_protocol.py`
- Create: `apps/o6-camera-teleop/tests/test_depth_protocol.py`
- Create: `apps/o6-camera-teleop/tests/depth_test_utils.py`

- [ ] **Step 1: Write protocol tests**

Create tests that build a `2x2` JPEG, depth array, and confidence array, then verify parsing and rejection:

```python
class DepthProtocolTest(unittest.TestCase):
    def test_round_trip_fixture_parses_exact_buffers(self):
        rgb = np.full((2, 2, 3), 80, dtype=np.uint8)
        ok, jpeg = cv2.imencode(".jpg", rgb)
        self.assertTrue(ok)
        depth = np.array([[400, 500], [0, 700]], dtype="<u2")
        confidence = np.array([[2, 2], [0, 1]], dtype=np.uint8)
        payload = make_fixture(jpeg.tobytes(), depth, confidence)
        frame = parse_depth_frame(payload, received_monotonic=10.0, max_message_bytes=4096)
        self.assertEqual(frame.sequence, 7)
        self.assertEqual(frame.depth_mm.tolist(), depth.tolist())
        self.assertEqual(frame.confidence.tolist(), confidence.tolist())
        self.assertEqual(frame.rgb_bgr.shape, (2, 2, 3))

    def test_rejects_truncated_and_oversize_frames(self):
        with self.assertRaises(DepthProtocolError):
            parse_depth_frame(b"\x00\x00\x00\x20{}", received_monotonic=1.0, max_message_bytes=4096)
        with self.assertRaises(DepthProtocolError):
            parse_depth_frame(b"x" * 20, received_monotonic=1.0, max_message_bytes=10)
```

The fixture header uses protocol version `1`, matching byte lengths, orientation `landscapeRight`, four intrinsics values, nine RGB-to-depth values, and sixteen camera-transform values.

Define the test helper in the same file:

```python
def make_fixture(jpeg: bytes, depth: np.ndarray, confidence: np.ndarray) -> bytes:
    header = {
        "protocol_version": 1, "sequence": 7, "timestamp_ns": 99,
        "device_name": "Duami", "orientation": "landscapeRight",
        "rgb_width": 2, "rgb_height": 2, "rgb_length": len(jpeg),
        "depth_width": depth.shape[1], "depth_height": depth.shape[0],
        "depth_length": depth.nbytes, "confidence_length": confidence.nbytes,
        "intrinsics": [1, 1, 0, 0],
        "rgb_to_depth": [1, 0, 0, 0, 1, 0, 0, 0, 1],
        "camera_transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
    }
    encoded = json.dumps(header, separators=(",", ":")).encode()
    return struct.pack(">I", len(encoded)) + encoded + jpeg + depth.tobytes() + confidence.tobytes()
```

Create `tests/depth_test_utils.py` after `DepthFrame` exists:

```python
def make_depth_frame(sequence=1, received_monotonic=0.0, depth_value=500):
    return DepthFrame(sequence, sequence, received_monotonic, "Duami", "landscapeRight",
        np.zeros((1, 1, 3), np.uint8), np.full((1, 1), depth_value, np.uint16),
        np.full((1, 1), 2, np.uint8), (1.0, 1.0, 0.0, 0.0),
        (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
         0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0))
```

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m unittest tests.test_depth_protocol -v`

Expected: FAIL because `vision.depth_protocol` does not exist.

- [ ] **Step 3: Implement strict parsing**

Implement this public API:

```python
PROTOCOL_VERSION = 1

class DepthProtocolError(ValueError):
    pass

@dataclass(frozen=True)
class DepthFrame:
    sequence: int
    timestamp_ns: int
    received_monotonic: float
    device_name: str
    orientation: str
    rgb_bgr: np.ndarray
    depth_mm: np.ndarray
    confidence: np.ndarray
    intrinsics: tuple[float, float, float, float]
    rgb_to_depth: tuple[float, ...]
    camera_transform: tuple[float, ...]

def parse_depth_frame(payload: bytes, *, received_monotonic: float, max_message_bytes: int) -> DepthFrame:
    if len(payload) > max_message_bytes or len(payload) < 5:
        raise DepthProtocolError("invalid message size")
    header_size = struct.unpack_from(">I", payload, 0)[0]
    if header_size < 2 or 4 + header_size > len(payload):
        raise DepthProtocolError("invalid header length")
    try:
        header = json.loads(payload[4:4 + header_size].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DepthProtocolError("invalid JSON header") from exc
    required = {
        "protocol_version", "sequence", "timestamp_ns", "device_name", "orientation",
        "rgb_width", "rgb_height", "rgb_length", "depth_width", "depth_height",
        "depth_length", "confidence_length", "intrinsics", "rgb_to_depth",
        "camera_transform",
    }
    if required - header.keys() or header["protocol_version"] != PROTOCOL_VERSION:
        raise DepthProtocolError("unsupported or incomplete header")
    depth_pixels = int(header["depth_width"]) * int(header["depth_height"])
    lengths = (int(header["rgb_length"]), int(header["depth_length"]), int(header["confidence_length"]))
    if lengths[1] != depth_pixels * 2 or lengths[2] != depth_pixels:
        raise DepthProtocolError("invalid depth buffer lengths")
    body = memoryview(payload)[4 + header_size:]
    if len(body) != sum(lengths):
        raise DepthProtocolError("payload length mismatch")
    rgb_end = lengths[0]
    depth_end = rgb_end + lengths[1]
    rgb = cv2.imdecode(np.frombuffer(body[:rgb_end], dtype=np.uint8), cv2.IMREAD_COLOR)
    if rgb is None or rgb.shape[:2] != (int(header["rgb_height"]), int(header["rgb_width"])):
        raise DepthProtocolError("invalid JPEG dimensions")
    depth = np.frombuffer(body[rgb_end:depth_end], dtype="<u2").reshape(header["depth_height"], header["depth_width"]).copy()
    confidence = np.frombuffer(body[depth_end:], dtype=np.uint8).reshape(header["depth_height"], header["depth_width"]).copy()
    intrinsics = tuple(float(v) for v in header["intrinsics"])
    rgb_to_depth = tuple(float(v) for v in header["rgb_to_depth"])
    camera_transform = tuple(float(v) for v in header["camera_transform"])
    if len(intrinsics) != 4 or len(rgb_to_depth) != 9 or len(camera_transform) != 16:
        raise DepthProtocolError("invalid matrix metadata")
    return DepthFrame(int(header["sequence"]), int(header["timestamp_ns"]), received_monotonic,
        str(header["device_name"]), str(header["orientation"]), rgb, depth, confidence,
        intrinsics, rgb_to_depth, camera_transform)
```

- [ ] **Step 4: Run tests and lint syntax**

Run:

```bash
.venv/bin/python -m unittest tests.test_depth_protocol -v
.venv/bin/python -m py_compile vision/depth_protocol.py
```

Expected: PASS and no compiler output.

- [ ] **Step 5: Commit**

```bash
git add apps/o6-camera-teleop/vision/depth_protocol.py apps/o6-camera-teleop/tests/test_depth_protocol.py apps/o6-camera-teleop/tests/depth_test_utils.py
git commit -m "feat: parse iPhone LiDAR frames"
```

## Task 3: Implement Robust Target Depth and Calibration

**Files:**
- Create: `apps/o6-camera-teleop/vision/depth_geometry.py`
- Create: `apps/o6-camera-teleop/tests/test_depth_geometry.py`

- [ ] **Step 1: Write geometry tests**

Cover normalized RGB box mapping, low-confidence rejection, outlier rejection, signed direction, and 15-sample calibration:

```python
def test_measurement_filters_background_outlier_and_signs_distance():
    depth = np.full((100, 100), 550, dtype=np.uint16)
    confidence = np.full((100, 100), 2, dtype=np.uint8)
    depth[50, 50] = 4000
    result = measure_depth(depth, confidence, rgb_box=(25, 25, 50, 50),
        rgb_size=(100, 100), inner_ratio=0.5, min_confidence=1,
        min_valid_ratio=0.2, contact_depth_mm=500)
    self.assertAlmostEqual(result.target_depth_mm, 550.0)
    self.assertAlmostEqual(result.signed_distance_mm, 50.0)

def test_calibrator_requires_stable_sample_count():
    calibrator = ContactCalibrator(required_samples=3)
    self.assertIsNone(calibrator.add(500.0))
    self.assertIsNone(calibrator.add(502.0))
    self.assertEqual(calibrator.add(501.0), 501.0)
```

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m unittest tests.test_depth_geometry -v`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the geometry API**

```python
@dataclass(frozen=True)
class DepthMeasurement:
    target_depth_mm: float | None
    signed_distance_mm: float | None
    valid_ratio: float
    depth_roi: tuple[int, int, int, int]

def measure_depth(depth_mm, confidence, *, rgb_box, rgb_size, inner_ratio,
                  min_confidence, min_valid_ratio, contact_depth_mm):
    rgb_x, rgb_y, rgb_w, rgb_h = rgb_box
    rgb_width, rgb_height = rgb_size
    center_x = (rgb_x + rgb_w / 2) / rgb_width
    center_y = (rgb_y + rgb_h / 2) / rgb_height
    roi_w = rgb_w / rgb_width * inner_ratio
    roi_h = rgb_h / rgb_height * inner_ratio
    x1 = max(0, int((center_x - roi_w / 2) * depth_mm.shape[1]))
    x2 = min(depth_mm.shape[1], int(np.ceil((center_x + roi_w / 2) * depth_mm.shape[1])))
    y1 = max(0, int((center_y - roi_h / 2) * depth_mm.shape[0]))
    y2 = min(depth_mm.shape[0], int(np.ceil((center_y + roi_h / 2) * depth_mm.shape[0])))
    values = depth_mm[y1:y2, x1:x2]
    scores = confidence[y1:y2, x1:x2]
    valid = values[(values > 0) & (scores >= min_confidence)].astype(np.float64)
    ratio = 0.0 if values.size == 0 else float(valid.size / values.size)
    if ratio < min_valid_ratio or valid.size == 0:
        return DepthMeasurement(None, None, ratio, (x1, y1, x2, y2))
    median = float(np.median(valid))
    mad = float(np.median(np.abs(valid - median)))
    if mad > 0:
        valid = valid[np.abs(valid - median) <= 3.0 * 1.4826 * mad]
        median = float(np.median(valid))
    signed = None if contact_depth_mm is None else median - float(contact_depth_mm)
    return DepthMeasurement(median, signed, ratio, (x1, y1, x2, y2))

class ContactCalibrator:
    def __init__(self, required_samples: int = 15) -> None:
        self.required_samples = required_samples
        self.samples: list[float] = []
    def reset(self) -> None:
        self.samples.clear()
    def add(self, depth_mm: float | None) -> float | None:
        if depth_mm is None:
            return None
        self.samples.append(float(depth_mm))
        if len(self.samples) < self.required_samples:
            return None
        value = float(np.median(self.samples[-self.required_samples:]))
        self.reset()
        return value
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m unittest tests.test_depth_geometry -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/o6-camera-teleop/vision/depth_geometry.py apps/o6-camera-teleop/tests/test_depth_geometry.py
git commit -m "feat: measure signed LiDAR target distance"
```

## Task 4: Add the Depth Safety Gate

**Files:**
- Create: `apps/o6-camera-teleop/control/depth_grasp.py`
- Create: `apps/o6-camera-teleop/tests/test_depth_grasp.py`
- Modify: `apps/o6-camera-teleop/control/grasp_state.py`
- Modify: `apps/o6-camera-teleop/tests/test_mapper.py`

- [ ] **Step 1: Write failing tests**

```python
def test_gate_opens_at_five_cm_and_confirms_contact_after_three_frames():
    gate = DepthGraspGate(open_threshold_mm=50, contact_threshold_mm=0, stable_frames=3)
    self.assertEqual(gate.update(80, armed=True, hand_blocked=False).phase, DepthPhase.OUTSIDE_OPEN_ZONE)
    self.assertTrue(gate.update(40, armed=True, hand_blocked=False).should_open)
    self.assertFalse(gate.update(-1, armed=True, hand_blocked=False).contact_confirmed)
    self.assertFalse(gate.update(-2, armed=True, hand_blocked=False).contact_confirmed)
    self.assertTrue(gate.update(-1, armed=True, hand_blocked=False).contact_confirmed)

def test_invalid_unarmed_or_blocked_never_confirms():
    gate = DepthGraspGate(50, 0, 2)
    for kwargs in ({"distance": None, "armed": True, "hand_blocked": False},
                   {"distance": -1, "armed": False, "hand_blocked": False},
                   {"distance": -1, "armed": True, "hand_blocked": True}):
        self.assertFalse(gate.update(kwargs["distance"], armed=kwargs["armed"],
            hand_blocked=kwargs["hand_blocked"]).contact_confirmed)
```

Also extend the existing grasp-state test to call `machine.update(target, allow_close=False)` for more than `stable_frames`, assert `ARMED`, then call with `allow_close=True` and assert `CLOSING`.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m unittest tests.test_depth_grasp tests.test_mapper -v`

Expected: FAIL for missing gate and `allow_close` argument.

- [ ] **Step 3: Implement the gate and external close permission**

```python
class DepthPhase(str, Enum):
    DEPTH_UNAVAILABLE = "DEPTH_UNAVAILABLE"
    OUTSIDE_OPEN_ZONE = "OUTSIDE_OPEN_ZONE"
    PREGRASP_OPEN = "PREGRASP_OPEN"
    CONTACT_CONFIRMED = "CONTACT_CONFIRMED"

@dataclass(frozen=True)
class DepthDecision:
    phase: DepthPhase
    should_open: bool
    contact_confirmed: bool
    stable_count: int

class DepthGraspGate:
    def __init__(self, open_threshold_mm: float, contact_threshold_mm: float, stable_frames: int):
        if open_threshold_mm <= contact_threshold_mm or stable_frames < 1:
            raise ValueError("invalid depth grasp thresholds")
        self.open_threshold_mm = float(open_threshold_mm)
        self.contact_threshold_mm = float(contact_threshold_mm)
        self.stable_frames = int(stable_frames)
        self.stable_count = 0
    def reset(self) -> None:
        self.stable_count = 0
    def update(self, distance: float | None, *, armed: bool, hand_blocked: bool) -> DepthDecision:
        if distance is None or not armed or hand_blocked:
            self.reset()
            return DepthDecision(DepthPhase.DEPTH_UNAVAILABLE, False, False, 0)
        if distance > self.open_threshold_mm:
            self.reset()
            return DepthDecision(DepthPhase.OUTSIDE_OPEN_ZONE, False, False, 0)
        if distance > self.contact_threshold_mm:
            self.reset()
            return DepthDecision(DepthPhase.PREGRASP_OPEN, True, False, 0)
        self.stable_count += 1
        confirmed = self.stable_count >= self.stable_frames
        phase = DepthPhase.CONTACT_CONFIRMED if confirmed else DepthPhase.PREGRASP_OPEN
        return DepthDecision(phase, True, confirmed, self.stable_count)
```

Change `GraspStateMachine.update` to `def update(self, observation, *, allow_close: bool = True)` and guard its transition with `if allow_close and self.stable_count >= self.stable_frames:`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m unittest tests.test_depth_grasp tests.test_mapper -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/o6-camera-teleop/control/depth_grasp.py apps/o6-camera-teleop/control/grasp_state.py apps/o6-camera-teleop/tests/test_depth_grasp.py apps/o6-camera-teleop/tests/test_mapper.py
git commit -m "feat: gate O6 grasp on stable depth contact"
```

## Task 5: Build the Paired Depth Receiver

**Files:**
- Create: `apps/o6-camera-teleop/vision/depth_receiver.py`
- Create: `apps/o6-camera-teleop/tests/test_depth_receiver.py`
- Modify: `apps/o6-camera-teleop/requirements.txt`

- [ ] **Step 1: Add dependencies and install them**

Append:

```text
websockets>=14,<16
zeroconf>=0.140,<1
```

Run: `.venv/bin/python -m pip install -r requirements.txt`

Expected: successful install of `websockets` and `zeroconf`.

- [ ] **Step 2: Write receiver-state tests**

Test `validate_hello`, one-client ownership, increasing sequence, freshness, overwrite-old-frame behavior, and disconnect status without opening a real port:

```python
def test_latest_frame_requires_fresh_monotonic_time(self):
    state = DepthReceiverState(pairing_code="123456", timeout_seconds=0.5)
    state.connect("Duami", "123456")
    state.accept(make_depth_frame(sequence=1, received_monotonic=10.0))
    self.assertEqual(state.latest(now=10.4).sequence, 1)
    self.assertIsNone(state.latest(now=10.6))

def test_wrong_code_and_second_client_are_rejected(self):
    state = DepthReceiverState("123456", 0.5)
    with self.assertRaises(PairingError):
        state.connect("Duami", "999999")
    state.connect("Duami", "123456")
    with self.assertRaises(PairingError):
        state.connect("Other", "123456")
```

Import `make_depth_frame` from `tests.depth_test_utils`.

- [ ] **Step 3: Verify failure**

Run: `.venv/bin/python -m unittest tests.test_depth_receiver -v`

Expected: FAIL because the receiver module is missing.

- [ ] **Step 4: Implement state and service lifecycle**

Expose:

```python
class PairingError(ValueError):
    pass

class DepthReceiverState:
    def __init__(self, pairing_code: str, timeout_seconds: float) -> None:
        self.pairing_code = pairing_code
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._client: str | None = None
        self._latest: DepthFrame | None = None
        self._last_sequence = -1
    def connect(self, device: str, code: str) -> None:
        with self._lock:
            if not secrets.compare_digest(code, self.pairing_code):
                raise PairingError("invalid pairing code")
            if self._client is not None:
                raise PairingError("another iPhone is already connected")
            self._client = device
            self._last_sequence = -1
    def accept(self, frame: DepthFrame) -> None:
        with self._lock:
            if self._client is None or frame.sequence <= self._last_sequence:
                raise PairingError("invalid frame sequence")
            self._latest = frame
            self._last_sequence = frame.sequence
    def latest(self, now: float) -> DepthFrame | None:
        with self._lock:
            frame = self._latest
            return frame if frame and now - frame.received_monotonic <= self.timeout_seconds else None
    def disconnect(self) -> None:
        with self._lock:
            self._client = None
            self._latest = None
            self._last_sequence = -1
```

Implement `DepthReceiver.start()` as a daemon-thread asyncio loop using `websockets.asyncio.server.serve`, requiring the first message to be JSON `hello`, calling `parse_depth_frame` for binary messages, and stopping via an asyncio event. Publish `_o6depth._tcp.local.` with `zeroconf.ServiceInfo`; always unregister and close Zeroconf in `stop()`.

Configure WebSocket protocol pings every two seconds and publish `depth_latency_ms` as the measured round-trip time. Do not subtract the iPhone frame timestamp from the Mac clock because the devices do not share a monotonic clock; stale-frame checks use Mac `received_monotonic` only.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m unittest tests.test_depth_receiver -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/o6-camera-teleop/vision/depth_receiver.py apps/o6-camera-teleop/tests/test_depth_receiver.py apps/o6-camera-teleop/requirements.txt
git commit -m "feat: receive paired iPhone depth stream"
```

## Task 6: Add Frame Routing and Atomic Calibration Storage

**Files:**
- Create: `apps/o6-camera-teleop/vision/frame_source.py`
- Create: `apps/o6-camera-teleop/config_store.py`
- Create: `apps/o6-camera-teleop/tests/test_frame_source.py`
- Modify: `apps/o6-camera-teleop/config.yaml`

- [ ] **Step 1: Write frame-source and persistence tests**

Use a fake capture factory and fake receiver. Assert Mac capture is opened lazily only for `MAC_CAMERA`, stale iPhone frames return `None`, and atomic YAML save preserves unrelated keys.

```python
def test_iphone_source_does_not_open_mac_camera(self):
    opened = []
    manager = FrameSourceManager(0, FakeReceiver(make_depth_frame()), lambda index: opened.append(index))
    sample = manager.read(VisionSource.IPHONE_LIDAR, now=1.0)
    self.assertEqual(sample.source, VisionSource.IPHONE_LIDAR)
    self.assertEqual(opened, [])

def test_atomic_contact_save_preserves_existing_config(self):
    save_contact_depth(path, 432.0)
    saved = yaml.safe_load(path.read_text())
    self.assertEqual(saved["iphone_lidar"]["contact_depth_mm"], 432.0)
    self.assertEqual(saved["o6"]["hand_type"], "left")
```

Define `FakeReceiver` locally with `latest(self, now)` returning its constructor frame, and import `make_depth_frame` from `tests.depth_test_utils`.

- [ ] **Step 2: Implement frame routing**

```python
@dataclass(frozen=True)
class FrameSample:
    source: VisionSource
    bgr: np.ndarray
    depth: DepthFrame | None

class FrameSourceManager:
    def __init__(self, camera_index, receiver, capture_factory=cv2.VideoCapture):
        self.camera_index = camera_index
        self.receiver = receiver
        self.capture_factory = capture_factory
        self.capture = None
    def read(self, source: VisionSource, now: float) -> FrameSample | None:
        if source == VisionSource.IPHONE_LIDAR:
            frame = self.receiver.latest(now)
            return None if frame is None else FrameSample(source, frame.rgb_bgr.copy(), frame)
        if self.capture is None:
            self.capture = self.capture_factory(self.camera_index)
        ok, bgr = self.capture.read()
        return FrameSample(source, bgr, None) if ok else None
    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None
```

Implement `save_contact_depth(path, value)` with `tempfile.NamedTemporaryFile` in the config directory, `yaml.safe_dump(..., allow_unicode=True, sort_keys=False)`, `os.fsync`, and `os.replace`.

- [ ] **Step 3: Add the exact `iphone_lidar` defaults**

Add the YAML block from the approved design, with `contact_depth_mm: null` and `enabled: true`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m unittest tests.test_frame_source -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/o6-camera-teleop/vision/frame_source.py apps/o6-camera-teleop/config_store.py apps/o6-camera-teleop/tests/test_frame_source.py apps/o6-camera-teleop/config.yaml
git commit -m "feat: route O6 vision sources and persist depth calibration"
```

## Task 7: Integrate LiDAR into the Single Mac Runtime

**Files:**
- Modify: `apps/o6-camera-teleop/web_console.py:26-789`
- Create: `apps/o6-camera-teleop/tests/test_web_depth_api.py`

- [ ] **Step 1: Write failing web/runtime contract tests**

Test that all four new actions are accepted, `/depth_feed` exists, status includes the approved fields, source changes disarm, calibration is rejected without valid depth, and stale depth never advances `CLOSING`.

```python
NEW_ACTIONS = {"source-mac-camera", "source-iphone-lidar",
               "depth-calibrate-contact", "depth-clear-calibration"}

def test_depth_routes_and_actions_are_exposed(self):
    self.assertTrue(NEW_ACTIONS <= ALLOWED_ACTIONS)
    app = create_app(FakeRuntime())
    client = app.test_client()
    self.assertEqual(client.get("/depth_feed").status_code, 200)
    for action in NEW_ACTIONS:
        self.assertEqual(client.post("/api/action", json={"action": action}).status_code, 202)
```

Define `FakeRuntime` in this test with `status_snapshot`, `enqueue_action`, `mjpeg_stream`, and `depth_mjpeg_stream`; both stream methods return `iter(())`, and `enqueue_action` accepts exactly `ALLOWED_ACTIONS`.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m unittest tests.test_web_depth_api -v`

Expected: FAIL for missing actions/route/status.

- [ ] **Step 3: Add receiver and depth stream ownership**

In `WebConsoleRuntime.__init__`, add status fields defined by the spec, a second JPEG condition/cache for depth, and construct `DepthReceiver` from `config["iphone_lidar"]`. In `start`, start the receiver before the runtime thread. In `stop`, stop the runtime thread before stopping the receiver. Add `depth_mjpeg_stream()` mirroring `mjpeg_stream()`.

Render depth safely with:

```python
def _depth_colormap(depth_mm: np.ndarray, roi=None) -> np.ndarray:
    valid = depth_mm > 0
    scaled = np.zeros(depth_mm.shape, dtype=np.uint8)
    if np.any(valid):
        low, high = np.percentile(depth_mm[valid], [5, 95])
        scaled[valid] = np.clip((depth_mm[valid] - low) * 255 / max(high - low, 1), 0, 255)
    image = cv2.applyColorMap(255 - scaled, cv2.COLORMAP_TURBO)
    image[~valid] = 0
    if roi:
        cv2.rectangle(image, (roi[0], roi[1]), (roi[2], roi[3]), (255, 255, 255), 2)
    return image
```

- [ ] **Step 4: Add source/calibration actions**

Each source action must send safe-open, reset both filters, reset the grasp machine and depth gate, clear the foreground detector, switch `VisionSource`, and remain disarmed. Calibration starts a 15-valid-frame `ContactCalibrator`; completion calls `save_contact_depth`. Clearing calibration persists `null`. Reject calibration unless the current source is iPhone, a target exists, and depth is valid.

- [ ] **Step 5: Replace unconditional camera reads with `FrameSourceManager`**

The loop obtains `FrameSample`. In iPhone mode, a missing fresh frame updates `iphone_connected=False`, resets the contact gate, disarms if state is `ARMED`, and sleeps briefly. If state is `CLOSING` or `HOLDING`, it sends no new command and preserves `current_pose`.

For a valid LiDAR target:

```python
measurement = measure_depth(
    sample.depth.depth_mm,
    sample.depth.confidence,
    rgb_box=(target.x, target.y, target.width, target.height),
    rgb_size=(target.frame_width, target.frame_height),
    inner_ratio=lidar_config["roi_inner_ratio"],
    min_confidence=confidence_value(lidar_config["min_confidence"]),
    min_valid_ratio=lidar_config["min_valid_depth_ratio"],
    contact_depth_mm=contact_depth_mm,
)
decision = depth_gate.update(
    measurement.signed_distance_mm,
    armed=machine.state == GraspState.ARMED,
    hand_blocked=hand_blocked,
)
machine.update(
    None if hand_blocked or target is None else _observation(target),
    allow_close=decision.contact_confirmed,
)
```

Define `DEPTH_CONFIDENCE = {"low": 0, "medium": 1, "high": 2}` at module scope and implement `confidence_value(name)` as a strict lookup that raises `ValueError` for an unknown configuration value.

When `decision.should_open` and the machine remains `ARMED`, send the safe-open pose at the existing command period. Never call `move(grasp_pose)` until `machine.state == CLOSING`.

- [ ] **Step 6: Add route and status publishing**

Add:

```python
@app.get("/depth_feed")
def depth_feed():
    return Response(runtime.depth_mjpeg_stream(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"})
```

Publish all spec status fields and ensure `pairing_code` is only returned on localhost, which is guaranteed by the unchanged Flask bind default.

- [ ] **Step 7: Run Mac tests**

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/o6-camera-teleop/web_console.py apps/o6-camera-teleop/tests/test_web_depth_api.py
git commit -m "feat: integrate LiDAR grasp into O6 runtime"
```

## Task 8: Extend the Local Visual Console

**Files:**
- Modify: `apps/o6-camera-teleop/web/index.html`
- Modify: `apps/o6-camera-teleop/web/app.js`
- Modify: `apps/o6-camera-teleop/web/styles.css`

- [ ] **Step 1: Add the input and calibration controls**

Under the object-mode actions, add a segmented source group and depth controls:

```html
<div id="objectSourceControls">
  <div class="source-switch" role="group" aria-label="自动抓取视觉来源">
    <button id="macSourceButton" data-action="source-mac-camera" type="button">Mac 摄像头</button>
    <button id="iphoneSourceButton" data-action="source-iphone-lidar" type="button">iPhone LiDAR</button>
  </div>
  <div id="lidarActions" class="action-grid" hidden>
    <button id="calibrateDepthButton" class="button secondary" data-action="depth-calibrate-contact" type="button">记录 0 cm</button>
    <button id="clearDepthButton" class="button secondary" data-action="depth-clear-calibration" type="button">清除标定</button>
  </div>
</div>
```

Change the video area to two sibling figures. The depth figure contains `<img id="depthFeed" src="/depth_feed">` and is hidden outside iPhone mode. Add concise fields for pairing code, iPhone state, latency, valid depth ratio, signed distance, and depth phase.

- [ ] **Step 2: Implement status rendering**

Add depth phase labels and update logic:

```javascript
const DEPTH_LABELS = {
  DEPTH_UNAVAILABLE: "深度不可用",
  OUTSIDE_OPEN_ZONE: "目标在 5 cm 外",
  PREGRASP_OPEN: "预抓取 / 保持张开",
  CONTACT_CONFIRMED: "接触面已确认",
};

const lidarSource = status.vision_source === "iphone-lidar";
document.querySelector("#macSourceButton").classList.toggle("selected", !lidarSource);
document.querySelector("#iphoneSourceButton").classList.toggle("selected", lidarSource);
document.querySelector("#lidarActions").hidden = !lidarSource;
document.querySelector("#depthPanel").hidden = !lidarSource;
setText("#pairingCode", status.pairing_code || "------");
setText("#depthDistance", status.signed_distance_mm == null ? "---" : `${Number(status.signed_distance_mm).toFixed(1)} mm`);
setText("#depthPhase", DEPTH_LABELS[status.depth_phase] || "等待深度");
```

Disable `armButton` in LiDAR mode unless connected and calibrated. Disable calibration without a valid target/depth. Keep emergency stop and safe-open available.

- [ ] **Step 3: Add responsive styles**

Use an un-nested `.stream-grid` with two equal tracks on desktop and one track below `760px`. Keep the existing 6px radius, neutral operational palette, minimum video aspect ratio, and no card-inside-card treatment. Source buttons use the same segmented-control conventions as the mode and hand switches.

- [ ] **Step 4: Smoke-test the static page and API**

Run the console in dry-run:

```bash
./run_web.sh --dry-run
```

Open `http://127.0.0.1:8765`, verify no console errors, switch both modes and both sources, and capture desktop/mobile screenshots. Expected: no overlap; depth panel appears only for iPhone source; control buttons reflect status.

- [ ] **Step 5: Commit**

```bash
git add apps/o6-camera-teleop/web/index.html apps/o6-camera-teleop/web/app.js apps/o6-camera-teleop/web/styles.css
git commit -m "feat: visualize iPhone depth grasp state"
```

## Task 9: Scaffold the Native iPhone App and Packet Encoder

**Files:**
- Create: `apps/o6-depth-streamer-ios/project.yml`
- Create: `apps/o6-depth-streamer-ios/O6DepthStreamer/App/O6DepthStreamerApp.swift`
- Create: `apps/o6-depth-streamer-ios/O6DepthStreamer/Models/DepthFramePayload.swift`
- Create: `apps/o6-depth-streamer-ios/O6DepthStreamer/Network/DepthPacketEncoder.swift`
- Create: `apps/o6-depth-streamer-ios/O6DepthStreamer/Resources/Info.plist`
- Create: `apps/o6-depth-streamer-ios/O6DepthStreamerTests/DepthPacketEncoderTests.swift`

- [ ] **Step 1: Install XcodeGen and define the project**

Run: `brew install xcodegen`

Create `project.yml` with no hard-coded development team:

```yaml
name: O6DepthStreamer
options:
  bundleIdPrefix: com.duamixu.tailhand
settings:
  base:
    IPHONEOS_DEPLOYMENT_TARGET: "17.0"
    SWIFT_VERSION: "5.9"
    CODE_SIGN_STYLE: Automatic
targets:
  O6DepthStreamer:
    type: application
    platform: iOS
    sources: [O6DepthStreamer]
    info:
      path: O6DepthStreamer/Resources/Info.plist
  O6DepthStreamerTests:
    type: bundle.unit-test
    platform: iOS
    sources: [O6DepthStreamerTests]
    dependencies:
      - target: O6DepthStreamer
schemes:
  O6DepthStreamer:
    build:
      targets:
        O6DepthStreamer: all
    test:
      targets:
        - O6DepthStreamerTests
```

Info.plist must contain `NSCameraUsageDescription`, `NSLocalNetworkUsageDescription`, `NSBonjourServices` with `_o6depth._tcp`, `NSAppTransportSecurity > NSAllowsLocalNetworking: true`, and landscape-right as the supported orientation.

- [ ] **Step 2: Write the packet encoder test**

```swift
func testPacketUsesBigEndianHeaderAndOrderedBodies() throws {
    let payload = DepthFramePayload(sequence: 7, timestampNs: 9, deviceName: "Duami",
        rgbWidth: 2, rgbHeight: 2, jpeg: Data([1, 2]), depthWidth: 2, depthHeight: 1,
        depthMillimeters: Data([0x90, 0x01, 0xF4, 0x01]), confidence: Data([2, 1]),
        intrinsics: [1, 1, 0, 0], rgbToDepth: [1,0,0, 0,1,0, 0,0,1],
        cameraTransform: Array(repeating: 0, count: 16))
    let packet = try DepthPacketEncoder.encode(payload)
    let headerLength = packet.prefix(4).reduce(0) { ($0 << 8) | Int($1) }
    XCTAssertGreaterThan(headerLength, 0)
    XCTAssertEqual(packet.suffix(8), Data([1, 2, 0x90, 0x01, 0xF4, 0x01, 2, 1]))
}
```

- [ ] **Step 3: Implement packet models and encoder**

`DepthFramePayload` stores the fields used by the Python parser. `DepthPacketEncoder.encode` creates a `Codable` header with snake-case keys, JSON-encodes it, prefixes a 32-bit big-endian header length, then appends JPEG, little-endian depth, and confidence in that order. Reject matrix counts other than `4/9/16` and depth/confidence lengths inconsistent with dimensions.

- [ ] **Step 4: Generate and test the project**

Run:

```bash
cd apps/o6-depth-streamer-ios
xcodegen generate
xcodebuild -project O6DepthStreamer.xcodeproj -scheme O6DepthStreamer -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17 Pro,OS=latest' test CODE_SIGNING_ALLOWED=NO
```

Expected: `** TEST SUCCEEDED **`.

- [ ] **Step 5: Commit**

```bash
git add apps/o6-depth-streamer-ios
git commit -m "feat: scaffold O6 iPhone depth streamer"
```

## Task 10: Capture ARKit RGB and LiDAR Data

**Files:**
- Create: `apps/o6-depth-streamer-ios/O6DepthStreamer/Capture/ARDepthCapture.swift`
- Modify: `apps/o6-depth-streamer-ios/O6DepthStreamer/Models/DepthFramePayload.swift`

- [ ] **Step 1: Implement capability and lifecycle checks**

Create an `@MainActor final class ARDepthCapture: NSObject, ObservableObject, ARSessionDelegate` with published `isSupported`, `isRunning`, `previewImage`, `centerDepthMm`, `validDepthRatio`, and `lastError`. `start()` must require `ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)`, insert both `.sceneDepth` and `.smoothedSceneDepth` when supported, and run the session. `stop()` pauses it.

- [ ] **Step 2: Implement bounded frame conversion**

In `session(_:didUpdate:)`, throttle to 15 FPS, choose `smoothedSceneDepth ?? sceneDepth`, copy depth/confidence pixel buffers on a dedicated serial queue, and drop the incoming frame if conversion is still busy.

Convert depth meters to little-endian millimeters:

```swift
let millimeters = source.withMemoryRebound(to: Float32.self, capacity: count) { values in
    var output = (0..<count).map { index -> UInt16 in
        let meters = values[index]
        guard meters.isFinite, meters > 0 else { return 0 }
        return UInt16(clamping: Int((meters * 1000).rounded())).littleEndian
    }
    return output.withUnsafeBytes { Data($0) }
}
```

Use one reusable `CIContext` to orient landscape-right, scale RGB to `640x480`, and produce JPEG data. Flatten camera intrinsics and transform in column-major order. Emit a complete `DepthFramePayload` through an `onFrame` closure.

- [ ] **Step 3: Build without signing**

Run:

```bash
xcodebuild -project apps/o6-depth-streamer-ios/O6DepthStreamer.xcodeproj -scheme O6DepthStreamer -sdk iphoneos -destination 'generic/platform=iOS' build CODE_SIGNING_ALLOWED=NO
```

Expected: `** BUILD SUCCEEDED **`.

- [ ] **Step 4: Commit**

```bash
git add apps/o6-depth-streamer-ios/O6DepthStreamer/Capture apps/o6-depth-streamer-ios/O6DepthStreamer/Models
git commit -m "feat: capture iPhone ARKit depth frames"
```

## Task 11: Add Bonjour Discovery, WebSocket Streaming, and iPhone UI

**Files:**
- Create: `apps/o6-depth-streamer-ios/O6DepthStreamer/Network/MacServiceBrowser.swift`
- Create: `apps/o6-depth-streamer-ios/O6DepthStreamer/Network/DepthStreamClient.swift`
- Create: `apps/o6-depth-streamer-ios/O6DepthStreamer/App/ContentView.swift`
- Modify: `apps/o6-depth-streamer-ios/O6DepthStreamer/App/O6DepthStreamerApp.swift`

- [ ] **Step 1: Implement Bonjour discovery**

`MacServiceBrowser` uses `NWBrowser(for: .bonjour(type: "_o6depth._tcp", domain: nil), using: .tcp)`, publishes discovered `NWEndpoint` values and labels, and exposes a manual `.hostPort(host:port:)` fallback. Cancel the browser in `deinit`.

- [ ] **Step 2: Implement single-flight WebSocket sending**

`DepthStreamClient` creates `NWParameters.tcp`, inserts `NWProtocolWebSocket.Options` as the application protocol, and opens `NWConnection(to: selectedEndpoint, using: parameters)`. This lets a discovered Bonjour service endpoint resolve without converting it to a URL. On `.ready`, send a text WebSocket message:

```swift
let hello: [String: Any] = [
    "type": "hello", "protocol_version": 1,
    "pairing_code": pairingCode, "device_name": UIDevice.current.name,
    "supports_scene_depth": true
]
```

Attach `NWProtocolWebSocket.Metadata(opcode: .text)` to the hello content context. Wait for an `{"type":"hello_ack"}` response before accepting frames. Send packets with `.binary` metadata. Maintain one in-flight send; if another AR frame arrives before completion, replace the pending frame rather than growing a queue. On error, cancel the connection, publish the exact error, and require explicit reconnect.

Allow Network.framework to answer WebSocket ping control frames. The Mac-reported RTT is the authoritative dashboard latency; the iPhone may show send-completion duration separately but must not label cross-device timestamp subtraction as latency.

- [ ] **Step 3: Build the operational SwiftUI screen**

The first screen is the working tool, not a landing page. Include ARKit status, discovered Mac picker, manual host fallback, six-digit pairing input, connect/disconnect button, camera preview, center depth, effective FPS, latency, and valid-depth ratio. Use system icons for connect/disconnect and restrained native controls. Starting streaming requests camera and local-network permissions only after the user taps Connect.

- [ ] **Step 4: Run simulator tests and device build**

Run the packet tests again, then the generic device build. Expected: tests and build succeed. ARKit scene depth is marked unavailable in simulator without crashing.

- [ ] **Step 5: Commit**

```bash
git add apps/o6-depth-streamer-ios
git commit -m "feat: stream iPhone LiDAR frames over Wi-Fi"
```

## Task 12: Document and Verify the Complete Dry-Run Path

**Files:**
- Modify: `apps/o6-camera-teleop/README.md`
- Create: `apps/o6-depth-streamer-ios/README.md`
- Create: `apps/o6-camera-teleop/tools/send_depth_fixture.py`

- [ ] **Step 1: Document setup and exact operation order**

Cover XcodeGen generation, opening the project, selecting the user's personal signing team, connecting `Duami`, granting camera/local-network permissions, Mac firewall prompt, starting `./run_web.sh --dry-run`, selecting iPhone LiDAR, entering the pairing code, recording the 0 cm plane, arming, and interpreting the distance/phase displays.

Explicitly state that the Mac dashboard stays at `http://127.0.0.1:8765`, the iPhone connects to port `8766`, and this version does not move the robot arm.

- [ ] **Step 2: Add a no-browser synthetic sender**

Create `tools/send_depth_fixture.py` with `--host`, `--port`, `--pairing-code`, `--depth-mm`, `--frames`, and `--fps`. It draws a high-contrast centered object, constructs the exact protocol header, waits for `hello_ack`, and sends bounded frames:

```python
async def send(args):
    uri = f"ws://{args.host}:{args.port}"
    async with websockets.connect(uri, max_size=1_572_864) as socket:
        await socket.send(json.dumps({
            "type": "hello", "protocol_version": 1,
            "pairing_code": args.pairing_code,
            "device_name": "synthetic-depth",
            "supports_scene_depth": True,
        }))
        ack = json.loads(await socket.recv())
        if ack.get("type") != "hello_ack":
            raise RuntimeError(f"pairing rejected: {ack}")
        for sequence in range(args.frames):
            rgb = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.rectangle(rgb, (240, 150), (400, 350), (230, 230, 230), -1)
            ok, jpeg = cv2.imencode(".jpg", rgb)
            if not ok:
                raise RuntimeError("JPEG encoding failed")
            depth = np.full((192, 256), args.depth_mm, dtype="<u2")
            confidence = np.full((192, 256), 2, dtype=np.uint8)
            header = {
                "protocol_version": 1, "sequence": sequence,
                "timestamp_ns": time.time_ns(), "device_name": "synthetic-depth",
                "orientation": "landscapeRight",
                "rgb_width": 640, "rgb_height": 480, "rgb_length": int(jpeg.size),
                "depth_width": 256, "depth_height": 192,
                "depth_length": int(depth.nbytes),
                "confidence_length": int(confidence.nbytes),
                "intrinsics": [500, 500, 320, 240],
                "rgb_to_depth": [0.4, 0, 0, 0, 0.4, 0, 0, 0, 1],
                "camera_transform": [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1],
            }
            encoded = json.dumps(header, separators=(",", ":")).encode()
            packet = struct.pack(">I", len(encoded)) + encoded + jpeg.tobytes() + depth.tobytes() + confidence.tobytes()
            await socket.send(packet)
            await asyncio.sleep(1 / args.fps)
```

For a configured `contact_depth_mm: 500`, document raw `--depth-mm` invocations of `600`, `540`, and `495`, producing signed distances `+100 mm`, `+40 mm`, and `-5 mm`. Expected dry-run phases are outside, pregrasp-open, and contact-confirmed/closing after eight stable frames.

- [ ] **Step 3: Run all automated checks**

```bash
cd apps/o6-camera-teleop
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile web_console.py vision/*.py control/*.py config_store.py
cd ../o6-depth-streamer-ios
xcodebuild -project O6DepthStreamer.xcodeproj -scheme O6DepthStreamer -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17 Pro,OS=latest' test CODE_SIGNING_ALLOWED=NO
```

Expected: all Python tests pass, Python compilation emits nothing, and Xcode reports `** TEST SUCCEEDED **`.

- [ ] **Step 4: Perform browser QA**

Start the Mac dry-run console, inspect desktop and mobile widths, and verify RGB/depth rendering is nonblank, labels do not overlap, all new buttons call the action endpoint, mode/source controls are mutually exclusive, and disconnect status appears within 500 ms.

- [ ] **Step 5: Commit**

```bash
git add apps/o6-camera-teleop/README.md apps/o6-camera-teleop/tools/send_depth_fixture.py apps/o6-depth-streamer-ios/README.md
git commit -m "docs: add iPhone LiDAR O6 workflow"
```

## Task 13: Deploy to iPhone and Perform Staged Hardware Validation

**Files:**
- Modify only if measurements require safe configuration adjustment: `apps/o6-camera-teleop/config.yaml`
- Record results in: `apps/o6-camera-teleop/README.md`

- [ ] **Step 1: Install on the connected iPhone**

Open `O6DepthStreamer.xcodeproj`, select the user's Apple development team and the connected `Duami` iPhone 17 Pro, then Run. The user must personally accept signing, trust, camera, and local-network prompts.

Expected: app launches and reports LiDAR supported.

- [ ] **Step 2: Validate network and image data without O6**

Run Mac with `--dry-run`, pair the phone, and verify at least 60 seconds of RGB/depth streaming at a practical rate with no growing latency. Disconnect Wi-Fi and verify the dashboard reports loss within 500 ms and never advances the grasp state.

- [ ] **Step 3: Validate distance with a ruler and plane**

Mount the phone rigidly, record 0 cm, and measure objects at approximately 10 cm, 5 cm, and the trigger plane. Confirm distance decreases in the approach direction and does not change sign backward. Recalibrate after any mount movement.

- [ ] **Step 4: Validate dry-run state transitions**

Arm only after pairing and calibration. Verify `>5 cm` does not close, `5..0 cm` reports pregrasp and open pose, and `<=0 cm` for eight stable frames reaches closing/holding. Verify a human hand in the zone, invalid depth, target loss, source switch, and emergency stop all block closure.

- [ ] **Step 5: Perform guarded O6 real-mode validation**

Clear the area, use the configured low speed, keep physical power disconnect reachable, and start `--real`. First test empty-hand safe-open, then approach a soft object. Confirm all six outputs remain in `0..255` and the hand holds on stream loss instead of opening.

- [ ] **Step 6: Record verified and unverified results**

Add a dated validation section to the README with the iPhone model/iOS, measured FPS/latency, distance observations, O6 hand selection, backend, and any hardware-only item not completed. Do not claim hardware verification without observing it.

- [ ] **Step 7: Final verification commit**

```bash
git add apps/o6-camera-teleop/config.yaml apps/o6-camera-teleop/README.md
git commit -m "test: validate iPhone LiDAR O6 grasp path"
```

## Final Completion Check

- [ ] `git status --short` contains no accidental generated files or unrelated staged changes.
- [ ] Python test suite passes from `apps/o6-camera-teleop`.
- [ ] Swift test suite and generic iPhone build pass.
- [ ] Mac dashboard remains localhost-only; only the paired sensor port binds to the LAN.
- [ ] A stale/invalid/unpaired stream cannot trigger closure.
- [ ] Hand-follow and object-grasp remain mutually exclusive.
- [ ] O6 source switching, hand switching, safe-open, and emergency-stop behavior remain intact.
- [ ] README commands match the actual generated Xcode project and Mac entrypoints.
- [ ] Hardware claims distinguish dry-run, iPhone device validation, and O6 real-mode validation.
