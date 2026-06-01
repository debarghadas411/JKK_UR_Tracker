#!/usr/bin/env bash
# setup_dashboard.sh — Install the Streamlit dashboard as a systemd service on Linux.

set -euo pipefail

INSTALL_DIR="/home/debarghadas411/JKK_UR_Tracker"
VENV_DIR="$INSTALL_DIR/.venv"
SERVICE_NAME="jkk-dashboard"
USER_NAME="debarghadas411"

echo "▶ Installing Dashboard dependencies..."
"$VENV_DIR/bin/pip" install --quiet pandas streamlit

echo "▶ Creating systemd service for dashboard..."

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

sudo tee "$SERVICE_FILE" > /dev/null <<SERVICE
[Unit]
Description=JKK + UR Tracker Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/streamlit run $INSTALL_DIR/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
Restart=on-failure
RestartSec=10
StandardOutput=append:$INSTALL_DIR/logs/dashboard_stdout.log
StandardError=append:$INSTALL_DIR/logs/dashboard_stderr.log
Environment=HOME=/home/$USER_NAME

[Install]
WantedBy=multi-user.target
SERVICE

echo "▶ Starting dashboard service..."
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo ""
echo "✅  Dashboard service installed and started!"
echo "    Status:  sudo systemctl status $SERVICE_NAME"
echo "    Port:    8501"
echo ""
echo "    IMPORTANT: Ensure port 8501 is open in your Cloud Provider's firewall (GCP/Oracle Console)."
