#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
CONTROL_URL="http://127.0.0.1:8080"
VISION_URL="http://127.0.0.1:8090"
CONTROL_LOG="$SCRIPT_DIR/server.log"
VISION_LOG="$SCRIPT_DIR/vision_approach.log"

wait_http() {
  local url="$1"
  local name="$2"
  for _ in {1..20}; do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      echo "[正常] $name"
      return 0
    fi
    sleep 1
  done
  echo "[失败] $name 未通过健康检查：$url" >&2
  return 1
}

echo "正在停止旧服务……"
curl -fsS --max-time 3 -X POST "$VISION_URL/api/approach/stop" >/dev/null 2>&1 || true
pkill -TERM -f 'dashboard/a1r_teaching_server' 2>/dev/null || true
pkill -TERM -f 'python3 dashboard/vision_approach.py' 2>/dev/null || true
for _ in {1..10}; do
  if ! pgrep -f 'dashboard/a1r_teaching_server' >/dev/null && \
     ! pgrep -f 'python3 dashboard/vision_approach.py' >/dev/null; then
    break
  fi
  sleep 1
done

# 优先使用 USB-CAN 的稳定硬件 ID。即使内核把设备从 ttyACM0
# 改成 ttyACM1，这个链接也会自动指向正确的串口。
device="${A1R_DEVICE:-}"
for _ in {1..30}; do
  if [[ -n "$device" && -e "$device" ]]; then break; fi
  device="$(find /dev/serial/by-id -maxdepth 1 -name '*CANable*' -print -quit 2>/dev/null || true)"
  if [[ -z "$device" ]]; then
    for candidate in /dev/ttyACM* /dev/ttyUSB*; do
      if [[ -e "$candidate" ]]; then device="$candidate"; break; fi
    done
  fi
  [[ -n "$device" && -e "$device" ]] && break
  device=""
  sleep 1
done

if [[ -z "$device" || ! -e "$device" ]]; then
  echo "[失败] 30 秒内未检测到 USB-CAN 串口，请重新插拔设备。" >&2
  exit 1
fi
echo "[正常] USB-CAN：$device -> $(readlink -f "$device" 2>/dev/null || echo "$device")"

cd -- "$ROOT_DIR"
export A1R_DEVICE="$device"
setsid -f "$SCRIPT_DIR/a1r_teaching_server" >"$CONTROL_LOG" 2>&1
setsid -f python3 "$SCRIPT_DIR/vision_approach.py" >"$VISION_LOG" 2>&1

control_ok=0
vision_ok=0
wait_http "$CONTROL_URL/api/status" "机械臂控制服务（8080）" || control_ok=$?
wait_http "$VISION_URL/api/approach/status" "视觉检测服务（8090）" || vision_ok=$?

if [[ "$control_ok" -ne 0 || "$vision_ok" -ne 0 ]]; then
  echo "控制服务日志：" >&2
  tail -n 20 "$CONTROL_LOG" >&2 || true
  echo "视觉服务日志：" >&2
  tail -n 20 "$VISION_LOG" >&2 || true
  exit 1
fi

# 重启后只进入待命，不自动驱动机械臂。
curl -fsS --max-time 3 -X POST "$VISION_URL/api/approach/stop" >/dev/null 2>&1 || true
echo "一键启动完成：示教与视觉服务均已就绪，自动靠近保持关闭。"
