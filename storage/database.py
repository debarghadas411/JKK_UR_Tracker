"""SQLite storage layer for JKK + UR listings and change history."""

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from utils.paths import DATA_DIR

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "listings.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    listing_id          TEXT PRIMARY KEY,
    name                TEXT,
    ward                TEXT,
    priority_type       TEXT,
    housing_type        TEXT,
    floor_plan          TEXT,
    area_text           TEXT,
    area_sqm            REAL,
    rent_text           TEXT,
    rent_yen            INTEGER,
    management_fee_yen  INTEGER,
    first_seen          TEXT,
    last_seen           TEXT,
    is_active           INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS geocode_cache (
    address     TEXT PRIMARY KEY,
    latitude    REAL,
    longitude   REAL,
    geocoded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS change_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id      TEXT NOT NULL,
    change_type     TEXT NOT NULL,
    changed_at      TEXT NOT NULL,
    old_data        TEXT,
    new_data        TEXT
);

CREATE TABLE IF NOT EXISTS ur_building_cache (
    ur_building_id TEXT PRIMARY KEY,
    address        TEXT,
    last_fetched   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    flag       TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_listings_active ON listings(is_active);
CREATE INDEX IF NOT EXISTS idx_changelog_listing ON change_log(listing_id);
CREATE INDEX IF NOT EXISTS idx_changelog_time    ON change_log(changed_at);
"""

LISTING_FIELDS = [
    "listing_id", "name", "ward", "priority_type", "housing_type",
    "floor_plan", "area_text", "area_sqm", "rent_text", "rent_yen",
    "management_fee_yen", "source", "floor", "access", "image_url",
    "detail_url", "ur_building_id", "room_id", "deposit_yen",
    "available_from", "address", "built_year", "room_number", "unit_type",
    "latitude", "longitude",
    "first_seen", "last_seen", "is_active",
]

# Columns added in schema v2+ — applied as ALTER TABLE migrations on existing DBs
_NEW_COLUMNS = {
    "priority_type":      "TEXT",
    "housing_type":       "TEXT",
    "area_text":          "TEXT",
    "rent_text":          "TEXT",
    "management_fee_yen": "INTEGER",
    # v3: UR Chintai integration
    "source":             "TEXT DEFAULT 'JKK'",
    "floor":              "INTEGER",
    "access":             "TEXT",
    "image_url":          "TEXT",
    "detail_url":         "TEXT",
    "ur_building_id":     "TEXT",
    "room_id":            "TEXT",
    # v4: room-level enrichment
    "deposit_yen":        "INTEGER",
    "available_from":     "TEXT",
    "address":            "TEXT",
    "built_year":         "INTEGER",
    "room_number":        "TEXT",
    "unit_type":          "TEXT",
    # v5: geocoordinates
    "latitude":           "REAL",
    "longitude":          "REAL",
}


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add any missing columns to existing databases (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()}
    had_deposit_yen = "deposit_yen" in existing

    for col, col_type in _NEW_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {col_type}")
            logger.info("Migration: added column '%s' to listings table.", col)
    conn.commit()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            flag       TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()

    if not had_deposit_yen:
        migrated = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE flag=?",
            ("jkk_v4_migrated",),
        ).fetchone()
        if not migrated:
            deleted = conn.execute(
                "DELETE FROM listings WHERE source='JKK' OR source IS NULL"
            ).rowcount
            now = _now()
            conn.execute(
                "INSERT INTO schema_migrations (flag, applied_at) VALUES (?, ?)",
                ("jkk_v4_migrated", now),
            )
            conn.commit()
            logger.info("Migration v4: cleared %d legacy JKK rows for room-level refresh.", deleted)


def init_db() -> None:
    """Explicitly initialise the database (also called implicitly by every _connect)."""
    _connect().close()
    logger.debug("Database initialised at %s", DB_PATH)


def get_active_listings() -> list[dict]:
    """Return all listings currently marked active."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM listings WHERE is_active = 1"
        ).fetchall()
    return [dict(r) for r in rows]


def get_active_listing_count(source: str) -> int:
    """Return count of active listings for a given source."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM listings WHERE is_active=1 AND COALESCE(source, 'JKK')=?",
            (source,),
        ).fetchone()
    return int(row["cnt"]) if row else 0


def upsert_and_detect_changes(new_listings: list[dict]) -> dict:
    """
    Compare new_listings against the database, persist changes, and return
    a ChangeReport dict:
        {
            "new":     [listing_dict, ...],
            "removed": [listing_dict, ...],
            "updated": [{"old": ..., "new": ...}, ...],
        }
    """
    now = _now()
    new_by_id = {l["listing_id"]: l for l in new_listings}
    sources_with_new_data = {l.get("source", "JKK") for l in new_listings}

    with _connect() as conn:
        existing_rows = conn.execute(
            "SELECT * FROM listings WHERE is_active = 1"
        ).fetchall()
        existing_by_id = {r["listing_id"]: dict(r) for r in existing_rows}

        added = []
        removed = []
        updated = []

        # Detect new and updated
        for lid, listing in new_by_id.items():
            if lid not in existing_by_id:
                listing["first_seen"] = now
                listing["last_seen"] = now
                listing["is_active"] = 1
                _insert_listing(conn, listing)
                _log_change(conn, lid, "new", None, listing, now)
                added.append(listing)
            else:
                old = existing_by_id[lid]
                changed_fields = _diff(old, listing)
                conn.execute(
                    "UPDATE listings SET last_seen=?, is_active=1 WHERE listing_id=?",
                    (now, lid),
                )
                if changed_fields:
                    _update_listing_fields(conn, listing, changed_fields, now)
                    _log_change(conn, lid, "updated", old, listing, now)
                    updated.append({"old": old, "new": {**old, **listing}})

        # Detect removed
        for lid, old_listing in existing_by_id.items():
            old_source = old_listing.get("source") or "JKK"
            if lid not in new_by_id and old_source in sources_with_new_data:
                conn.execute(
                    "UPDATE listings SET is_active=0, last_seen=? WHERE listing_id=?",
                    (now, lid),
                )
                _log_change(conn, lid, "removed", old_listing, None, now)
                removed.append(old_listing)

        conn.commit()

    logger.info(
        "Change detection: %d new, %d removed, %d updated.",
        len(added), len(removed), len(updated),
    )
    return {"new": added, "removed": removed, "updated": updated}


def _insert_listing(conn: sqlite3.Connection, listing: dict) -> None:
    cols = [f for f in LISTING_FIELDS if f in listing]
    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)
    values = [listing.get(c) for c in cols]
    conn.execute(
        f"INSERT OR REPLACE INTO listings ({col_names}) VALUES ({placeholders})",
        values,
    )


def _update_listing_fields(
    conn: sqlite3.Connection, listing: dict, fields: list[str], now: str
) -> None:
    set_clause = ", ".join(f"{f}=?" for f in fields if f in listing)
    values = [listing[f] for f in fields if f in listing]
    values.append(now)
    values.append(listing["listing_id"])
    conn.execute(
        f"UPDATE listings SET {set_clause}, last_seen=? WHERE listing_id=?",
        values,
    )


def _log_change(
    conn: sqlite3.Connection,
    listing_id: str,
    change_type: str,
    old_data: Optional[dict],
    new_data: Optional[dict],
    now: str,
) -> None:
    conn.execute(
        "INSERT INTO change_log (listing_id, change_type, changed_at, old_data, new_data) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            listing_id,
            change_type,
            now,
            json.dumps(old_data, ensure_ascii=False) if old_data else None,
            json.dumps(new_data, ensure_ascii=False) if new_data else None,
        ),
    )


def _diff(old: dict, new: dict) -> list[str]:
    """Return list of field names that differ between old and new (excluding metadata)."""
    ignore = {"first_seen", "last_seen", "is_active"}
    return [
        k for k in new
        if k not in ignore and old.get(k) != new.get(k)
    ]


def get_ur_building_cache() -> dict:
    """Return {building_id: {address, last_fetched}} for all cached buildings."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT ur_building_id, address, last_fetched FROM ur_building_cache"
        ).fetchall()
    return {
        row["ur_building_id"]: {
            "address": row["address"],
            "last_fetched": row["last_fetched"],
        }
        for row in rows
    }


def upsert_ur_building_cache(building_id: str, address: str) -> None:
    """Insert or update a UR building cache entry."""
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO ur_building_cache (ur_building_id, address, last_fetched)
            VALUES (?, ?, ?)
            ON CONFLICT(ur_building_id) DO UPDATE SET
                address=excluded.address,
                last_fetched=excluded.last_fetched
            """,
            (building_id, address, now),
        )
        conn.commit()


def get_stale_ur_building_ids(all_building_ids: list[str], max_age_days: int = 7) -> list[str]:
    """Return building IDs not in cache or older than max_age_days."""
    if not all_building_ids:
        return []

    cache = get_ur_building_cache()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    stale: list[str] = []

    for building_id in all_building_ids:
        cached = cache.get(building_id)
        if not cached:
            stale.append(building_id)
            continue

        last_fetched = cached.get("last_fetched") or ""
        try:
            fetched_at = datetime.strptime(last_fetched, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            stale.append(building_id)
            continue

        if fetched_at < cutoff:
            stale.append(building_id)

    return stale


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_listings_missing_geocode(source: Optional[str] = None) -> list[dict]:
    """Return active listings that have an address but no latitude yet."""
    with _connect() as conn:
        if source:
            rows = conn.execute(
                "SELECT listing_id, address FROM listings "
                "WHERE is_active=1 AND address IS NOT NULL AND address != '' "
                "AND latitude IS NULL AND COALESCE(source,'JKK')=?",
                (source,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT listing_id, address FROM listings "
                "WHERE is_active=1 AND address IS NOT NULL AND address != '' "
                "AND latitude IS NULL"
            ).fetchall()
    return [dict(r) for r in rows]


def update_listing_geocode(listing_id: str, latitude: float, longitude: float) -> None:
    """Set latitude and longitude for a single listing."""
    with _connect() as conn:
        conn.execute(
            "UPDATE listings SET latitude=?, longitude=? WHERE listing_id=?",
            (latitude, longitude, listing_id),
        )
        conn.commit()


def get_geocode_cache_entry(address: str) -> Optional[dict]:
    """Return cached geocode for an address, or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT latitude, longitude FROM geocode_cache WHERE address=?",
            (address,),
        ).fetchone()
    return dict(row) if row else None


def upsert_geocode_cache(address: str, latitude: float, longitude: float) -> None:
    """Insert or update a geocode cache entry."""
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO geocode_cache (address, latitude, longitude, geocoded_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(address) DO UPDATE SET
                latitude=excluded.latitude,
                longitude=excluded.longitude,
                geocoded_at=excluded.geocoded_at
            """,
            (address, latitude, longitude, now),
        )
        conn.commit()
