"""
Auto-publishes docs/index.html to GitHub so GitHub Pages stays current.

Runs in a background daemon thread after each map regeneration.
Failures are logged as warnings and never crash the tracker.
Skipped when running as a frozen PyInstaller executable (no git repo present).
"""

import logging
import subprocess
import sys
import threading

from utils.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

DOCS_INDEX = PROJECT_ROOT / "docs" / "index.html"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30
    )


def _push() -> None:
    if getattr(sys, "frozen", False):
        return  # No git repo in a PyInstaller bundle

    try:
        # Only commit if docs/index.html has actually changed (staged or unstaged)
        status = _run(["git", "status", "--porcelain", "docs/index.html"])
        if not status.stdout.strip():
            logger.debug("GitHub Pages: docs/index.html unchanged — skipping push.")
            return

        _run(["git", "add", "docs/index.html"])
        result = _run(["git", "commit", "-m", "chore: update map [skip ci]"])
        if result.returncode != 0:
            logger.debug("GitHub Pages: nothing to commit.")
            return

        push = _run(["git", "push"])
        if push.returncode == 0:
            logger.info("GitHub Pages: map pushed successfully.")
        else:
            logger.warning("GitHub Pages push failed: %s", push.stderr.strip())

    except subprocess.TimeoutExpired:
        logger.warning("GitHub Pages push timed out.")
    except FileNotFoundError:
        logger.warning("GitHub Pages push skipped: git not found in PATH.")
    except Exception as exc:
        logger.warning("GitHub Pages push error: %s", exc)


def push_map_async() -> None:
    """Commit and push docs/index.html in a background thread (non-blocking)."""
    threading.Thread(target=_push, daemon=True, name="git-push").start()
