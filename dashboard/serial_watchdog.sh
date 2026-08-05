#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RESTART_SCRIPT="$SCRIPT_DIR/restart_all.sh"
DEVICE_GLOB='/dev/serial/by-id/*CANable*'
CONTROL_URL='http://127.0.0.1:8080/api/status'
VISION_URL='http://127.0.0.1:8090/api/approach/status'
last_device=''
was_present=0

log() { echo "$(date '+%F %T') $*"; }

find_device() {
  local candidate
  for candidate in $DEVICE_GLOB; do
    if [[ -L "$candidate" && -e "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

stop_control() {
  curl -fsS --max-time 2 -X POST http://127.0.0.1:8080/api/shutdown >/dev/null 2>&1 || true
  sleep 1
  pkill -TERM -f 'dashboard/a1r_teaching_server' 2>/dev/null || true
}

log 'USB-CAN 串口看门狗已启动'
while true; do
  device="$(find_device 2>/dev/null || true)"
  if [[ -z "$device" ]]; then
    if [[ "$was_present" -eq 1 ]]; then
      log "USB-CAN 已断开（原设备：$last_device），停止机械臂控制服务"
      stop_control
    fi
    was_present=0
    last_device=''
    sleep 2
    continue
  fi

  resolved="$(readlink -f "$device" 2>/dev/null || true)"
  if [[ "$was_present" -eq 0 || "$resolved" != "$last_device" ]]; then
    log "USB-CAN 已连接：$device -> $resolved，恢复机器人服务"
    if flock -w 5 /tmp/crazy-caveman-restart.lock "$RESTART_SCRIPT"; then
      log '机器人服务恢复成功'
    else
      log '机器人服务恢复失败，将在下一轮重试'
      was_present=0
      sleep 3
      continue
    fi
  elif ! curl -fsS --max-time 2 "$CONTROL_URL" >/dev/null 2>&1 || \
       ! curl -fsS --max-time 2 "$VISION_URL" >/dev/null 2>&1; then
    log '服务健康检查失败，执行自动恢复'
    flock -w 5 /tmp/crazy-caveman-restart.lock "$RESTART_SCRIPT" || true
  fi

  was_present=1
  last_device="$resolved"
  sleep 2
done
