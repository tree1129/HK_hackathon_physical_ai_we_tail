#!/bin/zsh
set -eu
SCRIPT_DIR="${0:A:h}"
PYTHON="$SCRIPT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  print -u2 "ERROR: virtual environment is missing. Run: python3 -m venv '$SCRIPT_DIR/.venv'"
  exit 1
fi
export DYLD_LIBRARY_PATH="$SCRIPT_DIR/third_party/maccan${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
exec "$PYTHON" "$SCRIPT_DIR/web_console.py" "$@"
