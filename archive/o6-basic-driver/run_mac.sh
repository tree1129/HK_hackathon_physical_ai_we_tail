#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
WORKSPACE_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

if [ -n "${PCBUSB_LIB_DIR:-}" ]; then
    LOCAL_LIB_DIR="$PCBUSB_LIB_DIR"
elif [ -f "$SCRIPT_DIR/vendor/PCBUSB/libPCBUSB.dylib" ]; then
    LOCAL_LIB_DIR="$SCRIPT_DIR/vendor/PCBUSB"
elif [ -f "$WORKSPACE_DIR/work/maccan-local/lib/libPCBUSB.dylib" ]; then
    LOCAL_LIB_DIR="$WORKSPACE_DIR/work/maccan-local/lib"
elif [ -f "/usr/local/lib/libPCBUSB.dylib" ]; then
    LOCAL_LIB_DIR="/usr/local/lib"
else
    echo "PCBUSB library not found. Run: ./setup_mac.sh" >&2
    exit 1
fi

if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
elif [ -x "$WORKSPACE_DIR/work/.venv/bin/python" ]; then
    PYTHON_BIN="$WORKSPACE_DIR/work/.venv/bin/python"
else
    echo "Python environment not found. Run: ./setup_mac.sh" >&2
    exit 1
fi

if [ ! -x "$PYTHON_BIN" ]; then
    echo "Python environment not found: $PYTHON_BIN" >&2
    echo "Create it and install requirements first; see README.md." >&2
    exit 1
fi

export DYLD_LIBRARY_PATH="$LOCAL_LIB_DIR${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
exec "$PYTHON_BIN" "$SCRIPT_DIR/o6_driver.py" \
    --interface pcan --channel PCAN_USBBUS1 "$@"
