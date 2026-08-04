#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VENDOR_DIR="$SCRIPT_DIR/vendor/PCBUSB"

if [ ! -f "$VENDOR_DIR/LICENSE" ] || [ ! -f "$VENDOR_DIR/libPCBUSB.0.13.dylib" ]; then
    echo "Bundled PCBUSB files are missing." >&2
    echo "Obtain PCBUSB from https://github.com/mac-can/PCBUSB-Library" >&2
    exit 1
fi

echo "PCBUSB is licensed under the EULA at: $VENDOR_DIR/LICENSE"
echo "Continuing to install/use it indicates acceptance of that EULA."

ln -sfn "$VENDOR_DIR/libPCBUSB.0.13.dylib" "$VENDOR_DIR/libPCBUSB.dylib"

if [ ! -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    python3 -m venv "$SCRIPT_DIR/.venv"
fi

"$SCRIPT_DIR/.venv/bin/python" -m pip install --upgrade pip
"$SCRIPT_DIR/.venv/bin/python" -m pip install -r "$SCRIPT_DIR/requirements.txt"
"$SCRIPT_DIR/.venv/bin/python" -m unittest discover -s "$SCRIPT_DIR/tests" -v

echo "Setup complete. Next run:"
echo "  $SCRIPT_DIR/run_mac.sh doctor"
echo "  $SCRIPT_DIR/run_mac.sh status"
