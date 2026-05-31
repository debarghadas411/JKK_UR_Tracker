#!/usr/bin/env bash
# vm_setup.sh — Bootstrap JKK + UR Tracker on a fresh Ubuntu VM (Oracle Cloud / GCP etc.)
#
# Usage (run as the default ubuntu user, NOT root):
#   bash vm_setup.sh
#
# What this script does:
#   1. Installs Python 3.11, git, and other system packages
#   2. Clones the repo (or skips if already present)
#   3. Installs Python dependencies into a virtualenv
#   4. Generates a GitHub deploy key and prints the public key (add to repo)
#   5. Prompts for Telegram credentials and creates config.yaml
#   6. Installs and starts a systemd service (runs main.py on boot, restarts on crash)
#
# After running this script, the tracker is live. Map pushes go to GitHub Pages.
# Telegram notifications and command polling work immediately.

set -euo pipefail

REPO_URL="git@github.com:debarghadas411/JKK_UR_Tracker.git"
INSTALL_DIR="$HOME/JKK_UR_Tracker"
VENV_DIR="$INSTALL_DIR/.venv"
SERVICE_NAME="jkk-tracker"
SSH_KEY="$HOME/.ssh/github_deploy"

echo "============================================================"
echo "  JKK + UR Tracker — VM Setup"
echo "============================================================"
echo ""

# ── 1. System packages ────────────────────────────────────────────────────────
echo "▶ Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3.11 python3.11-venv python3.11-dev \
    git curl build-essential libssl-dev libffi-dev

# ── 2. GitHub deploy SSH key ──────────────────────────────────────────────────
if [ ! -f "$SSH_KEY" ]; then
    echo ""
    echo "▶ Generating GitHub deploy SSH key..."
    ssh-keygen -t ed25519 -C "jkk-tracker-vm" -f "$SSH_KEY" -N ""
fi

echo ""
echo "┌─────────────────────────────────────────────────────────┐"
echo "│  ACTION REQUIRED: Add this deploy key to your GitHub    │"
echo "│  repo before the script can clone.                      │"
echo "│                                                         │"
echo "│  Go to:                                                 │"
echo "│  github.com/debarghadas411/JKK_UR_Tracker/settings/keys│"
echo "│  → Add deploy key → Allow write access → paste below   │"
echo "└─────────────────────────────────────────────────────────┘"
echo ""
cat "$SSH_KEY.pub"
echo ""
read -rp "Press ENTER after adding the deploy key to GitHub... "

# Configure SSH to use deploy key for github.com
if ! grep -q "Host github.com" "$HOME/.ssh/config" 2>/dev/null; then
    cat >> "$HOME/.ssh/config" <<SSH_CFG

Host github.com
    HostName github.com
    User git
    IdentityFile $SSH_KEY
    StrictHostKeyChecking no
SSH_CFG
    chmod 600 "$HOME/.ssh/config"
fi

# ── 3. Clone repo ─────────────────────────────────────────────────────────────
echo ""
echo "▶ Cloning repository..."
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "  Repo already present — pulling latest..."
    git -C "$INSTALL_DIR" pull --rebase
else
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# ── 4. Python virtualenv + dependencies ──────────────────────────────────────
echo ""
echo "▶ Creating Python virtualenv and installing dependencies..."
python3.11 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# ── 5. Create config.yaml ────────────────────────────────────────────────────
CONFIG="$INSTALL_DIR/config.yaml"
if [ -f "$CONFIG" ]; then
    echo ""
    echo "▶ config.yaml already exists — skipping credential prompts."
else
    echo ""
    echo "▶ Setting up config.yaml..."
    echo "  (Find these in Telegram by messaging @BotFather and @userinfobot)"
    echo ""
    read -rp "  Telegram bot token: " TG_TOKEN
    read -rp "  Telegram chat ID (negative for groups, e.g. -1001234567890): " TG_CHAT

    cat > "$CONFIG" <<YAML
# JKK + UR Tracker — VM config
telegram:
  enabled: true
  bot_token: "$TG_TOKEN"
  chat_id: $TG_CHAT
  digest_time: "08:00"
  only_filtered_matches: false

github_pages:
  auto_push: true

check_interval_minutes: 5

filters:
  rent_max: null
  area_min: null
YAML
    echo "  config.yaml created."
fi

# ── 6. Configure git identity for map commits ─────────────────────────────────
echo ""
echo "▶ Configuring git identity..."
git -C "$INSTALL_DIR" config user.name  "jkk-tracker-vm"
git -C "$INSTALL_DIR" config user.email "jkk-tracker-vm@users.noreply.github.com"

# ── 7. Create data + logs dirs ───────────────────────────────────────────────
mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/logs"

# ── 8. systemd service ───────────────────────────────────────────────────────
echo ""
echo "▶ Installing systemd service..."

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

sudo tee "$SERVICE_FILE" > /dev/null <<SERVICE
[Unit]
Description=JKK + UR Tokyo Housing Tracker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/main.py
Restart=on-failure
RestartSec=30
StandardOutput=append:$INSTALL_DIR/logs/stdout.log
StandardError=append:$INSTALL_DIR/logs/stderr.log
Environment=HOME=$HOME

[Install]
WantedBy=multi-user.target
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

sleep 2
STATUS=$(sudo systemctl is-active "$SERVICE_NAME" 2>/dev/null || echo "unknown")

echo ""
echo "============================================================"
echo "  ✅  Setup complete!"
echo "============================================================"
echo ""
echo "  Service status : $STATUS"
echo "  Logs           : tail -f $INSTALL_DIR/logs/jkk_tracker.log"
echo "  Map (local)    : $INSTALL_DIR/data/map.html"
echo "  Map (live)     : https://debarghadas411.github.io/JKK_UR_Tracker/"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status $SERVICE_NAME"
echo "    sudo systemctl restart $SERVICE_NAME"
echo "    sudo systemctl stop $SERVICE_NAME"
echo "    tail -f $INSTALL_DIR/logs/jkk_tracker.log"
echo ""
