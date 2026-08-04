# reCamera Armed Auto-Grasp Design

## Goal

Extend the existing reCamera eye-in-hand MVP so the O6 can close automatically after an operator explicitly arms object recognition and a central target remains stable for eight detector updates.

This feature remains RGB-only. It uses target position and bounding-box size as a proximity proxy and must not report or imply a physical distance in centimeters.

## Operator Flow

1. Start the existing single Mac runner in real mode.
2. Select `物品抓取` and `reCamera`.
3. Confirm the page reports `mac-pcan-o6`, left hand `0x28`, RTSP connected, and `DISARMED`.
4. Click `布防识别` once.
5. Move an object into the on-screen grasp zone.
6. When the same central target is eligible and stable for eight detector updates, the state changes from `ARMED` to `CLOSING` automatically.
7. The existing filtered command path closes to the configured conservative grasp pose and then holds.
8. Release only by clicking `安全张开`.

The existing `保守握合` action remains available as a manual test path.

## Arming Gates

The reCamera arm action is accepted only when all of these conditions are true:

- the runtime is in object-grasp mode;
- reCamera is the selected vision source;
- RTSP is connected and fresh;
- the O6 controller is connected, or the process was intentionally started in dry-run mode;
- the controller is not a `dry-run-fallback` caused by failed hardware initialization;
- emergency stop is not latched;
- the grasp state is `DISARMED`.

Arming does not move the O6. It changes the state to `ARMED`, clears any previous target, and resets the stability counter.

## Target Selection And Stability

The existing Mac-side detector remains authoritative. reCamera continues to provide only the RGB RTSP stream.

- Select the detected object whose center is closest to the image center.
- The target must lie inside the configured grasp zone.
- Its bounding-box area ratio must remain between the configured minimum and maximum limits.
- Consecutive detections must retain the same label and stay within the configured center tolerance.
- Eight consecutive eligible detections trigger `CLOSING`.
- Target loss, a label change, excessive center movement, or an ineligible box resets the stability counter to zero while keeping the system armed.
- A detected human hand in the grasp zone suppresses target observations and prevents the transition to `CLOSING`.

Once `CLOSING` begins, temporary target loss does not reverse the motion because the object is expected to become occluded by the fingers. A detected human hand during closing triggers the existing emergency-stop latch.

## Motion And Safety

Automatic closing reuses the existing command path without bypassing safeguards:

- command rate: 20 Hz;
- EMA filtering;
- input deadband;
- per-command maximum delta;
- output clipping to `0..255`;
- configured conservative grasp pose;
- transition to `HOLDING` only after reaching the target within the configured deadband.

RTSP loss while armed clears the target observation and stability counter, so no automatic close can begin. RTSP loss after closing has begun does not automatically open the hand. The operator must use `安全张开`, or `紧急停止` if motion must cease immediately.

## Web Console

In reCamera object mode the console shows:

- `布防识别` and `解除布防`;
- `保守握合` for manual testing;
- current grasp state;
- stability progress out of eight frames;
- selected target and confidence;
- existing RTSP and O6 diagnostics.

Button availability mirrors the backend safety gates. The UI must not claim that automatic grasp is armed when the backend rejected the request.

## Error Handling

- RTSP unavailable: reject arming and display a specific connection error.
- Hardware initialization fallback: reject real automatic grasp and state that commands are simulated only when dry-run was explicitly requested.
- Emergency stop latched: reject arming until the runner is restarted.
- Target lost before trigger: reset stability progress without moving the O6.
- Human hand in zone: block the trigger; if already closing, latch emergency stop.

## Verification

Automated tests must verify:

- reCamera arming is accepted only with a fresh stream and valid controller state;
- a stable eligible target triggers closing after exactly eight updates;
- target loss resets stability and does not close;
- a human hand suppresses the automatic transition;
- fallback hardware mode cannot arm real automatic grasp;
- the web console exposes both automatic arming and manual grasp controls in reCamera mode;
- the full existing test suite remains green.

Dry-run integration must verify that a stable target produces filtered pose commands and that target loss before the threshold produces no command. Real-hardware verification is limited to a clear workspace and a soft test object; release is performed with `安全张开`.

## Out Of Scope

- physical depth or centimeter measurements;
- automatic arm or wrist motion;
- force or tactile feedback;
- automatic release;
- model training or custom phone detection;
- using reCamera inference metadata instead of the Mac-side detector.
