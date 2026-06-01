#!/usr/bin/env bash
# linux_install_service.sh — Install JKK+UR Tracker as a systemd service.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="jkk-tracker"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
VENV_DIR="$SCRIPT_DIR/.venv"

echo "============================================================"
echo "  JKK + UR Tracker — Linux Service Installation"
echo "============================================================"

if [ ! -d "$VENV_DIR" ]; then
    echo "ERROR: .venv directory not found in $SCRIPT_DIR."
    echo "Please create it first: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

# Ensure log and data directories exist
mkdir -p "$SCRIPT_DIR/logs" "$SCRIPT_DIR/data"

echo "▶ Creating systemd service file..."

sudo tee "$SERVICE_FILE" > /dev/null <<SERVICE
[Unit]
Description=JKK + UR Tokyo Housing Tracker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$VENV_DIR/bin/python $SCRIPT_DIR/main.py
Restart=on-failure
RestartSec=30
StandardOutput=append:$SCRIPT_DIR/logs/stdout.log
StandardError=append:$SCRIPT_DIR/logs/stderr.log
Environment=HOME=$HOME

[Install]
WantedBy=multi-user.target
SERVICE

echo "▶ Reloading systemd and starting service..."
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo ""
STATUS=$(sudo systemctl is-active "$SERVICE_NAME" 2>/dev/null || echo "unknown")

if [ "$STATUS" = "active" ]; then
    echo "✅  JKK + UR Tracker service installed and started."
else
    echo "❌  Service failed to start (status: $STATUS)."
    echo "    Check logs: journalctl -u $SERVICE_NAME"
fi

echo "    Logs:     $SCRIPT_DIR/logs/jkk_tracker.log"
echo "    Data:     $SCRIPT_DIR/data/"
echo ""
echo "    To view live logs: tail -f $SCRIPT_DIR/logs/jkk_tracker.log"
echo "    To stop:           sudo systemctl stop $SERVICE_NAME"
echo ""
