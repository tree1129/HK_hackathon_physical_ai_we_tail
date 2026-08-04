#!/usr/bin/env python3
"""Offline fixed-phrase voice trigger for the Onero right-arm teaching API."""

from __future__ import annotations

import argparse
import json
import logging
import re
import select
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


API = "http://127.0.0.1:8080"
ASR = Path.home() / "robot-voice/asr_daemon"
PHRASE = "动作库名称"
COOLDOWN_SECONDS = 20


def api(path: str, method: str = "GET") -> dict:
    request = urllib.request.Request(API + path, method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def normalize(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text).lower()


def find_action(text: str, actions: list[dict]) -> dict | None:
    value = normalize(text)
    candidates = [
        item for item in actions
        if normalize(str(item.get("name", "")))
        and normalize(str(item.get("name", ""))) in value
    ]
    if not value or not candidates:
        return None
    # Prefer the most specific (longest) name. For duplicates, prefer the
    # newest numeric trajectory id.
    candidates.sort(
        key=lambda item: (len(normalize(str(item.get("name", "")))), str(item.get("id", ""))),
        reverse=True,
    )
    return candidates[0]


def start_asr() -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [str(ASR)], text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, bufsize=1,
    )
    assert process.stdout is not None
    while True:
        line = process.stdout.readline()
        if not line:
            raise RuntimeError("ASR process exited during startup")
        if line.strip() == "READY":
            return process


def recognize(process: subprocess.Popen[str], wav: Path) -> str:
    if process.poll() is not None or process.stdin is None or process.stdout is None:
        raise RuntimeError("ASR process is not running")
    process.stdin.write(str(wav) + "\n")
    process.stdin.flush()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], 1)
        if not ready:
            continue
        line = process.stdout.readline()
        if not line:
            raise RuntimeError("ASR process exited")
        if line.startswith("RESULT\t"):
            return line.removeprefix("RESULT\t").strip()
    raise subprocess.TimeoutExpired(str(ASR), 20)


def record(wav: Path, seconds: int) -> bool:
    result = subprocess.run(
        [
            "arecord", "-q", "-D", "hw:1,0", "-f", "S16_LE",
            "-r", "16000", "-c", "1", "-d", str(seconds), str(wav),
        ],
        timeout=seconds + 3,
        check=False,
    )
    return result.returncode == 0


def trigger_action(action: dict, status: dict) -> str:
    if status.get("recording") or status.get("replaying"):
        return "ignored: right arm is busy"
    action_id = action["id"]
    query = urllib.parse.urlencode({"id": action_id})
    response = api(f"/api/play?{query}", method="POST")
    return response.get("message", "action started")


def run(capture_seconds: int, dry_run: bool) -> None:
    if not ASR.is_file():
        raise FileNotFoundError(ASR)
    last_trigger = 0.0
    recognizer = start_asr()
    logging.info("ready: say %s", PHRASE)

    with tempfile.TemporaryDirectory(prefix="robot-voice-") as directory:
        wav = Path(directory) / "capture.wav"
        while True:
            try:
                if not record(wav, capture_seconds):
                    logging.error("microphone capture failed")
                    time.sleep(2)
                    continue
                text = recognize(recognizer, wav)
                if text:
                    logging.info("recognized: %s", text)
                status = api("/api/status")
                action = find_action(text, status.get("actions", []))
                if action is None:
                    continue
                now = time.monotonic()
                if now - last_trigger < COOLDOWN_SECONDS:
                    logging.info("ignored duplicate command during cooldown")
                    continue
                if dry_run:
                    logging.info("dry-run match: %s", action["name"])
                else:
                    logging.info("triggered action=%s id=%s: %s", action["name"], action["id"], trigger_action(action, status))
                last_trigger = now
            except (subprocess.SubprocessError, OSError, RuntimeError,
                    urllib.error.URLError, json.JSONDecodeError) as error:
                logging.exception("voice loop error: %s", error)
                if recognizer.poll() is not None:
                    recognizer = start_asr()
                time.sleep(2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-seconds", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--test-text")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.test_text is not None:
        status = api("/api/status")
        action = find_action(args.test_text, status.get("actions", []))
        print(json.dumps({"text": args.test_text, "action": action}, ensure_ascii=False))
        return
    run(args.capture_seconds, args.dry_run)


if __name__ == "__main__":
    main()
