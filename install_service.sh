#!/usr/bin/env bash
# install_service.sh — Install JKK+UR Tracker as a macOS launchd agent.
# Works in two modes:
#   Frozen bundle:  JKK_UR_Tracker binary is present alongside this script.
#   Script mode:    main.py is present; requires Python 3 (Homebrew recommended).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_SRC="$SCRIPT_DIR/com.jkk.tracker.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.jkk.tracker.plist"
GUI_TARGET="gui/$(id -u)"

# ---------------------------------------------------------------------------
# Detect mode: frozen binary or Python script
# ---------------------------------------------------------------------------
if [ -x "$SCRIPT_DIR/JKK_UR_Tracker" ] && [ ! -f "$SCRIPT_DIR/main.py" ]; then
  FROZEN=true
  PROG_ARGS=("<string>$SCRIPT_DIR/JKK_UR_Tracker</string>")
  echo "Mode: frozen executable"
  echo "Binary: $SCRIPT_DIR/JKK_UR_Tracker"
else
  FROZEN=false

  # Prefer a system/Homebrew Python over a venv interpreter.
  # Venv-based Python binaries embed a path to pyvenv.cfg which launchd's
  # restricted environment cannot read, causing a fatal import-site error.
  PYTHON=""
  for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [ -x "$candidate" ]; then
      PYTHON="$candidate"
      break
    fi
  done
  if [ -z "$PYTHON" ]; then
    PYTHON="$(which python3 2>/dev/null || true)"
  fi

  if [ -z "$PYTHON" ]; then
    echo "ERROR: python3 not found. Install Python 3 via Homebrew (brew install python) first."
    exit 1
  fi

  PROG_ARGS=("<string>$PYTHON</string>" "<string>$SCRIPT_DIR/main.py</string>")
  echo "Mode: Python script"
  echo "Python: $PYTHON"
fi

echo "Project dir: $SCRIPT_DIR"

# ---------------------------------------------------------------------------
# Install Python dependencies (script mode only)
# ---------------------------------------------------------------------------
if [ "$FROZEN" = false ]; then
  echo ""
  echo "Installing Python dependencies..."
  "$PYTHON" -m pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
fi

# Ensure log and data directories exist (launchd won't create them)
mkdir -p "$SCRIPT_DIR/logs" "$SCRIPT_DIR/data"

# ---------------------------------------------------------------------------
# Generate plist
# ---------------------------------------------------------------------------
PROG_ARGS_XML=""
for arg in "${PROG_ARGS[@]}"; do
  PROG_ARGS_XML="        $arg"$'\n'"$PROG_ARGS_XML"
done

cat > "$PLIST_SRC" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jkk.tracker</string>

    <key>ProgramArguments</key>
    <array>
$(for arg in "${PROG_ARGS[@]}"; do echo "        $arg"; done)
    </array>

    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$SCRIPT_DIR/logs/stdout.log</string>

    <key>StandardErrorPath</key>
    <string>$SCRIPT_DIR/logs/stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
PLIST

cp "$PLIST_SRC" "$PLIST_DEST"

# ---------------------------------------------------------------------------
# (Re)load the launchd agent
# ---------------------------------------------------------------------------
if launchctl print "$GUI_TARGET/com.jkk.tracker" &>/dev/null; then
  echo "Stopping existing service..."
  launchctl bootout "$GUI_TARGET" "$PLIST_DEST" 2>/dev/null || \
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
  sleep 1
fi

if ! launchctl bootstrap "$GUI_TARGET" "$PLIST_DEST" 2>/dev/null; then
  echo "bootstrap failed, trying legacy load..."
  launchctl load "$PLIST_DEST"
fi

echo ""
echo "✅  JKK + UR Tracker service installed and started."
echo "    Logs:     $SCRIPT_DIR/logs/jkk_tracker.log"
echo "    Data:     $SCRIPT_DIR/data/"
echo "    Map:      $SCRIPT_DIR/data/map.html  (generated after first cycle)"
echo "    Config:   $SCRIPT_DIR/config.yaml"
echo ""
echo "    To view live logs: tail -f $SCRIPT_DIR/logs/jkk_tracker.log"
echo "    To open map:       open $SCRIPT_DIR/data/map.html"
echo "    To stop:           bash $SCRIPT_DIR/uninstall_service.sh"
