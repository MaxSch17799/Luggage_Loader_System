#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
mkdir -p logs

pause_after_command() {
    echo ""
    read -rp "Press Enter to return to the launcher menu..." _
}

run_and_log() {
    local label="$1"
    shift

    local timestamp
    timestamp="$(date +"%Y%m%d_%H%M%S")"
    local safe_label
    safe_label="$(echo "$label" | tr ' ' '_' | tr -cd 'A-Za-z0-9_-')"
    local log_path="logs/${timestamp}_${safe_label}.log"

    echo ""
    echo "Running: $label"
    echo "Log file: $PROJECT_DIR/$log_path"
    echo ""

    set +e
    "$@" 2>&1 | tee "$log_path"
    local cmd_status=${PIPESTATUS[0]}
    set -e

    echo ""
    if [ "$cmd_status" -eq 0 ]; then
        echo "Command completed successfully."
    else
        echo "Command failed with exit code $cmd_status."
        echo "You can send me this log file:"
        echo "  $PROJECT_DIR/$log_path"
        echo ""
        echo "Last 40 log lines:"
        tail -n 40 "$log_path" || true
    fi

    pause_after_command
}

print_header() {
    echo ""
    echo "Steer Clear Demo Launcher"
    echo "Project folder: $PROJECT_DIR"
    echo ""
}

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is not installed."
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "No virtual environment found. Creating one now..."
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
fi

REQ_HASH_FILE=".venv/.requirements_hash"
CURRENT_REQ_HASH="$(sha256sum requirements.txt | awk '{print $1}')"
INSTALLED_REQ_HASH=""
if [ -f "$REQ_HASH_FILE" ]; then
    INSTALLED_REQ_HASH="$(cat "$REQ_HASH_FILE")"
fi

if [ "$CURRENT_REQ_HASH" != "$INSTALLED_REQ_HASH" ]; then
    echo "Installing or updating Python dependencies..."
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
    echo "$CURRENT_REQ_HASH" > "$REQ_HASH_FILE"
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

while true; do
    print_header
    echo "Configured LiDAR port: $CONFIG_PORT"
    if [ -e "$CONFIG_PORT" ]; then
        echo "LiDAR device appears to be connected."
    else
        echo "LiDAR device not detected at that path right now."
    fi
    echo ""
    echo "Choose how to run the demo:"
    echo "1) Simulate browser demo"
    echo "2) Live LiDAR browser demo"
    echo "3) Run diagnostics"
    echo "4) Show serial ports"
    echo "5) Exit"
    echo ""
    read -rp "Enter choice [1-5]: " CHOICE

    case "$CHOICE" in
        1)
            run_and_log \
                "simulate_browser_demo" \
                env PYTHONUNBUFFERED=1 .venv/bin/python scripts/lidar_web_ui.py --simulate
            ;;
        2)
            run_and_log \
                "live_lidar_browser_demo" \
                env PYTHONUNBUFFERED=1 .venv/bin/python scripts/lidar_web_ui.py
            ;;
        3)
            run_and_log \
                "lidar_diagnostics" \
                env PYTHONUNBUFFERED=1 .venv/bin/python scripts/lidar_diagnostics.py
            ;;
        4)
            run_and_log \
                "show_serial_ports" \
                env PYTHONUNBUFFERED=1 .venv/bin/python scripts/show_serial_ports.py
            ;;
        5)
            echo "Exiting."
            exit 0
            ;;
        *)
            echo "Invalid choice."
            pause_after_command
            ;;
    esac
done
