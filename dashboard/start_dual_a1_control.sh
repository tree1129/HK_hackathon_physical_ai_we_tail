#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/mememe/ArmApi
DASH="$ROOT/dashboard"
BIN="$DASH/a1r_teaching_server"
RIGHT_DEV=/dev/serial/by-id/usb-Openlight_Labs_CANable2_b158aa7_github.com_normaldotcom_canable2.git_2097368F4343-if00
LEFT_DEV=/dev/serial/by-id/usb-Openlight_Labs_CANable2_b158aa7_github.com_normaldotcom_canable2.git_209836A04343-if00

[[ -e "$RIGHT_DEV" ]] || { echo "右臂设备未找到: $RIGHT_DEV" >&2; exit 1; }
[[ -e "$LEFT_DEV" ]] || { echo "左臂设备未找到: $LEFT_DEV" >&2; exit 1; }

stop_pid_file() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  local pid
  pid="$(tr -cd '0-9' < "$file")"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    [[ "$(readlink -f "/proc/$pid/exe")" == "$BIN" ]] || return 1
    kill -TERM "$pid"
    for _ in {1..10}; do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    ! kill -0 "$pid" 2>/dev/null || return 1
  fi
  rm -f -- "$file"
}

stop_pid_file "$DASH/teaching.pid"
stop_pid_file "$DASH/right.pid"
stop_pid_file "$DASH/left.pid"
cd "$ROOT"

A1_ARM_SIDE=right A1_ARM_DEVICE="$RIGHT_DEV" A1_ARM_MODEL=a1_r A1_ARM_PORT=8080 A1_ARM_LIBRARY=trajectory_library \
  nohup "$BIN" >"$DASH/right.log" 2>&1 </dev/null &
right_pid=$!
echo "$right_pid" >"$DASH/right.pid"

A1_ARM_SIDE=left A1_ARM_DEVICE="$LEFT_DEV" A1_ARM_MODEL=a1_l A1_ARM_PORT=8081 A1_ARM_LIBRARY=trajectory_library_left \
  nohup "$BIN" >"$DASH/left.log" 2>&1 </dev/null &
left_pid=$!
echo "$left_pid" >"$DASH/left.pid"

for endpoint in http://127.0.0.1:8080/api/status http://127.0.0.1:8081/api/status; do
  for _ in {1..20}; do curl -fsS --max-time 2 "$endpoint" >/dev/null 2>&1 && break; sleep 1; done
  curl -fsS --max-time 2 "$endpoint" >/dev/null
done
echo "双臂控制服务已启动: right=$right_pid left=$left_pid"
