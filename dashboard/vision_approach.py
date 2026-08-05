#!/usr/bin/env python3
"""Small HTTP service that turns reCamera detections into smooth A1R approach steps."""

import json
import math
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CAMERA_URL = "http://192.168.254.153:1880/api/latest-detection"
ARM_URL = "http://127.0.0.1:8080"
PICKABLE = {
    "book", "carrot", "kite", "tie", "sports ball", "frisbee", "apple",
    "banana", "orange", "suitcase", "backpack", "remote", "cell phone",
    "teddy bear", "bottle", "cup", "mouse", "scissors",
}
IGNORE = {
    "person", "toilet", "chair", "couch", "bed", "dining table", "tv",
    "refrigerator", "oven", "car", "truck", "bus", "motorcycle",
}

lock = threading.Lock()
state = {
    "enabled": False, "phase": "idle", "message": "待命",
    "target": None, "last_move": None, "updated_at": 0,
}
stop_event = threading.Event()


def fetch_json(url, method="GET", timeout=6.0):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def choose_target(payload):
    data = payload.get("data") or {}
    labels, boxes = data.get("labels") or [], data.get("boxes") or []
    candidates = []
    for label, box in zip(labels, boxes):
        if len(box) < 5:
            continue
        x, y, w, h, score = [float(v) for v in box[:5]]
        label = str(label).lower()
        if label in IGNORE or score < 20 or w < 25 or h < 25:
            continue
        if w > 520 or h > 520 or w * h > 170000:
            continue
        cx, cy = x, y  # SSCMA boxes use center x/y, width, height.
        if not (70 < cx < 1210 and 60 < cy < 700):
            continue
        priority = 2 if label in PICKABLE else 1
        candidates.append((priority, score + min(w * h / 5000, 35), {
            "label": label, "score": score, "cx": cx, "cy": cy,
            "width": w, "height": h,
        }))
    return max(candidates, default=(0, 0, None), key=lambda item: (item[0], item[1]))[2]


def set_state(**updates):
    with lock:
        state.update(updates)
        state["updated_at"] = int(time.time() * 1000)


def approach_loop():
    stable_label = None
    stable_count = 0
    while not stop_event.is_set():
        with lock:
            enabled = state["enabled"]
        if not enabled:
            time.sleep(0.15)
            continue
        try:
            target = choose_target(fetch_json(CAMERA_URL))
            if not target:
                stable_count = 0
                set_state(phase="searching", message="搜索可拾取物品…", target=None)
                time.sleep(0.35)
                continue
            if target["label"] == stable_label:
                stable_count += 1
            else:
                stable_label, stable_count = target["label"], 1
            set_state(phase="tracking", message=f"已发现 {target['label']}，稳定识别 {stable_count}/3", target=target)
            if stable_count < 3:
                time.sleep(0.25)
                continue

            # Center the object horizontally. As the box grows, descend less.
            pixel_error = 640.0 - target["cx"]
            dy = max(-0.040, min(0.040, pixel_error * 0.00016))
            size = max(target["width"], target["height"])
            dz = -0.030 if size < 180 else (-0.018 if size < 270 else 0.0)
            if abs(pixel_error) < 38:
                dy = 0.0
            if dy == 0.0 and dz == 0.0:
                set_state(phase="close", message=f"已靠近 {target['label']}（保持跟随）", target=target)
                time.sleep(0.35)
                continue
            norm = math.hypot(dy, dz)
            if norm > 0.045:
                dy, dz = dy * 0.045 / norm, dz * 0.045 / norm
            query = f"/api/end-move?dx=0&dy={dy:.5f}&dz={dz:.5f}&speed=0.20"
            set_state(phase="moving", message=f"靠近 {target['label']}：Y {dy*100:+.1f} / Z {dz*100:+.1f} cm", target=target)
            result = fetch_json(ARM_URL + query, method="POST", timeout=12)
            set_state(last_move={"dy": dy, "dz": dz, "result": result}, message=f"持续跟随 {target['label']}")
            time.sleep(0.22)
        except Exception as exc:
            set_state(phase="error", message=f"视觉靠近异常：{exc}")
            time.sleep(0.8)


class Handler(BaseHTTPRequestHandler):
    def send_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/api/approach/status":
            self.send_json(404, {"ok": False, "error": "接口不存在"})
            return
        with lock:
            snapshot = dict(state)
        self.send_json(200, {"ok": True, **snapshot})

    def do_POST(self):
        if self.path == "/api/approach/start":
            set_state(enabled=True, phase="searching", message="已启动，搜索可拾取物品…")
            self.send_json(200, {"ok": True, "message": "视觉靠近模式已启动"})
        elif self.path == "/api/approach/stop":
            set_state(enabled=False, phase="idle", message="已停止视觉靠近")
            try:
                fetch_json(ARM_URL + "/api/stop", method="POST", timeout=3)
            except Exception:
                pass
            self.send_json(200, {"ok": True, "message": "视觉靠近模式已停止"})
        else:
            self.send_json(404, {"ok": False, "error": "接口不存在"})

    def log_message(self, *_args):
        pass


threading.Thread(target=approach_loop, daemon=True).start()
ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()
