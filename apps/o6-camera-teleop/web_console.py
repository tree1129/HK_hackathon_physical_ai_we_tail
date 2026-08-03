#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import logging
import os
import queue
import secrets
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
    "source-mac-camera",
    "source-iphone-lidar",
    "depth-calibrate-contact",
    "depth-clear-calibration",
}

DEPTH_CONFIDENCE = {"low": 0, "medium": 1, "high": 2}


def confidence_value(name: str) -> int:
    try:
        return DEPTH_CONFIDENCE[name]
    except (KeyError, TypeError):
        raise ValueError(f"unknown depth confidence: {name!r}") from None


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

from config_store import save_contact_depth
from control.console_mode import ConsoleMode, ConsoleModeState, TrackingState, VisionSource
from control.depth_grasp import DepthGraspGate, DepthPhase
from control.filters import CommandFilter
from control.grasp_state import GraspState, GraspStateMachine, TargetObservation
from control.hand_mapper import CHANNEL_ORDER, HandMapper
from control.o6_controller import O6Controller
from vision.depth_geometry import ContactCalibrator, DepthMeasurement, measure_depth
from vision.depth_receiver import DepthReceiver
from vision.frame_source import FrameSourceManager
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


def _best_target_in_zone(
    detections: list[ObjectDetection],
    zone: tuple[float, float, float, float],
    min_area: float,
    max_area: float,
) -> ObjectDetection | None:
    x1, y1, x2, y2 = zone
    eligible = [
        detection
        for detection in detections
        if x1 <= detection.center_normalized[0] <= x2
        and y1 <= detection.center_normalized[1] <= y2
        and min_area <= detection.area_ratio <= max_area
    ]
    return max(eligible, key=lambda detection: detection.score, default=None)


class _UnavailableDepthReceiver:
    def latest(self, now: float):
        return None


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


def _depth_colormap(depth_mm, roi=None):
    valid = depth_mm > 0
    scaled = cv2.normalize(
        depth_mm,
        None,
        0,
        255,
        cv2.NORM_MINMAX,
        dtype=cv2.CV_8U,
        mask=valid.astype("uint8"),
    )
    image = cv2.applyColorMap(255 - scaled, cv2.COLORMAP_TURBO)
    image[~valid] = 0
    if roi is not None:
        x1, y1, x2, y2 = roi
        cv2.rectangle(image, (x1, y1), (x2, y2), (255, 255, 255), 2)
    return image


class WebConsoleRuntime:
    def __init__(
        self,
        config: dict,
        camera: int,
        requested_dry_run: bool,
        config_path: Path | None = None,
    ) -> None:
        self.config = config
        self.config_path = (config_path or (PROJECT_DIR / "config.yaml")).resolve()
        self.camera = int(camera)
        self.requested_dry_run = bool(requested_dry_run)
        lidar_config = config.get("iphone_lidar", {})
        self.pairing_code = f"{secrets.randbelow(1_000_000):06d}"
        self.depth_receiver: DepthReceiver | None = None
        if lidar_config.get("enabled", True):
            self.depth_receiver = DepthReceiver(
                self.pairing_code,
                host=str(lidar_config.get("bind_host", "0.0.0.0")),
                port=int(lidar_config.get("port", 8766)),
                timeout_seconds=float(lidar_config.get("stream_timeout_ms", 500)) / 1000.0,
                max_message_bytes=int(lidar_config.get("max_message_bytes", 1_572_864)),
                max_fps=float(lidar_config.get("max_fps", 20)),
                service_name=str(lidar_config.get("service_name", "_o6depth._tcp")),
            )
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
            "vision_source": VisionSource.MAC_CAMERA.value,
            "pairing_code": self.pairing_code,
            "iphone_receiver_running": False,
            "iphone_connected": False,
            "iphone_device": None,
            "bonjour_state": "stopped",
            "bonjour_error": None,
            "depth_fps": 0.0,
            "depth_latency_ms": None,
            "depth_stream_age_ms": None,
            "depth_valid_ratio": 0.0,
            "depth_calibrated": lidar_config.get("contact_depth_mm") is not None,
            "depth_calibrating": False,
            "contact_depth_mm": lidar_config.get("contact_depth_mm"),
            "target_depth_mm": None,
            "signed_distance_mm": None,
            "depth_phase": DepthPhase.DEPTH_UNAVAILABLE.value,
            "depth_stable_count": 0,
            "depth_required_frames": int(lidar_config.get("contact_stable_frames", 8)),
        }
        self._status_lock = threading.Lock()
        self._frame_condition = threading.Condition()
        self._depth_condition = threading.Condition()
        self._jpeg: bytes | None = None
        self._depth_jpeg: bytes | None = None
        self._frame_sequence = 0
        self._depth_frame_sequence = 0
        self._actions: queue.Queue[str] = queue.Queue(maxsize=20)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._calibrating = False
        self._latest_target_depth_mm: float | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        if self.depth_receiver is not None:
            try:
                self.depth_receiver.start()
            except Exception as exc:
                self._set_status(
                    last_error=f"iPhone depth receiver failed: {type(exc).__name__}: {exc}",
                    last_event="iPhone 深度接收服务启动失败，Mac 摄像头仍可使用",
                )
        self._thread = threading.Thread(target=self._run, name="o6-camera-runtime", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._frame_condition:
            self._frame_condition.notify_all()
        with self._depth_condition:
            self._depth_condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        if self.depth_receiver is not None:
            try:
                self.depth_receiver.stop()
            except Exception as exc:
                self._set_status(last_error=f"iPhone depth receiver stop failed: {exc}")

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

    def depth_mjpeg_stream(self) -> Iterator[bytes]:
        sequence = -1
        while not self._stop_event.is_set():
            with self._depth_condition:
                self._depth_condition.wait_for(
                    lambda: self._depth_frame_sequence != sequence
                    or self._stop_event.is_set(),
                    timeout=1.0,
                )
                if self._stop_event.is_set():
                    return
                jpeg = self._depth_jpeg
                sequence = self._depth_frame_sequence
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

    def _publish_depth_frame(self, frame) -> None:
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if not ok:
            return
        with self._depth_condition:
            self._depth_jpeg = encoded.tobytes()
            self._depth_frame_sequence += 1
            self._depth_condition.notify_all()

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
        depth_gate: DepthGraspGate,
        calibrator: ContactCalibrator,
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
            depth_gate.reset()
            calibrator.reset()
            self._calibrating = False
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

        if action in ("source-mac-camera", "source-iphone-lidar"):
            source = (
                VisionSource.MAC_CAMERA
                if action == "source-mac-camera"
                else VisionSource.IPHONE_LIDAR
            )
            controller.move(safe_open)
            hand_filter.reset(safe_open)
            grasp_filter.reset(safe_open)
            machine.reset_after_open()
            depth_gate.reset()
            calibrator.reset()
            self._calibrating = False
            self._latest_target_depth_mm = None
            foreground.clear()
            mode_state.switch_source(source)
            label = "Mac 摄像头" if source == VisionSource.MAC_CAMERA else "iPhone LiDAR"
            self._set_status(
                vision_source=source.value,
                depth_calibrating=False,
                depth_phase=DepthPhase.DEPTH_UNAVAILABLE.value,
                depth_stable_count=0,
                target_depth_mm=None,
                signed_distance_mm=None,
                last_event=f"已切换到{label}，当前未布防",
            )
            return safe_open.copy()

        if action == "depth-calibrate-contact":
            if mode_state.vision_source != VisionSource.IPHONE_LIDAR:
                self._set_status(last_event="请先切换到 iPhone LiDAR")
            elif self._latest_target_depth_mm is None:
                self._set_status(last_event="目标深度无效，无法记录 0 cm")
            elif machine.state != GraspState.DISARMED:
                self._set_status(last_event="请先解除布防再标定 0 cm")
            else:
                calibrator.reset()
                self._calibrating = True
                self._set_status(depth_calibrating=True, last_event="正在采集 0 cm 接触面")
            return None

        if action == "depth-clear-calibration":
            try:
                save_contact_depth(self.config_path, None)
                self.config["iphone_lidar"]["contact_depth_mm"] = None
                depth_gate.reset()
                calibrator.reset()
                self._calibrating = False
                machine.disarm()
                self._set_status(
                    depth_calibrated=False,
                    depth_calibrating=False,
                    contact_depth_mm=None,
                    signed_distance_mm=None,
                    depth_phase=DepthPhase.DEPTH_UNAVAILABLE.value,
                    last_event="已清除 0 cm 标定，自动抓取保持未布防",
                )
            except Exception as exc:
                self._set_status(last_event=f"清除标定失败：{type(exc).__name__}: {exc}")
            return None

        if action in ("mode-hand", "mode-object"):
            controller.move(safe_open)
            hand_filter.reset(safe_open)
            grasp_filter.reset(safe_open)
            machine.reset_after_open()
            depth_gate.reset()
            calibrator.reset()
            self._calibrating = False
            foreground.clear()
            mode = (
                ConsoleMode.HAND_FOLLOW
                if action == "mode-hand"
                else ConsoleMode.OBJECT_GRASP
            )
            mode_state.switch(mode)
            if mode == ConsoleMode.HAND_FOLLOW:
                mode_state.switch_source(VisionSource.MAC_CAMERA)
            event = (
                "已切换到手势跟随；点击启用跟随后才会发送动作"
                if mode == ConsoleMode.HAND_FOLLOW
                else "已切换到物品抓取；当前未布防"
            )
            self._set_status(last_event=event, vision_source=mode_state.vision_source.value)
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
            elif (
                mode_state.vision_source == VisionSource.IPHONE_LIDAR
                and (
                    self.depth_receiver is None
                    or not self.depth_receiver.status().connected
                    or self.config["iphone_lidar"].get("contact_depth_mm") is None
                )
            ):
                self._set_status(last_event="iPhone 未连接或 0 cm 未标定，不能布防")
            elif machine.state == GraspState.DISARMED:
                if frame is not None:
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
                depth_gate.reset()
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
            depth_gate.reset()
            calibrator.reset()
            self._calibrating = False
            foreground.clear()
            self._set_status(last_event="已发送安全张开并复位；急停锁定不会自动解除")
            return safe_open.copy()
        elif action == "stop":
            mode_state.pause_follow()
            controller.emergency_stop()
            self._set_status(last_event="急停已锁定，后续运动指令停止")
        return None

    def _run(self) -> None:
        frame_sources = FrameSourceManager(
            self.camera,
            self.depth_receiver or _UnavailableDepthReceiver(),
        )
        tracker: ObjectTracker | None = None
        hand_tracker: HandTracker | None = None
        controller: O6Controller | None = None
        machine: GraspStateMachine | None = None
        safe_open = [int(value) for value in self.config["o6"]["safe_open_pose"]]
        current_pose = safe_open.copy()
        try:
            grasp_config = self.config["object_grasp"]
            vision_config = self.config["vision"]
            control_config = self.config["control"]
            lidar_config = self.config["iphone_lidar"]
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
            depth_gate = DepthGraspGate(
                open_threshold_mm=lidar_config["open_threshold_mm"],
                contact_threshold_mm=lidar_config["contact_threshold_mm"],
                stable_frames=int(lidar_config["contact_stable_frames"]),
            )
            calibrator = ContactCalibrator(required_samples=15)
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
            last_frame = None
            last_depth_sequence = -1
            previous_depth_time: float | None = None
            depth_fps = 0.0
            measurement = DepthMeasurement(None, None, 0.0, (0, 0, 0, 0))
            decision = depth_gate.update(None, armed=False, hand_blocked=False)
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
                now = time.monotonic()
                receiver_status = (
                    self.depth_receiver.status(now) if self.depth_receiver is not None else None
                )
                if receiver_status is not None:
                    stream_fresh = (
                        receiver_status.connected
                        and receiver_status.last_frame_age_ms is not None
                        and receiver_status.last_frame_age_ms
                        <= float(lidar_config["stream_timeout_ms"])
                    )
                    self._set_status(
                        iphone_receiver_running=receiver_status.running,
                        iphone_connected=stream_fresh,
                        iphone_device=receiver_status.connected_device,
                        depth_latency_ms=receiver_status.depth_latency_ms,
                        depth_stream_age_ms=receiver_status.last_frame_age_ms,
                        bonjour_state=receiver_status.bonjour_state,
                        bonjour_error=receiver_status.bonjour_error,
                    )

                while True:
                    try:
                        action = self._actions.get_nowait()
                    except queue.Empty:
                        break
                    changed_pose = self._apply_action(
                        action,
                        last_frame,
                        mode_state,
                        machine,
                        foreground,
                        controller,
                        hand_filter,
                        grasp_filter,
                        depth_gate,
                        calibrator,
                        safe_open,
                    )
                    if changed_pose is not None:
                        current_pose = changed_pose
                        preview_pose = changed_pose.copy()

                sample = frame_sources.read(mode_state.vision_source, now)
                if sample is None:
                    failures += 1
                    self._latest_target_depth_mm = None
                    if mode_state.vision_source == VisionSource.IPHONE_LIDAR:
                        depth_gate.reset()
                        if machine.state == GraspState.ARMED:
                            machine.disarm()
                            foreground.clear()
                            self._set_status(last_event="iPhone 深度流已过期，自动解除布防")
                        self._set_status(
                            camera_ok=False,
                            depth_phase=DepthPhase.DEPTH_UNAVAILABLE.value,
                            depth_stable_count=0,
                            target_depth_mm=None,
                            signed_distance_mm=None,
                        )
                    else:
                        self._set_status(camera_ok=False)
                        if failures == 10:
                            self._set_status(last_event="Mac 摄像头连续读取失败，可切换到 iPhone LiDAR")
                    time.sleep(0.02 if mode_state.vision_source == VisionSource.IPHONE_LIDAR else 0.05)
                    continue

                if (
                    sample.depth is not None
                    and sample.depth.sequence == last_depth_sequence
                ):
                    time.sleep(0.005)
                    continue

                failures = 0
                frame = sample.bgr
                last_frame = frame
                if sample.depth is not None:
                    last_depth_sequence = sample.depth.sequence
                    if previous_depth_time is not None:
                        instant_depth_fps = 1.0 / max(now - previous_depth_time, 1e-6)
                        depth_fps = (
                            instant_depth_fps
                            if depth_fps == 0
                            else 0.9 * depth_fps + 0.1 * instant_depth_fps
                        )
                    previous_depth_time = now

                timestamp_ms = int((now - start_time) * 1000)
                hand_detection = hand_tracker.process(frame, timestamp_ms)

                if mode_state.mode == ConsoleMode.HAND_FOLLOW:
                    detections = []
                    target = None
                    hand_blocked = False
                    depth_gate.reset()
                    decision = depth_gate.update(None, armed=False, hand_blocked=False)
                    measurement = DepthMeasurement(None, None, 0.0, (0, 0, 0, 0))
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
                        if (
                            target is None
                            and mode_state.vision_source == VisionSource.IPHONE_LIDAR
                        ):
                            target = _best_target_in_zone(
                                detections,
                                zone,
                                machine.min_area_ratio,
                                machine.max_area_ratio,
                            )
                        if mode_state.vision_source == VisionSource.MAC_CAMERA:
                            machine.update(
                                None
                                if hand_blocked or target is None
                                else _observation(target)
                            )
                        last_object_detection_time = now

                    if mode_state.vision_source == VisionSource.IPHONE_LIDAR:
                        measurement = DepthMeasurement(None, None, 0.0, (0, 0, 0, 0))
                        if sample.depth is not None and target is not None:
                            measurement = measure_depth(
                                sample.depth.depth_mm,
                                sample.depth.confidence,
                                rgb_box=(target.x, target.y, target.width, target.height),
                                rgb_size=(target.frame_width, target.frame_height),
                                inner_ratio=float(lidar_config["roi_inner_ratio"]),
                                min_confidence=confidence_value(lidar_config["min_confidence"]),
                                min_valid_ratio=float(lidar_config["min_valid_depth_ratio"]),
                                contact_depth_mm=lidar_config.get("contact_depth_mm"),
                            )
                        self._latest_target_depth_mm = measurement.target_depth_mm

                        if self._calibrating:
                            calibrated = calibrator.add(measurement.target_depth_mm)
                            if calibrated is not None:
                                try:
                                    save_contact_depth(self.config_path, calibrated)
                                    lidar_config["contact_depth_mm"] = calibrated
                                    self._calibrating = False
                                    self._set_status(
                                        depth_calibrated=True,
                                        depth_calibrating=False,
                                        contact_depth_mm=round(calibrated, 1),
                                        last_event="0 cm 接触面标定已保存",
                                    )
                                except Exception as exc:
                                    self._calibrating = False
                                    self._set_status(
                                        depth_calibrating=False,
                                        last_event=f"保存标定失败：{type(exc).__name__}: {exc}",
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
                        if (
                            decision.should_open
                            and machine.state == GraspState.ARMED
                            and not controller.emergency_stopped
                            and now - last_command_time >= command_period
                        ):
                            current_pose = grasp_filter.apply(safe_open)
                            controller.move(current_pose)
                            command_count += 1
                            last_command_time = now
                    else:
                        depth_gate.reset()
                        decision = depth_gate.update(None, armed=False, hand_blocked=False)
                        measurement = DepthMeasurement(None, None, 0.0, (0, 0, 0, 0))
                        self._latest_target_depth_mm = None

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
                if sample.depth is not None:
                    depth_roi = (
                        measurement.depth_roi
                        if measurement.depth_roi != (0, 0, 0, 0)
                        else None
                    )
                    self._publish_depth_frame(
                        _depth_colormap(sample.depth.depth_mm, depth_roi)
                    )
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
                    vision_source=mode_state.vision_source.value,
                    depth_fps=round(depth_fps, 1),
                    depth_valid_ratio=round(measurement.valid_ratio, 3),
                    depth_calibrated=lidar_config.get("contact_depth_mm") is not None,
                    depth_calibrating=self._calibrating,
                    contact_depth_mm=lidar_config.get("contact_depth_mm"),
                    target_depth_mm=(
                        None
                        if measurement.target_depth_mm is None
                        else round(measurement.target_depth_mm, 1)
                    ),
                    signed_distance_mm=(
                        None
                        if measurement.signed_distance_mm is None
                        else round(measurement.signed_distance_mm, 1)
                    ),
                    depth_phase=decision.phase.value,
                    depth_stable_count=decision.stable_count,
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
            frame_sources.close()
            self._set_status(camera_ok=False, connected=False)
            with self._frame_condition:
                self._frame_condition.notify_all()
            with self._depth_condition:
                self._depth_condition.notify_all()


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

    @app.get("/depth_feed")
    def depth_feed():
        return Response(
            runtime.depth_mjpeg_stream(),
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
    runtime = WebConsoleRuntime(config, args.camera, requested_dry_run, config_path)
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
