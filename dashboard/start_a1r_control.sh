#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SERVER="$SCRIPT_DIR/a1r_teaching_server"
PAGE="$SCRIPT_DIR/teaching.html"
PID_FILE="$SCRIPT_DIR/teaching.pid"
LOG_FILE="$SCRIPT_DIR/teaching.log"
URL="http://127.0.0.1:8080"

if [[ -f "$PID_FILE" ]]; then
  pid="$(tr -cd '0-9' < "$PID_FILE")"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "A1R 控制服务已在运行，PID=$pid"
    echo "控制页面：http://$(hostname -I | awk '{print $1}'):8080/"
    exit 0
  fi
  rm -f -- "$PID_FILE"
fi

if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE '(^|:)8080$'; then
  echo "启动失败：端口 8080 已被其他程序占用。" >&2
  ss -ltnp 2>/dev/null | grep ':8080' >&2 || true
  exit 1
fi

[[ -x "$SERVER" ]] || { echo "启动失败：找不到可执行文件 $SERVER" >&2; exit 1; }
[[ -s "$PAGE" ]] || { echo "启动失败：找不到页面文件 $PAGE" >&2; exit 1; }
device="${A1R_DEVICE:-}"
for _ in {1..30}; do
  if [[ -n "$device" && -e "$device" ]]; then break; fi
  device="$(find /dev/serial/by-id -maxdepth 1 -name '*CANable*' -print -quit 2>/dev/null || true)"
  if [[ -z "$device" ]]; then
    for candidate in /dev/ttyACM*; do
      if [[ -e "$candidate" ]]; then device="$candidate"; break; fi
    done
  fi
  [[ -n "$device" && -e "$device" ]] && break
  device=""
  sleep 1
done
[[ -n "$device" && -e "$device" ]] || { echo "启动失败：等待 30 秒仍未检测到 USB-CAN 设备" >&2; exit 1; }
export A1R_DEVICE="$device"

cd -- "$ROOT_DIR"
nohup "$SERVER" >"$LOG_FILE" 2>&1 </dev/null &
pid=$!
echo "$pid" >"$PID_FILE"

for _ in {1..20}; do
  if curl -fsS --max-time 2 "$URL/api/status" >/dev/null 2>&1; then
    echo "A1R 控制服务启动成功，PID=$pid，设备=$device"
    echo "控制页面：http://$(hostname -I | awk '{print $1}'):8080/"
    exit 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then break; fi
  sleep 1
done

echo "启动失败，最近日志：" >&2
tail -30 "$LOG_FILE" >&2 || true
rm -f -- "$PID_FILE"
exit 1
