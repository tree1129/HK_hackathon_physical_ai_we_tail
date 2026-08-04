#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def ensure_macos_pcan_loader() -> None:
    """Re-exec once so dyld can resolve the bundled MacCAN library by name."""
    if sys.platform != "darwin" or os.environ.get("O6_MACCAN_READY") == "1":
        return
    library_dir = Path(__file__).resolve().parent / "third_party" / "maccan"
    if not (library_dir / "libPCBUSB.dylib").exists():
        return
    existing = os.environ.get("DYLD_LIBRARY_PATH", "")
    paths = [str(library_dir)] + ([existing] if existing else [])
    environment = os.environ.copy()
    environment["DYLD_LIBRARY_PATH"] = ":".join(paths)
    environment["O6_MACCAN_READY"] = "1"
    os.execve(sys.executable, [sys.executable, *sys.argv], environment)


ensure_macos_pcan_loader()

import cv2
import yaml

from control.filters import CommandFilter
from control.hand_mapper import CHANNEL_ORDER, HandMapper
from control.o6_controller import O6Controller
from vision.hand_tracker import HandDetection, HandTracker

PROJECT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Webcam-to-LinkerHand O6 teleoperation")
    parser.add_argument("--camera", type=int, default=0, help="OpenCV camera index")
    parser.add_argument("--config", default="config.yaml", help="YAML configuration path")
    parser.add_argument(
        "--mode",
        choices=("hand", "object-grasp"),
        default="hand",
        help="hand mirroring or object-triggered grasp",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="never connect to hardware")
    mode.add_argument("--real", action="store_true", help="request a real O6 connection")
    parser.add_argument("--headless", action="store_true", help="run without an OpenCV window")
    parser.add_argument("--max-frames", type=int, default=0, help="stop after N frames; 0 is unlimited")
    return parser.parse_args()


def resolve_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    for section in ("o6", "vision", "control", "calibration"):
        if section not in config:
            raise ValueError(f"config is missing section: {section}")
    return config


def save_calibration(path: Path, config: dict, mapper: HandMapper) -> None:
    config["calibration"] = mapper.calibration_data()
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)
    print(f"Calibration saved: {path}")


def put_lines(frame, lines: list[str]) -> None:
    y = 28
    for line in lines:
        cv2.putText(frame, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (15, 15, 15), 4)
        cv2.putText(frame, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (240, 245, 245), 1)
        y += 24


def draw_control_panel(
    frame,
    normalized: dict[str, float],
    pose: list[int],
    status: str,
    backend: str,
    calibrated: bool,
) -> None:
    height, width = frame.shape[:2]
    panel_width = min(420, max(330, width // 3))
    left = width - panel_width
    overlay = frame.copy()
    cv2.rectangle(overlay, (left, 0), (width, height), (18, 22, 27), -1)
    cv2.addWeighted(overlay, 0.86, frame, 0.14, 0.0, frame)

    cv2.putText(frame, "O6 CAMERA TELEOP", (left + 20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (245, 245, 245), 2)
    status_color = (95, 225, 130) if status.startswith("TRACKING") else (80, 185, 255)
    if "EMERGENCY" in status:
        status_color = (70, 70, 255)
    cv2.putText(frame, status, (left + 20, 66), cv2.FONT_HERSHEY_SIMPLEX, 0.54, status_color, 2)
    cv2.putText(
        frame,
        f"backend: {backend} | calibration: {'yes' if calibrated else 'default'}",
        (left + 20, 91),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.40,
        (190, 198, 205),
        1,
    )

    labels = ["THUMB FLEX", "THUMB ABD", "INDEX FLEX", "MIDDLE FLEX", "RING FLEX", "PINKY FLEX"]
    y = 126
    bar_width = panel_width - 40
    for name, label, output in zip(CHANNEL_ORDER, labels, pose):
        value = float(normalized.get(name, 0.0))
        cv2.putText(frame, label, (left + 20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (230, 234, 238), 1)
        mapping_text = f"human {value:0.2f}  ->  O6 {output:3d}"
        text_width = cv2.getTextSize(mapping_text, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)[0][0]
        cv2.putText(
            frame,
            mapping_text,
            (width - 20 - text_width, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (150, 220, 255),
            1,
        )
        bar_y = y + 10
        cv2.rectangle(frame, (left + 20, bar_y), (left + 20 + bar_width, bar_y + 10), (58, 65, 73), -1)
        fill = int(bar_width * max(0.0, min(1.0, value)))
        cv2.rectangle(frame, (left + 20, bar_y), (left + 20 + fill, bar_y + 10), (80, 200, 145), -1)
        y += 58

    help_y = min(height - 46, y + 8)
    cv2.putText(frame, "1 OPEN  2 FIST  S SAVE  R RESET", (left + 20, help_y), cv2.FONT_HERSHEY_SIMPLEX, 0.39, (190, 198, 205), 1)
    cv2.putText(frame, "E STOP  O SAFE OPEN  Q QUIT", (left + 20, help_y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.39, (190, 198, 205), 1)


def key_action(
    key: int,
    raw_sample: dict[str, float] | None,
    mapper: HandMapper,
    controller: O6Controller,
    safe_open: list[int],
    config_path: Path,
    config: dict,
) -> bool:
    if key in (ord("q"), ord("Q")):
        return False
    if key == ord("1"):
        if raw_sample is None:
            print("Calibration open ignored: no hand detected")
        else:
            mapper.record_open(raw_sample)
            print("Calibration: current hand recorded as fully open")
    elif key == ord("2"):
        if raw_sample is None:
            print("Calibration fist ignored: no hand detected")
        else:
            mapper.record_closed(raw_sample)
            print("Calibration: current hand recorded as a fist")
    elif key in (ord("s"), ord("S")):
        save_calibration(config_path, config, mapper)
    elif key in (ord("r"), ord("R")):
        mapper.reset_calibration()
        print("Calibration reset to geometry defaults (press S to persist)")
    elif key in (ord("e"), ord("E")):
        controller.emergency_stop()
    elif key in (ord("o"), ord("O")):
        controller.send_safe_open(safe_open)
        print("Safe open pose sent; emergency latch remains active if previously set")
    return True


def run(args: argparse.Namespace) -> int:
    config_path = resolve_path(args.config, Path.cwd())
    config = load_config(config_path)
    if args.mode == "object-grasp":
        from object_grasp import run_object_grasp

        return run_object_grasp(args, PROJECT_DIR, config_path, config)
    o6_config = config["o6"]
    control_config = config["control"]
    vision_config = config["vision"]

    requested_dry_run = True
    if args.real:
        requested_dry_run = False
    elif args.dry_run:
        requested_dry_run = True
    else:
        requested_dry_run = bool(o6_config.get("dry_run", True))

    capture = cv2.VideoCapture(args.camera)
    if not capture.isOpened():
        print(f"ERROR: cannot open camera index {args.camera}")
        print("On macOS, allow camera access for Terminal/Codex in System Settings > Privacy & Security > Camera.")
        return 2

    tracker: HandTracker | None = None
    controller: O6Controller | None = None
    exit_code = 0
    safe_open = [int(value) for value in o6_config["safe_open_pose"]]
    try:
        model_path = resolve_path(vision_config["model_path"], PROJECT_DIR)
        tracker = HandTracker(
            model_path=model_path,
            detection_confidence=vision_config["detection_confidence"],
            presence_confidence=vision_config["presence_confidence"],
            tracking_confidence=vision_config["tracking_confidence"],
        )
        controller = O6Controller(o6_config, PROJECT_DIR, requested_dry_run)
        controller.connect()
        controller.set_speed([int(value) for value in o6_config["speed"]])

        mapper = HandMapper(o6_config["channels"], config.get("calibration"))
        command_filter = CommandFilter(
            ema_alpha=control_config["ema_alpha"],
            deadband=control_config["deadband"],
            max_delta=control_config["max_delta_per_command"],
        )
        command_filter.reset(safe_open)

        command_period = 1.0 / float(control_config["command_hz"])
        lost_timeout = float(control_config["lost_hand_timeout_ms"]) / 1000.0
        mirror = bool(vision_config.get("mirror_display", True))
        start_time = time.monotonic()
        previous_frame_time = start_time
        last_detection_time: float | None = None
        last_send_time = 0.0
        last_pose = safe_open.copy()
        raw_sample: dict[str, float] | None = None
        normalized_sample = {name: 0.0 for name in CHANNEL_ORDER}
        detection: HandDetection | None = None
        fps = 0.0
        frame_count = 0
        detected_frame_count = 0
        command_count = 0
        consecutive_read_failures = 0

        print("Controls: 1=open sample, 2=fist sample, S=save, R=reset, E=stop, O=open, Q=quit")
        while True:
            ok, raw_frame = capture.read()
            if not ok:
                consecutive_read_failures += 1
                if consecutive_read_failures >= 10:
                    print("ERROR: camera frame read failed 10 consecutive times")
                    exit_code = 3
                    break
                time.sleep(0.05)
                continue
            consecutive_read_failures = 0
            now = time.monotonic()
            frame_count += 1
            timestamp_ms = int((now - start_time) * 1000)
            detection = tracker.process(raw_frame, timestamp_ms)

            if detection is not None:
                detected_frame_count += 1
                last_detection_time = now
                mapped_pose, raw_sample = mapper.map_landmarks(detection.geometry_landmarks)
                normalized_sample = mapper.apply_calibration(raw_sample)
                last_pose = command_filter.apply(mapped_pose)
            else:
                raw_sample = None

            hand_age = float("inf") if last_detection_time is None else now - last_detection_time
            send_allowed = hand_age <= lost_timeout and not controller.emergency_stopped
            if send_allowed and now - last_send_time >= command_period:
                try:
                    controller.move(last_pose)
                    last_send_time = now
                    command_count += 1
                except Exception as exc:
                    print(f"ERROR: O6 command failed; output stopped: {type(exc).__name__}: {exc}")
                    controller.emergency_stop()
                    exit_code = 4

            elapsed = max(now - previous_frame_time, 1e-6)
            instant_fps = 1.0 / elapsed
            fps = instant_fps if fps == 0.0 else 0.9 * fps + 0.1 * instant_fps
            previous_frame_time = now

            if not args.headless:
                display = cv2.flip(raw_frame, 1) if mirror else raw_frame.copy()
                if detection is not None:
                    tracker.draw(display, detection, mirrored=mirror)
                if controller.emergency_stopped:
                    status = "EMERGENCY STOP"
                elif detection is not None:
                    status = f"TRACKING {detection.handedness} {detection.score:.2f}"
                elif hand_age <= lost_timeout:
                    status = "HAND LOST - HOLDING"
                else:
                    status = "HAND LOST - OUTPUT PAUSED"
                put_lines(display, [f"FPS {fps:4.1f}"])
                draw_control_panel(
                    display,
                    normalized_sample,
                    last_pose,
                    status,
                    controller.backend,
                    mapper.open_sample is not None and mapper.closed_sample is not None,
                )
                cv2.imshow("LinkerHand O6 Camera Teleop", display)
                key = cv2.waitKey(1) & 0xFF
            else:
                key = -1

            if key != -1 and not key_action(
                key, raw_sample, mapper, controller, safe_open, config_path, config
            ):
                break
            if args.max_frames and frame_count >= args.max_frames:
                break
        print(
            f"Session summary: frames={frame_count}, detected={detected_frame_count}, "
            f"commands={command_count}, backend={controller.backend}"
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
        capture.release()
        cv2.destroyAllWindows()
    return exit_code


if __name__ == "__main__":
    sys.exit(run(parse_args()))
