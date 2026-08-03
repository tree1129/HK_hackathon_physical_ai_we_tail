#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import logging
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Iterator


PROJECT_DIR = Path(__file__).resolve().parent
WEB_DIR = PROJECT_DIR / "web"
CHANNEL_NAMES = [
    "thumb_flexion",
    "thumb_abduction",
    "index_flexion",
    "middle_flexion",
    "ring_flexion",
    "pinky_flexion",
]
ALLOWED_ACTIONS = {
    "arm",
    "disarm",
    "open",
    "stop",
    "mode-hand",
    "mode-object",
    "follow-enable",
    "follow-pause",
    "hand-left",
    "hand-right",
}


def ensure_macos_pcan_loader() -> None:
    if sys.platform != "darwin" or os.environ.get("O6_MACCAN_READY") == "1":
        return
    library_dir = PROJECT_DIR / "third_party" / "maccan"
    if not (library_dir / "libPCBUSB.dylib").exists():
        return
    existing = os.environ.get("DYLD_LIBRARY_PATH", "")
    environment = os.environ.copy()
    environment["DYLD_LIBRARY_PATH"] = ":".join(
        [str(library_dir)] + ([existing] if existing else [])
    )
    environment["O6_MACCAN_READY"] = "1"
    os.execve(sys.executable, [sys.executable, *sys.argv], environment)


import cv2
import yaml
from flask import Flask, Response, jsonify, request, send_from_directory

from control.console_mode import ConsoleMode, ConsoleModeState, TrackingState
from control.filters import CommandFilter
from control.grasp_state import GraspState, GraspStateMachine, TargetObservation
from control.hand_mapper import CHANNEL_ORDER, HandMapper
from control.o6_controller import O6Controller
from vision.foreground_detector import ForegroundDetector
from vision.hand_tracker import HandDetection, HandTracker
from vision.object_detector import ObjectDetection, ObjectTracker


def _resolve(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def _observation(detection: ObjectDetection) -> TargetObservation:
    center_x, center_y = detection.center_normalized
    return TargetObservation(
        label=detection.label,
        score=detection.score,
        center_x=center_x,
        center_y=center_y,
        area_ratio=detection.area_ratio,
    )


def _select_target(
    generic: ObjectDetection | None,
    semantic_detections: list[ObjectDetection],
) -> ObjectDetection | None:
    if generic is None:
        return None
    generic_x, generic_y = generic.center_normalized
    semantic = min(
        semantic_detections,
        key=lambda item: (
            (item.center_normalized[0] - generic_x) ** 2
            + (item.center_normalized[1] - generic_y) ** 2
        ),
        default=None,
    )
    if semantic is None:
        return generic
    semantic_x, semantic_y = semantic.center_normalized
    if ((semantic_x - generic_x) ** 2 + (semantic_y - generic_y) ** 2) ** 0.5 > 0.15:
        return generic
    return ObjectDetection(
        label=semantic.label,
        score=semantic.score,
        x=generic.x,
        y=generic.y,
        width=generic.width,
        height=generic.height,
        frame_width=generic.frame_width,
        frame_height=generic.frame_height,
    )


def _hand_in_zone(
    detection: HandDetection | None,
    zone: tuple[float, float, float, float],
) -> bool:
    if detection is None:
        return False
    x1, y1, x2, y2 = zone
    return any(
        x1 <= point[0] <= x2 and y1 <= point[1] <= y2
        for point in detection.image_landmarks
    )


def _draw_box(frame, detection: ObjectDetection, mirrored: bool, selected: bool) -> None:
    frame_width = frame.shape[1]
    x = frame_width - detection.x - detection.width if mirrored else detection.x
    color = (69, 211, 124) if selected else (160, 166, 173)
    cv2.rectangle(
        frame,
        (x, detection.y),
        (x + detection.width, detection.y + detection.height),
        color,
        3 if selected else 1,
    )
    cv2.putText(
        frame,
        f"{detection.label} {detection.score:.2f}",
        (x, max(22, detection.y - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        color,
        2,
    )


def _annotate_frame(
    frame,
    detections: list[ObjectDetection],
    target: ObjectDetection | None,
    hand_detection: HandDetection | None,
    machine: GraspStateMachine,
    mode: ConsoleMode,
    mirrored: bool,
    hand_blocked: bool,
) -> None:
    if mode == ConsoleMode.OBJECT_GRASP:
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = machine.grasp_zone
        if mirrored:
            left, right = int((1 - x2) * width), int((1 - x1) * width)
        else:
            left, right = int(x1 * width), int(x2 * width)
        top, bottom = int(y1 * height), int(y2 * height)
        if hand_blocked:
            color = (63, 63, 232)
            label = "HAND BLOCKED"
        elif machine.state == GraspState.ARMED:
            color = (69, 211, 124)
            label = "GRASP ZONE / ARMED"
        else:
            color = (45, 177, 232)
            label = "GRASP ZONE"
        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        cv2.putText(
            frame,
            label,
            (left + 8, top + 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.54,
            color,
            2,
        )
        for detection in detections:
            _draw_box(frame, detection, mirrored, False)
        if target is not None:
            _draw_box(frame, target, mirrored, True)
    if hand_detection is not None:
        HandTracker.draw(frame, hand_detection, mirrored=mirrored)


class WebConsoleRuntime:
    def __init__(self, config: dict, camera: int, requested_dry_run: bool) -> None:
        self.config = config
        self.camera = int(camera)
        self.requested_dry_run = bool(requested_dry_run)
        safe_open = [int(value) for value in config["o6"]["safe_open_pose"]]
        self._status = {
            "ready": False,
            "camera_ok": False,
            "requested_mode": "dry-run" if requested_dry_run else "real",
            "dry_run": True,
            "connected": False,
            "backend": "starting",
            "fallback_reason": None,
            "mode": ConsoleMode.OBJECT_GRASP.value,
            "follow_enabled": False,
            "tracking_state": TrackingState.WAITING_HAND.value,
            "state": GraspState.DISARMED.value,
            "emergency_stopped": False,
            "target": None,
            "target_score": None,
            "objects": 0,
            "hand_detected": False,
            "hand_blocked": False,
            "handedness": None,
            "hand_score": None,
            "hand_type": config["o6"]["hand_type"],
            "stable_count": 0,
            "stable_frames": int(config["object_grasp"]["stable_frames"]),
            "pose": safe_open,
            "channels": CHANNEL_NAMES,
            "normalized": {name: 0.0 for name in CHANNEL_ORDER},
            "fps": 0.0,
            "commands": 0,
            "last_event": "正在初始化摄像头与视觉模型",
            "last_error": None,
        }
        self._status_lock = threading.Lock()
        self._frame_condition = threading.Condition()
        self._jpeg: bytes | None = None
        self._frame_sequence = 0
        self._actions: queue.Queue[str] = queue.Queue(maxsize=20)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="o6-camera-runtime", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._frame_condition:
            self._frame_condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def status_snapshot(self) -> dict:
        with self._status_lock:
            return copy.deepcopy(self._status)

    def enqueue_action(self, action: str) -> bool:
        if action not in ALLOWED_ACTIONS:
            return False
        try:
            self._actions.put_nowait(action)
            return True
        except queue.Full:
            return False

    def mjpeg_stream(self) -> Iterator[bytes]:
        sequence = -1
        while not self._stop_event.is_set():
            with self._frame_condition:
                self._frame_condition.wait_for(
                    lambda: self._frame_sequence != sequence or self._stop_event.is_set(),
                    timeout=1.0,
                )
                if self._stop_event.is_set():
                    return
                jpeg = self._jpeg
                sequence = self._frame_sequence
            if jpeg is not None:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"

    def _set_status(self, **values) -> None:
        with self._status_lock:
            self._status.update(values)

    def _publish_frame(self, frame) -> None:
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if not ok:
            return
        with self._frame_condition:
            self._jpeg = encoded.tobytes()
            self._frame_sequence += 1
            self._frame_condition.notify_all()

    def _apply_action(
        self,
        action: str,
        frame,
        mode_state: ConsoleModeState,
        machine: GraspStateMachine,
        foreground: ForegroundDetector,
        controller: O6Controller,
        hand_filter: CommandFilter,
        grasp_filter: CommandFilter,
        safe_open: list[int],
    ) -> list[int] | None:
        if action in ("hand-left", "hand-right"):
            hand_type = "left" if action == "hand-left" else "right"
            if controller.emergency_stopped:
                self._set_status(last_event="急停已锁定，重启运行器后才能切换设备")
                return None
            if controller.config["hand_type"] == hand_type:
                label = "左手" if hand_type == "left" else "右手"
                self._set_status(last_event=f"当前已经选择{label}")
                return None
            try:
                controller.send_safe_open(safe_open)
            except Exception as exc:
                print(f"WARNING: safe-open before hand switch failed: {exc}")
            mode_state.pause_follow()
            machine.reset_after_open()
            foreground.clear()
            hand_filter.reset(safe_open)
            grasp_filter.reset(safe_open)
            try:
                controller.reconnect_hand(hand_type)
                speed = [int(value) for value in self.config["o6"]["speed"]]
                controller.set_speed(speed)
                controller.send_safe_open(safe_open)
            except Exception as exc:
                controller.emergency_stop()
                self._set_status(
                    last_event=f"设备切换失败，已急停：{type(exc).__name__}: {exc}"
                )
                return None
            label = "左手" if hand_type == "left" else "右手"
            if controller.backend == "dry-run-fallback":
                event = f"已选择{label}，但真机无响应，已回退模拟"
            elif controller.dry_run:
                event = f"模拟模式已切换到{label}"
            else:
                event = f"已连接{label} O6，并发送安全张开"
            self._set_status(
                hand_type=hand_type,
                dry_run=controller.dry_run,
                connected=controller.connected,
                backend=controller.backend,
                fallback_reason=controller.fallback_reason,
                last_event=event,
            )
            return safe_open.copy()

        if action in ("mode-hand", "mode-object"):
            controller.send_safe_open(safe_open)
            hand_filter.reset(safe_open)
            grasp_filter.reset(safe_open)
            machine.reset_after_open()
            foreground.clear()
            mode = (
                ConsoleMode.HAND_FOLLOW
                if action == "mode-hand"
                else ConsoleMode.OBJECT_GRASP
            )
            mode_state.switch(mode)
            event = (
                "已切换到手势跟随；点击启用跟随后才会发送动作"
                if mode == ConsoleMode.HAND_FOLLOW
                else "已切换到物品抓取；当前未布防"
            )
            self._set_status(last_event=event)
            return safe_open.copy()

        if action == "follow-enable":
            if mode_state.mode != ConsoleMode.HAND_FOLLOW:
                self._set_status(last_event="请先切换到手势跟随模式")
            elif mode_state.enable_follow(controller.emergency_stopped):
                hand_filter.reset(safe_open)
                self._set_status(last_event="手势跟随已启用，等待识别人手")
            else:
                self._set_status(last_event="急停已锁定，无法启用手势跟随")
        elif action == "follow-pause":
            if mode_state.mode == ConsoleMode.HAND_FOLLOW:
                mode_state.pause_follow()
                self._set_status(last_event="手势跟随已暂停，保持最后姿态")
            else:
                self._set_status(last_event="当前不是手势跟随模式")
        elif action == "arm":
            if mode_state.mode != ConsoleMode.OBJECT_GRASP:
                self._set_status(last_event="请先切换到物品抓取模式")
                return None
            if controller.emergency_stopped:
                self._set_status(last_event="急停已锁定，请重启程序后再布防")
            elif machine.state == GraspState.DISARMED:
                foreground.capture_background(frame)
                machine.arm()
                self._set_status(last_event="已布防并记录背景，现在将物品放入绿色区域")
            else:
                self._set_status(last_event="当前状态不能布防，请先张开并复位")
        elif action == "disarm":
            if mode_state.mode != ConsoleMode.OBJECT_GRASP:
                self._set_status(last_event="当前不是物品抓取模式")
                return None
            if machine.state == GraspState.ARMED:
                machine.disarm()
                foreground.clear()
                self._set_status(last_event="已解除布防")
            else:
                self._set_status(last_event="只有等待识别时可以解除布防")
        elif action == "open":
            controller.send_safe_open(safe_open)
            hand_filter.reset(safe_open)
            grasp_filter.reset(safe_open)
            mode_state.pause_follow()
            machine.reset_after_open()
            foreground.clear()
            self._set_status(last_event="已发送安全张开并复位；急停锁定不会自动解除")
            return safe_open.copy()
        elif action == "stop":
            mode_state.pause_follow()
            controller.emergency_stop()
            self._set_status(last_event="急停已锁定，后续运动指令停止")
        return None

    def _run(self) -> None:
        capture = cv2.VideoCapture(self.camera)
        tracker: ObjectTracker | None = None
        hand_tracker: HandTracker | None = None
        controller: O6Controller | None = None
        machine: GraspStateMachine | None = None
        safe_open = [int(value) for value in self.config["o6"]["safe_open_pose"]]
        current_pose = safe_open.copy()
        try:
            if not capture.isOpened():
                raise RuntimeError(f"无法打开摄像头索引 {self.camera}")
            self._set_status(camera_ok=True)
            grasp_config = self.config["object_grasp"]
            vision_config = self.config["vision"]
            control_config = self.config["control"]
            tracker = ObjectTracker(
                model_path=_resolve(grasp_config["model_path"], PROJECT_DIR),
                score_threshold=grasp_config["score_threshold"],
                max_results=grasp_config["max_results"],
                denylist=grasp_config.get("category_denylist", ["person"]),
            )
            hand_tracker = HandTracker(
                model_path=_resolve(vision_config["model_path"], PROJECT_DIR),
                detection_confidence=vision_config["detection_confidence"],
                presence_confidence=vision_config["presence_confidence"],
                tracking_confidence=vision_config["tracking_confidence"],
            )
            foreground = ForegroundDetector(
                pixel_threshold=grasp_config["foreground_pixel_threshold"],
                min_contour_area_ratio=grasp_config["foreground_min_area_ratio"],
                max_changed_area_ratio=grasp_config["foreground_max_changed_ratio"],
            )
            controller = O6Controller(self.config["o6"], PROJECT_DIR, self.requested_dry_run)
            controller.connect()
            controller.set_speed([int(value) for value in self.config["o6"]["speed"]])
            controller.send_safe_open(safe_open)
            zone = tuple(float(value) for value in grasp_config["grasp_zone"])
            machine = GraspStateMachine(
                grasp_zone=zone,
                min_area_ratio=grasp_config["min_box_area_ratio"],
                max_area_ratio=grasp_config["max_box_area_ratio"],
                stable_frames=grasp_config["stable_frames"],
                center_tolerance=grasp_config["center_tolerance"],
                auto_arm=grasp_config.get("auto_arm", False),
            )
            machine.reset_after_open()
            mode_state = ConsoleModeState()
            hand_mapper = HandMapper(self.config["o6"]["channels"], self.config.get("calibration"))
            hand_filter = CommandFilter(
                ema_alpha=control_config["ema_alpha"],
                deadband=control_config["deadband"],
                max_delta=control_config["max_delta_per_command"],
            )
            grasp_filter = CommandFilter(
                ema_alpha=control_config["ema_alpha"],
                deadband=control_config["deadband"],
                max_delta=control_config["max_delta_per_command"],
            )
            hand_filter.reset(safe_open)
            grasp_filter.reset(safe_open)
            grasp_pose = [int(value) for value in grasp_config["grasp_pose"]]
            command_period = 1.0 / float(control_config["command_hz"])
            detector_period = 1.0 / float(grasp_config["detector_hz"])
            lost_timeout = float(control_config["lost_hand_timeout_ms"]) / 1000.0
            mirror = bool(vision_config.get("mirror_display", True))
            detections: list[ObjectDetection] = []
            target: ObjectDetection | None = None
            hand_detection: HandDetection | None = None
            hand_blocked = False
            normalized_sample = {name: 0.0 for name in CHANNEL_ORDER}
            preview_pose = safe_open.copy()
            hand_target_pose = safe_open.copy()
            command_count = 0
            last_object_detection_time = 0.0
            last_command_time = 0.0
            start_time = time.monotonic()
            previous_time = start_time
            fps = 0.0
            failures = 0
            self._set_status(
                ready=True,
                dry_run=controller.dry_run,
                connected=controller.connected,
                backend=controller.backend,
                fallback_reason=controller.fallback_reason,
                mode=mode_state.mode.value,
                follow_enabled=mode_state.follow_enabled,
                tracking_state=mode_state.tracking_state.value,
                state=machine.state.value,
                last_event=(
                    "控制台就绪：模拟模式不会连接真机"
                    if controller.dry_run
                    else "控制台就绪：已连接 O6 真机"
                ),
            )

            while not self._stop_event.is_set():
                ok, frame = capture.read()
                if not ok:
                    failures += 1
                    if failures >= 10:
                        raise RuntimeError("摄像头连续 10 帧读取失败")
                    time.sleep(0.05)
                    continue
                failures = 0
                now = time.monotonic()

                while True:
                    try:
                        action = self._actions.get_nowait()
                    except queue.Empty:
                        break
                    changed_pose = self._apply_action(
                        action,
                        frame,
                        mode_state,
                        machine,
                        foreground,
                        controller,
                        hand_filter,
                        grasp_filter,
                        safe_open,
                    )
                    if changed_pose is not None:
                        current_pose = changed_pose
                        preview_pose = changed_pose.copy()

                timestamp_ms = int((now - start_time) * 1000)
                hand_detection = hand_tracker.process(frame, timestamp_ms)

                if mode_state.mode == ConsoleMode.HAND_FOLLOW:
                    detections = []
                    target = None
                    hand_blocked = False
                    if hand_detection is not None:
                        hand_target_pose, raw_sample = hand_mapper.map_landmarks(
                            hand_detection.geometry_landmarks
                        )
                        normalized_sample = hand_mapper.apply_calibration(raw_sample)
                        if not mode_state.follow_enabled:
                            preview_pose = hand_target_pose.copy()
                    mode_state.observe_hand(
                        detected=hand_detection is not None,
                        now=now,
                        lost_timeout=lost_timeout,
                    )
                    if (
                        mode_state.can_send_hand(now, lost_timeout)
                        and not controller.emergency_stopped
                        and now - last_command_time >= command_period
                    ):
                        try:
                            current_pose = hand_filter.apply(hand_target_pose)
                            controller.move(current_pose)
                            command_count += 1
                            last_command_time = now
                        except Exception as exc:
                            controller.emergency_stop()
                            self._set_status(
                                last_event=f"手势指令失败，已急停：{type(exc).__name__}: {exc}"
                            )
                else:
                    hand_blocked = _hand_in_zone(hand_detection, zone)
                    if hand_blocked and machine.state == GraspState.CLOSING:
                        controller.emergency_stop()
                        self._set_status(last_event="检测到手进入抓取区域，已触发急停")
                    if now - last_object_detection_time >= detector_period:
                        detections = tracker.process(frame, timestamp_ms)
                        if machine.state == GraspState.ARMED and not foreground.ready:
                            foreground.capture_background(frame)
                        generic = (
                            foreground.detect(frame, zone)
                            if machine.state == GraspState.ARMED
                            else None
                        )
                        target = _select_target(generic, detections)
                        machine.update(
                            None if hand_blocked or target is None else _observation(target)
                        )
                        last_object_detection_time = now

                    if (
                        machine.state == GraspState.CLOSING
                        and not controller.emergency_stopped
                        and now - last_command_time >= command_period
                    ):
                        try:
                            current_pose = grasp_filter.apply(grasp_pose)
                            controller.move(current_pose)
                            command_count += 1
                            last_command_time = now
                            if max(
                                abs(a - b) for a, b in zip(current_pose, grasp_pose)
                            ) <= max(1, int(control_config["deadband"])):
                                machine.mark_closed()
                                self._set_status(last_event="目标已稳定抓取，保持当前姿态")
                        except Exception as exc:
                            controller.emergency_stop()
                            self._set_status(
                                last_event=f"抓取指令失败，已急停：{type(exc).__name__}: {exc}"
                            )

                elapsed = max(now - previous_time, 1e-6)
                instant_fps = 1.0 / elapsed
                fps = instant_fps if fps == 0 else 0.9 * fps + 0.1 * instant_fps
                previous_time = now
                display = cv2.flip(frame, 1) if mirror else frame.copy()
                _annotate_frame(
                    display,
                    detections,
                    target,
                    hand_detection,
                    machine,
                    mode_state.mode,
                    mirror,
                    hand_blocked,
                )
                self._publish_frame(display)
                hand_mode = mode_state.mode == ConsoleMode.HAND_FOLLOW
                display_pose = (
                    preview_pose
                    if hand_mode and not mode_state.follow_enabled
                    else current_pose
                )
                self._set_status(
                    ready=True,
                    camera_ok=True,
                    dry_run=controller.dry_run,
                    connected=controller.connected,
                    backend=controller.backend,
                    fallback_reason=controller.fallback_reason,
                    mode=mode_state.mode.value,
                    follow_enabled=mode_state.follow_enabled,
                    tracking_state=mode_state.tracking_state.value,
                    state=(
                        mode_state.tracking_state.value if hand_mode else machine.state.value
                    ),
                    emergency_stopped=controller.emergency_stopped,
                    target=(target.label if not hand_mode and target is not None else None),
                    target_score=(
                        round(target.score, 3)
                        if not hand_mode and target is not None
                        else None
                    ),
                    objects=0 if hand_mode else len(detections),
                    hand_detected=hand_detection is not None,
                    hand_blocked=False if hand_mode else hand_blocked,
                    handedness=(
                        hand_detection.handedness if hand_detection is not None else None
                    ),
                    hand_score=(
                        round(hand_detection.score, 3)
                        if hand_detection is not None
                        else None
                    ),
                    hand_type=controller.config["hand_type"],
                    stable_count=(
                        (1 if hand_detection is not None else 0)
                        if hand_mode
                        else machine.stable_count
                    ),
                    stable_frames=1 if hand_mode else machine.stable_frames,
                    pose=display_pose.copy(),
                    normalized=normalized_sample.copy(),
                    fps=round(fps, 1),
                    commands=command_count,
                )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            print(f"ERROR: web console runtime failed: {message}")
            self._set_status(ready=False, last_error=message, last_event="运行层发生错误，已停止下发")
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
            self._set_status(camera_ok=False, connected=False)
            with self._frame_condition:
                self._frame_condition.notify_all()


def create_app(runtime) -> Flask:
    app = Flask(__name__, static_folder=None)

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    @app.get("/assets/<path:filename>")
    def assets(filename: str):
        return send_from_directory(WEB_DIR, filename)

    @app.get("/api/status")
    def status():
        response = jsonify(runtime.status_snapshot())
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/action")
    def action():
        body = request.get_json(silent=True) or {}
        requested_action = body.get("action")
        accepted = isinstance(requested_action, str) and runtime.enqueue_action(requested_action)
        if not accepted:
            return jsonify({"accepted": False, "error": "invalid or busy action"}), 400
        return jsonify({"accepted": True, "action": requested_action}), 202

    @app.get("/video_feed")
    def video_feed():
        return Response(
            runtime.mjpeg_stream(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store"},
        )

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LinkerHand O6 local visual control console")
    parser.add_argument("--camera", type=int, default=0, help="OpenCV camera index")
    parser.add_argument("--config", default="config.yaml", help="YAML configuration path")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="never connect to hardware")
    mode.add_argument("--real", action="store_true", help="request a real O6 connection")
    return parser.parse_args()


def main() -> int:
    ensure_macos_pcan_loader()
    args = parse_args()
    config_path = _resolve(args.config, PROJECT_DIR)
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    requested_dry_run = not args.real if (args.real or args.dry_run) else bool(config["o6"].get("dry_run", True))
    runtime = WebConsoleRuntime(config, args.camera, requested_dry_run)
    app = create_app(runtime)
    runtime.start()
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    print(f"O6 visual console: http://{args.host}:{args.port}")
    print("Press Ctrl-C to stop; shutdown sends safe-open when real hardware is connected.")
    try:
        app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)
    finally:
        runtime.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
