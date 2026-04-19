#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo ""
echo "Steer Clear Demo Launcher"
echo "Project folder: $PROJECT_DIR"
echo ""

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is not installed."
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "No virtual environment found. Creating one now..."
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
fi

CONFIG_PORT="$(
    .venv/bin/python - <<'PY'
import pathlib, tomllib
config_path = pathlib.Path("config/system_parameters.toml")
with config_path.open("rb") as f:
    data = tomllib.load(f)
print(data["serial"]["port"])
PY
)"

echo "Configured LiDAR port: $CONFIG_PORT"
if [ -e "$CONFIG_PORT" ]; then
    echo "LiDAR device appears to be connected."
else
    echo "LiDAR device not detected at that path right now."
fi
echo ""
echo "Choose how to run the demo:"
echo "1) Simulate demo"
echo "2) Live LiDAR demo"
echo "3) Show serial ports"
echo "4) Exit"
echo ""
read -rp "Enter choice [1-4]: " CHOICE

case "$CHOICE" in
    1)
        exec .venv/bin/python scripts/lidar_live_view.py --simulate
        ;;
    2)
        exec .venv/bin/python scripts/lidar_live_view.py
        ;;
    3)
        exec .venv/bin/python scripts/show_serial_ports.py
        ;;
    4)
        echo "Exiting."
        exit 0
        ;;
    *)
        echo "Invalid choice."
        exit 1
        ;;
esac

