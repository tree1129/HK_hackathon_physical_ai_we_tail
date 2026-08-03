#!/bin/zsh
set -eu
SCRIPT_DIR="${0:A:h}"
export DYLD_LIBRARY_PATH="$SCRIPT_DIR/third_party/maccan${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/app.py" "$@"
