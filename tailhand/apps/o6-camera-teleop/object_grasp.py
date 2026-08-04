from __future__ import annotations

import time
from pathlib import Path

import cv2
import yaml

from control.filters import CommandFilter
from control.grasp_state import GraspState, GraspStateMachine, TargetObservation
from control.o6_controller import O6Controller
from vision.foreground_detector import ForegroundDetector
from vision.hand_tracker import HandDetection, HandTracker
from vision.object_detector import ObjectDetection, ObjectTracker


def _resolve(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def _read_frame(capture: cv2.VideoCapture, failures: int) -> tuple[object | None, int]:
    ok, frame = capture.read()
    if ok:
        return frame, 0
    failures += 1
    if failures < 10:
        time.sleep(0.05)
    return None, failures


def _observation(detection: ObjectDetection) -> TargetObservation:
    center_x, center_y = detection.center_normalized
    return TargetObservation(
        label=detection.label,
        score=detection.score,
        center_x=center_x,
        center_y=center_y,
        area_ratio=detection.area_ratio,
    )


def _draw_box(frame, detection: ObjectDetection, mirrored: bool, selected: bool) -> None:
    frame_width = frame.shape[1]
    x = frame_width - detection.x - detection.width if mirrored else detection.x
    color = (70, 225, 130) if selected else (140, 150, 160)
    cv2.rectangle(
        frame,
        (x, detection.y),
        (x + detection.width, detection.y + detection.height),
        color,
        3 if selected else 1,
    )
    label = f"{detection.label} {detection.score:.2f}"
    cv2.putText(
        frame,
        label,
        (x, max(22, detection.y - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        color,
        2,
    )


def _draw_interface(
    frame,
    detections: list[ObjectDetection],
    target: ObjectDetection | None,
    machine: GraspStateMachine,
    pose: list[int],
    backend: str,
    fps: float,
    mirrored: bool,
    hand_detection: HandDetection | None,
    hand_blocked: bool,
) -> None:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = machine.grasp_zone
    if mirrored:
        zone_left, zone_right = int((1 - x2) * width), int((1 - x1) * width)
    else:
        zone_left, zone_right = int(x1 * width), int(x2 * width)
    zone_top, zone_bottom = int(y1 * height), int(y2 * height)
    zone_color = (70, 225, 130) if machine.state == GraspState.ARMED else (80, 185, 255)
    cv2.rectangle(frame, (zone_left, zone_top), (zone_right, zone_bottom), zone_color, 2)
    cv2.putText(
        frame,
        "PLACE OBJECT HERE",
        (zone_left + 8, zone_top + 26),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        zone_color,
        2,
    )

    for detection in detections:
        _draw_box(frame, detection, mirrored, False)
    if target is not None:
        _draw_box(frame, target, mirrored, True)
    if hand_detection is not None:
        HandTracker.draw(frame, hand_detection, mirrored=mirrored)

    panel_width = min(410, max(340, width // 3))
    panel_left = width - panel_width
    overlay = frame.copy()
    cv2.rectangle(overlay, (panel_left, 0), (width, height), (18, 22, 27), -1)
    cv2.addWeighted(overlay, 0.86, frame, 0.14, 0.0, frame)
    state_colors = {
        GraspState.DISARMED: (160, 170, 180),
        GraspState.ARMED: (80, 185, 255),
        GraspState.CLOSING: (80, 220, 255),
        GraspState.HOLDING: (70, 225, 130),
    }
    lines = [
        ("OBJECT GRASP", 0.72, (245, 245, 245)),
        (
            "HAND IN ZONE - BLOCKED" if hand_blocked else f"STATE: {machine.state.value}",
            0.55 if hand_blocked else 0.62,
            (70, 70, 255) if hand_blocked else state_colors[machine.state],
        ),
        (f"backend: {backend}", 0.43, (190, 198, 205)),
        (f"FPS {fps:.1f} | objects {len(detections)}", 0.43, (190, 198, 205)),
        (
            "target: none" if target is None else f"target: {target.label} {target.score:.2f}",
            0.50,
            (225, 230, 235),
        ),
        (f"stable: {machine.stable_count}/{machine.stable_frames}", 0.50, (225, 230, 235)),
        ("O6: " + " ".join(str(value) for value in pose), 0.43, (150, 220, 255)),
    ]
    y = 38
    for text, scale, color in lines:
        cv2.putText(frame, text, (panel_left + 20, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2 if scale >= 0.6 else 1)
        y += 34

    bar_width = panel_width - 40
    cv2.rectangle(frame, (panel_left + 20, y), (panel_left + 20 + bar_width, y + 12), (58, 65, 73), -1)
    cv2.rectangle(
        frame,
        (panel_left + 20, y),
        (panel_left + 20 + int(bar_width * machine.progress), y + 12),
        (80, 200, 145),
        -1,
    )
    y += 48
    instructions = [
        "G  ARM / DISARM",
        "O  OPEN & RESET",
        "E  EMERGENCY STOP",
        "Q  SAFE QUIT",
        "",
        "Object must stay inside",
        "the green zone before grasp.",
        "Hand in zone blocks closing.",
        "It never auto-releases.",
    ]
    for text in instructions:
        cv2.putText(frame, text, (panel_left + 20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (195, 202, 210), 1)
        y += 25


def run_object_grasp(args, project_dir: Path, config_path: Path, config: dict) -> int:
    grasp_config = config["object_grasp"]
    o6_config = config["o6"]
    control_config = config["control"]
    requested_dry_run = not args.real if (args.real or args.dry_run) else bool(o6_config.get("dry_run", True))

    capture = cv2.VideoCapture(args.camera)
    if not capture.isOpened():
        print(f"ERROR: cannot open camera index {args.camera}")
        return 2

    tracker: ObjectTracker | None = None
    hand_tracker: HandTracker | None = None
    controller: O6Controller | None = None
    exit_code = 0
    state_machine: GraspStateMachine | None = None
    current_pose = [int(value) for value in o6_config["safe_open_pose"]]
    safe_open = current_pose.copy()
    try:
        tracker = ObjectTracker(
            model_path=_resolve(grasp_config["model_path"], project_dir),
            score_threshold=grasp_config["score_threshold"],
            max_results=grasp_config["max_results"],
            denylist=grasp_config.get("category_denylist", ["person"]),
        )
        hand_tracker = HandTracker(
            model_path=_resolve(config["vision"]["model_path"], project_dir),
            detection_confidence=config["vision"]["detection_confidence"],
            presence_confidence=config["vision"]["presence_confidence"],
            tracking_confidence=config["vision"]["tracking_confidence"],
        )
        foreground = ForegroundDetector(
            pixel_threshold=grasp_config["foreground_pixel_threshold"],
            min_contour_area_ratio=grasp_config["foreground_min_area_ratio"],
            max_changed_area_ratio=grasp_config["foreground_max_changed_ratio"],
        )
        controller = O6Controller(o6_config, project_dir, requested_dry_run)
        controller.connect()
        controller.set_speed([int(value) for value in o6_config["speed"]])
        controller.send_safe_open(safe_open)

        zone = tuple(float(value) for value in grasp_config["grasp_zone"])
        state_machine = GraspStateMachine(
            grasp_zone=zone,
            min_area_ratio=grasp_config["min_box_area_ratio"],
            max_area_ratio=grasp_config["max_box_area_ratio"],
            stable_frames=grasp_config["stable_frames"],
            center_tolerance=grasp_config["center_tolerance"],
            auto_arm=grasp_config.get("auto_arm", False),
        )
        command_filter = CommandFilter(
            ema_alpha=control_config["ema_alpha"],
            deadband=control_config["deadband"],
            max_delta=control_config["max_delta_per_command"],
        )
        command_filter.reset(safe_open)
        grasp_pose = [int(value) for value in grasp_config["grasp_pose"]]
        command_period = 1.0 / float(control_config["command_hz"])
        detector_period = 1.0 / float(grasp_config["detector_hz"])
        mirror = bool(config["vision"].get("mirror_display", True))
        last_detection_time = 0.0
        last_command_time = 0.0
        start_time = time.monotonic()
        previous_time = start_time
        fps = 0.0
        detections: list[ObjectDetection] = []
        target: ObjectDetection | None = None
        hand_detection: HandDetection | None = None
        hand_blocked = False
        frame_count = 0
        command_count = 0
        failures = 0

        print("Object grasp controls: G=arm, O=open/reset, E=stop, Q=quit")
        while True:
            frame, failures = _read_frame(capture, failures)
            if frame is None:
                if failures >= 10:
                    print("ERROR: camera frame read failed 10 consecutive times")
                    exit_code = 3
                    break
                continue
            frame_count += 1
            now = time.monotonic()
            if now - last_detection_time >= detector_period:
                timestamp_ms = int((now - start_time) * 1000)
                detections = tracker.process(frame, timestamp_ms)
                hand_detection = hand_tracker.process(frame, timestamp_ms)
                if state_machine.state == GraspState.ARMED and not foreground.ready:
                    foreground.capture_background(frame)
                generic_target = foreground.detect(frame, zone) if state_machine.state == GraspState.ARMED else None
                target = generic_target
                if generic_target is not None:
                    generic_x, generic_y = generic_target.center_normalized
                    semantic = min(
                        detections,
                        key=lambda item: (
                            (item.center_normalized[0] - generic_x) ** 2
                            + (item.center_normalized[1] - generic_y) ** 2
                        ),
                        default=None,
                    )
                    if semantic is not None:
                        sx, sy = semantic.center_normalized
                        if ((sx - generic_x) ** 2 + (sy - generic_y) ** 2) ** 0.5 <= 0.15:
                            target = ObjectDetection(
                                label=semantic.label,
                                score=semantic.score,
                                x=generic_target.x,
                                y=generic_target.y,
                                width=generic_target.width,
                                height=generic_target.height,
                                frame_width=generic_target.frame_width,
                                frame_height=generic_target.frame_height,
                            )
                hand_blocked = False
                if hand_detection is not None:
                    x1, y1, x2, y2 = zone
                    hand_blocked = any(
                        x1 <= point[0] <= x2 and y1 <= point[1] <= y2
                        for point in hand_detection.image_landmarks
                    )
                state_machine.update(
                    None if hand_blocked or target is None else _observation(target)
                )
                if hand_blocked and state_machine.state == GraspState.CLOSING:
                    controller.emergency_stop()
                    print("EMERGENCY STOP: hand entered grasp zone during closing")
                last_detection_time = now

            if (
                state_machine.state == GraspState.CLOSING
                and not controller.emergency_stopped
                and now - last_command_time >= command_period
            ):
                current_pose = command_filter.apply(grasp_pose)
                controller.move(current_pose)
                command_count += 1
                last_command_time = now
                if max(abs(a - b) for a, b in zip(current_pose, grasp_pose)) <= max(1, int(control_config["deadband"])):
                    state_machine.mark_closed()

            elapsed = max(now - previous_time, 1e-6)
            instant_fps = 1.0 / elapsed
            fps = instant_fps if fps == 0 else 0.9 * fps + 0.1 * instant_fps
            previous_time = now

            if not args.headless:
                display = cv2.flip(frame, 1) if mirror else frame.copy()
                _draw_interface(
                    display,
                    detections,
                    target,
                    state_machine,
                    current_pose,
                    controller.backend,
                    fps,
                    mirror,
                    hand_detection,
                    hand_blocked,
                )
                cv2.imshow("LinkerHand O6 Object Grasp", display)
                key = cv2.waitKey(1) & 0xFF
            else:
                key = -1

            if key in (ord("q"), ord("Q")):
                break
            if key in (ord("g"), ord("G")):
                if state_machine.state == GraspState.ARMED:
                    state_machine.disarm()
                    foreground.clear()
                    print("Object grasp disarmed")
                elif state_machine.state == GraspState.DISARMED:
                    foreground.capture_background(frame)
                    state_machine.arm()
                    print("Object grasp armed; background captured, now insert the object")
                else:
                    print("Object is closing/held; press O to open and reset")
            elif key in (ord("o"), ord("O")):
                controller.send_safe_open(safe_open)
                command_filter.reset(safe_open)
                current_pose = safe_open.copy()
                state_machine.reset_after_open()
                foreground.clear()
                print("Safe open sent; object grasp reset and disarmed")
            elif key in (ord("e"), ord("E")):
                controller.emergency_stop()
            if args.max_frames and frame_count >= args.max_frames:
                break

        print(
            f"Object grasp summary: frames={frame_count}, commands={command_count}, "
            f"state={state_machine.state.value}, backend={controller.backend}"
        )
    except KeyboardInterrupt:
        print("Interrupted by user")
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        exit_code = 1
    finally:
        if controller is not None:
            if controller.connected and not controller.emergency_stopped:
                try:
                    controller.send_safe_open(safe_open)
                    time.sleep(0.15)
                except Exception as exc:
                    print(f"WARNING: safe-open during shutdown failed: {exc}")
            controller.close()
        if tracker is not None:
            tracker.close()
        if hand_tracker is not None:
            hand_tracker.close()
        capture.release()
        cv2.destroyAllWindows()
    return exit_code
