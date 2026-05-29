#!/usr/bin/env bash
# uninstall_service.sh — Stop and remove the JKK Tracker launchd agent.

set -euo pipefail

PLIST_DEST="$HOME/Library/LaunchAgents/com.jkk.tracker.plist"
GUI_TARGET="gui/$(id -u)"

if [ ! -f "$PLIST_DEST" ]; then
  echo "Service plist not found at $PLIST_DEST — nothing to remove."
  exit 0
fi

echo "Stopping JKK Tracker service..."
launchctl bootout "$GUI_TARGET" "$PLIST_DEST" 2>/dev/null || \
  launchctl unload "$PLIST_DEST" 2>/dev/null || true

rm -f "$PLIST_DEST"
echo "✅  JKK Tracker service stopped and removed."
echo "    Your data and logs in the project folder are untouched."
