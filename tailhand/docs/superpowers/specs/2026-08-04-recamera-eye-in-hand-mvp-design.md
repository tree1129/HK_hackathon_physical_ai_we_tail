# reCamera Eye-in-Hand MVP Design

Date: 2026-08-04

Status: approved for implementation

## Goal

Add the wrist-mounted reCamera 2002/2002w as a live RGB source in the existing O6 web console, show basic object detections, and provide explicit manual controls for the connected LinkerHand O6 left hand. This milestone proves the real camera, web visualization, and hardware command path before adding monocular proximity-triggered grasping.

## Scope

The MVP delivers one end-to-end path:

```text
reCamera Camera -> Node-RED RTSP stream -> Mac tailhand runner
  -> web video and object boxes
  -> explicit Open / Conservative Grasp / Emergency Stop buttons
  -> existing filtered O6 controller -> O6 left hand (CAN ID 0x28)
```

The Mac remains the only process allowed to command O6. reCamera provides video only and never sends hand commands.

## reCamera Setup

- Use the existing reCamera workspace at `http://192.168.254.153/#/workspace`.
- Deploy the official Node-RED `Camera -> Stream` flow.
- Enable an H.264 RTSP session on port `554`, with the session name and credentials treated as configuration rather than hard-coded values.
- Verify the stream independently before starting real O6 control.
- Do not modify reCamera firmware or require a custom RISC-V application for this milestone.

## Mac Application Changes

- Add `recamera` as a frame source beside the current Mac camera and iPhone LiDAR sources.
- Read the RTSP URL from `config.yaml` and reconnect after temporary failures.
- Detect stale frames and expose connection state, FPS, and latest-frame age.
- Reuse the existing object detector and draw its boxes on the reCamera view. Prefer the eligible detection nearest the frame center for the highlighted target.
- Do not use static-background differencing for the wrist camera because the camera moves with the wrist.
- Preserve the single `WebConsoleRuntime`, command filter, O6 controller, hand-side selection, dry-run fallback, and latched emergency stop.

## Web Console

The object mode gains a `reCamera` source option and displays:

- live wrist-camera video;
- object boxes and one highlighted central target;
- RTSP connected/disconnected state;
- FPS and latest-frame age;
- actual O6 backend and left-hand connection state.

It also provides three explicit commands:

- `Safe Open`: send the configured safe-open pose;
- `Conservative Grasp`: send the existing conservative grasp pose through the normal rate limiter;
- `Emergency Stop`: latch software stop and reject later motion commands until restart.

No camera event automatically moves O6 in this milestone. Manual close remains unavailable unless real mode reports a genuine hardware connection; dry-run shows the pose without pretending the hand moved.

## Safety And Failure Behavior

- Startup remains dry-run unless `--real` is explicitly selected.
- RTSP loss shows a visible error and freezes the last preview; it never creates an O6 command.
- Object loss clears the highlighted target; it never creates an O6 command.
- `Safe Open` remains available whenever the controller can safely send it.
- Emergency stop remains latched and takes priority over all other commands.
- O6 motion uses the existing command frequency and per-command delta limits.
- The user must secure the wrist/camera, clear the hand workspace, and keep physical power disconnection within reach before real movement.

## Acceptance

The milestone is complete when:

1. The reCamera RTSP stream can be opened from the Mac.
2. Selecting `reCamera` in the web console shows the wrist view without starting a second O6 runner.
3. Moving the wrist visibly updates the page and object boxes appear on supported objects.
4. Dry-run prints the safe-open and conservative-grasp poses without connecting hardware.
5. In explicit real mode, the connected O6 left hand safely opens and performs the conservative grasp from separate button presses.
6. Emergency stop rejects subsequent grasp commands.
7. Unplugging or stopping reCamera produces a visible disconnected state and no automatic hand motion.

## Deferred Work

The following work is intentionally excluded from this milestone:

- metric depth or centimeter labels;
- contact-zone calibration;
- far/near/contact classification;
- click-to-lock tracking;
- automatic proximity-triggered grasping;
- robot-arm or wrist motion control;
- moving inference from the Mac to reCamera.

These features can be added after the real wrist view, latency, framing, detector behavior, and O6 manual command path have been observed together.
