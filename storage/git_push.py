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
DATA_FILES = [
    PROJECT_ROOT / "data" / "listings.tsv",
    PROJECT_ROOT / "data" / "listings_english.tsv"
]


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30
    )


def _push() -> None:
    if getattr(sys, "frozen", False):
        return  # No git repo in a PyInstaller bundle

    try:
        # Check for changes in map and data files
        files_to_add = []
        
        # Check docs/index.html
        status_map = _run(["git", "status", "--porcelain", str(DOCS_INDEX)])
        if status_map.stdout.strip():
            files_to_add.append(str(DOCS_INDEX))
            
        # Check data files
        for tsv in DATA_FILES:
            status_tsv = _run(["git", "status", "--porcelain", str(tsv)])
            if status_tsv.stdout.strip():
                files_to_add.append(str(tsv))

        if not files_to_add:
            logger.debug("GitHub Pages: No files changed — skipping push.")
            return

        for f in files_to_add:
            _run(["git", "add", f])
            
        result = _run(["git", "commit", "-m", "chore: update map and data [skip ci]"])
        if result.returncode != 0:
            logger.debug("GitHub Pages: nothing to commit.")
            return

        # Pull with rebase to handle remote changes. 
        # '-X ours' favors our newly generated files if there's a conflict.
        _run(["git", "pull", "--rebase", "origin", "main", "-X", "ours"])

        push = _run(["git", "push", "origin", "main"])
        if push.returncode == 0:
            logger.info("GitHub Pages: map and data pushed successfully.")
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
