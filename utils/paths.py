"""
Central path resolver — works both as a Python script and as a
PyInstaller-frozen executable.

When frozen (onedir bundle):
  sys.executable = dist/JKK_UR_Tracker/JKK_UR_Tracker
  PROJECT_ROOT   = dist/JKK_UR_Tracker/   ← user-writable, config lives here

When running as a plain script:
  PROJECT_ROOT   = this file's parent.parent = the repo/project root
  (identical to what each module computed with Path(__file__).parent.parent)
"""

import sys
from pathlib import Path


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    # utils/paths.py lives at <project_root>/utils/paths.py
    return Path(__file__).parent.parent


PROJECT_ROOT = _project_root()
DATA_DIR     = PROJECT_ROOT / "data"
LOG_DIR      = PROJECT_ROOT / "logs"
CONFIG_FILE  = PROJECT_ROOT / "config.yaml"
