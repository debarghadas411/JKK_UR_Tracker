#!/usr/bin/env bash
# build_dist.sh — Build a self-contained macOS distribution of JKK_UR_Tracker.
#
# Output: dist/JKK_UR_Tracker_macOS.zip
# Contents when unzipped:
#   JKK_UR_Tracker/
#     JKK_UR_Tracker         ← main daemon binary (run by launchd)
#     clear_data              ← data-reset utility
#     config.yaml             ← user-editable settings
#     install_service.sh      ← installs + starts the launchd agent
#     uninstall_service.sh    ← stops + removes the launchd agent
#     clear_data.sh           ← convenience wrapper for clear_data binary
#     _internal/              ← PyInstaller runtime (do not modify)
#
# Usage:
#   bash build_dist.sh
#
# Requirements:
#   /opt/homebrew/bin/python3 with pyinstaller installed
#   (pip3 install pyinstaller)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON=/opt/homebrew/bin/python3
DIST_DIR="$SCRIPT_DIR/dist/JKK_UR_Tracker"
ZIP_OUT="$SCRIPT_DIR/dist/JKK_UR_Tracker_macOS.zip"

echo "=== JKK_UR_Tracker build ==="
echo "Python: $PYTHON"
echo "Source: $SCRIPT_DIR"
echo ""

# Ensure PyInstaller is available
if ! "$PYTHON" -m PyInstaller --version &>/dev/null; then
  echo "Installing PyInstaller..."
  "$PYTHON" -m pip install --quiet pyinstaller
fi

# Ensure certifi is importable (used in the spec file)
"$PYTHON" -m pip install --quiet certifi

# Clean previous build artefacts
rm -rf "$SCRIPT_DIR/build" "$DIST_DIR" "$ZIP_OUT"

# Run PyInstaller
cd "$SCRIPT_DIR"
"$PYTHON" -m PyInstaller JKK_UR_Tracker.spec

echo ""
echo "=== Copying user-facing files into bundle ==="

# README
cp "$SCRIPT_DIR/README.md"            "$DIST_DIR/README.md"

# config.yaml — placed next to the executable so users can edit it
cp "$SCRIPT_DIR/config.yaml"          "$DIST_DIR/config.yaml"

# Shell scripts
cp "$SCRIPT_DIR/install_service.sh"   "$DIST_DIR/install_service.sh"
cp "$SCRIPT_DIR/uninstall_service.sh" "$DIST_DIR/uninstall_service.sh"
chmod +x "$DIST_DIR/install_service.sh" "$DIST_DIR/uninstall_service.sh"

# Rewrite clear_data.sh to call ./clear_data binary instead of python3
cat > "$DIST_DIR/clear_data.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$DIR/clear_data" "$@"
SH
chmod +x "$DIST_DIR/clear_data.sh"

# Ensure the executables are executable
chmod +x "$DIST_DIR/JKK_UR_Tracker" "$DIST_DIR/clear_data"

echo ""
echo "=== Creating distribution zip ==="
cd "$SCRIPT_DIR/dist"
zip -r --quiet "$(basename "$ZIP_OUT")" JKK_UR_Tracker/

echo ""
echo "✅  Build complete."
echo "    Bundle:  $DIST_DIR"
echo "    Archive: $ZIP_OUT"
echo ""
echo "To distribute: share $ZIP_OUT"
echo "Recipients:"
echo "  1. Unzip to a permanent writable location (e.g. ~/Applications/JKK_UR_Tracker)"
echo "  2. Remove quarantine:  xattr -dr com.apple.quarantine JKK_UR_Tracker/"
echo "  3. Edit config.yaml to set wards, floor plans, rent filters, etc."
echo "  4. Run: bash install_service.sh"
echo "  5. After ~2 minutes: open data/map.html  in a browser for the interactive map"
