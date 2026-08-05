#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/teaching.pid"
URL="http://127.0.0.1:8080"

if [[ ! -f "$PID_FILE" ]]; then
  echo "A1R 控制服务未运行。"
  exit 0
fi

pid="$(tr -cd '0-9' < "$PID_FILE")"
if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
  rm -f -- "$PID_FILE"
  echo "A1R 控制服务未运行，已清理旧 PID。"
  exit 0
fi

exe="$(readlink -f "/proc/$pid/exe" 2>/dev/null || true)"
exe="${exe% (deleted)}"
if [[ "${exe##*/}" != "a1r_teaching_server" ]]; then
  echo "停止失败：PID $pid 不是 A1R 控制服务，拒绝终止。" >&2
  exit 1
fi

curl -fsS --max-time 5 -X POST "$URL/api/stop" >/dev/null || true
kill -TERM "$pid"
for _ in {1..15}; do
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f -- "$PID_FILE"
    echo "A1R 控制服务已安全停止。"
    exit 0
  fi
  sleep 1
done

echo "服务未在 15 秒内退出；为避免误操作，未强制杀进程。PID=$pid" >&2
exit 1
