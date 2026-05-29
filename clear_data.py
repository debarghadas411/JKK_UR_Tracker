#!/usr/bin/env python3
"""
Clears all stored listings and logs.

Removes:
  - SQLite database (listings + change history)
  - JSON snapshot
  - CSV exports (Japanese + English)
  - Rotating log files

Run with --confirm to skip the interactive prompt.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

from utils.paths import DATA_DIR, LOG_DIR, PROJECT_ROOT

BASE_DIR = PROJECT_ROOT

FILES_TO_DELETE = [
    DATA_DIR / "listings.json",
    DATA_DIR / "listings.tsv",
    DATA_DIR / "listings_english.tsv",
    DATA_DIR / "map.html",
]

LOG_DIR  = LOG_DIR
DB_PATH  = DATA_DIR / "listings.db"


def confirm() -> bool:
    answer = input("This will erase all listings and logs. Type 'yes' to continue: ").strip().lower()
    return answer == "yes"


def clear_database() -> None:
    if not DB_PATH.exists():
        print("  [skip] Database not found.")
        return
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM listings")
    conn.execute("DELETE FROM change_log")
    # Clear caches so the next run fetches everything fresh
    for tbl in ("ur_building_cache", "geocode_cache", "schema_migrations"):
        try:
            conn.execute(f"DELETE FROM {tbl}")
        except sqlite3.OperationalError:
            pass  # table may not exist on older DBs
    conn.commit()
    conn.close()
    print(f"  [ok]   Database cleared ({DB_PATH.name})")


def clear_files() -> None:
    for path in FILES_TO_DELETE:
        if path.exists():
            path.unlink()
            print(f"  [ok]   Deleted {path.name}")
        else:
            print(f"  [skip] {path.name} not found")


def clear_logs() -> None:
    if not LOG_DIR.exists():
        print("  [skip] Log directory not found.")
        return
    deleted = 0
    for log_file in LOG_DIR.glob("*.log*"):
        log_file.unlink()
        deleted += 1
    if deleted:
        print(f"  [ok]   Deleted {deleted} log file(s) in {LOG_DIR.name}/")
    else:
        print("  [skip] No log files found.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear JKK Tracker data and logs.")
    parser.add_argument("--confirm", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args()

    if not args.confirm and not confirm():
        print("Aborted.")
        sys.exit(0)

    print()
    clear_database()
    clear_files()
    clear_logs()
    print("\nDone. The tracker will treat the next run as a fresh first run.")


if __name__ == "__main__":
    main()
