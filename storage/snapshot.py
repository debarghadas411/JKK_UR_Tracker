"""JSON snapshot: lightweight current-state file for quick reads."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from utils.paths import DATA_DIR

logger = logging.getLogger(__name__)

SNAPSHOT_PATH = DATA_DIR / "listings.json"


def save_snapshot(listings: list[dict]) -> None:
    """Overwrite the JSON snapshot with the current active listings."""
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(listings),
        "listings": listings,
    }
    SNAPSHOT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.debug("JSON snapshot saved: %d listings → %s", len(listings), SNAPSHOT_PATH)


def load_snapshot() -> list[dict]:
    """Load the last saved snapshot. Returns an empty list if no file exists."""
    if not SNAPSHOT_PATH.exists():
        return []
    try:
        payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        return payload.get("listings", [])
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Could not parse JSON snapshot (%s); treating as empty.", exc)
        return []
