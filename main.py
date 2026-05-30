#!/usr/bin/env python3
"""
JKK + UR Tracker — main entry point.
"""

import logging
import logging.handlers
import sys
import time

import yaml

from utils.paths import CONFIG_FILE, DATA_DIR, LOG_DIR, PROJECT_ROOT

BASE_DIR = PROJECT_ROOT
CONFIG_FILE = CONFIG_FILE
DATA_DIR = DATA_DIR
LOG_DIR = LOG_DIR

from filters.matcher import has_any_filter, partition_changes
from notifications.notifier import notify_changes
from notifications.telegram_notify import notify_changes_telegram, send_digest
from scheduler.runner import schedule_daily, schedule_every_hours, start as start_scheduler
from scraper.fetcher import (
    FetchError,
    extract_form_state,
    fetch_all_listings,
    fetch_jkk_detail,
    fetch_next_page,
)
from scraper.parser import has_next_page, parse_jkk_detail_rooms, parse_listings
from scraper.session import SessionError, create_session
from scraper.ur_fetcher import (
    URFetchError,
    create_ur_session,
    fetch_all_ur_buildings,
    fetch_rooms_for_building,
    fetch_ur_building_html,
    fetch_ur_room_detail,
)
from scraper.ur_parser import parse_ur_listings
from storage.csv_export import save_csv
from storage.database import (
    get_active_listing_count,
    get_active_listings,
    get_stale_ur_building_ids,
    get_ur_building_cache,
    init_db,
    upsert_and_detect_changes,
    upsert_ur_building_cache,
)
from storage.geocoder import geocode_missing_listings
from storage.git_push import push_map_async
from storage.map_export import generate_map_html
from storage.region_cache import refresh_region_cache
from storage.rooms_json import lookup_building
from storage.snapshot import save_snapshot

logger = logging.getLogger(__name__)

_session = None
_config: dict = {}
_is_first_run: bool = True
# Accumulates post-suppression change counts between digest sends.
_digest_stats: dict = {"new": 0, "removed": 0, "updated": 0}


def load_config() -> dict:
    """Load config.yaml and return the parsed dict."""
    if not CONFIG_FILE.exists():
        logger.warning("config.yaml not found at %s — using defaults.", CONFIG_FILE)
        return _default_config()
    with CONFIG_FILE.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    return cfg


def _default_config() -> dict:
    return {
        "check_interval_minutes": 10,
        "filters": {},
        "notifications": {
            "notify_all_changes": True,
            "notify_filtered_matches": True,
        },
    }


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "jkk_tracker.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)

    root.addHandler(fh)
    root.addHandler(sh)


def run_jkk_check() -> list[dict]:
    """Fetch JKK search results, then expand each building into room-level listings."""
    global _session
    if _session is None:
        try:
            _session = create_session()
        except SessionError as exc:
            logger.error("Cannot create JKK session: %s", exc)
            return []

    # Deduplicate by (jyutaku_cd, msk_kbn): each unique combination may show
    # different rooms (JKK groups rooms by floor-plan type per msk_kbn row).
    buildings_by_key: dict[tuple, dict] = {}
    last_form_state: dict = {}

    try:
        html, _session = fetch_all_listings(_session)
        last_form_state = extract_form_state(html)
        for building in parse_listings(html):
            jid = building.get("jyutaku_cd")
            mkb = building.get("msk_kbn")
            if jid:
                buildings_by_key[(jid, mkb)] = building

        seen_first = next(iter(buildings_by_key), None)

        while has_next_page(html):
            form_state = extract_form_state(html)
            last_form_state = form_state
            html, _session = fetch_next_page(_session, form_state)
            page_buildings = parse_listings(html)
            if not page_buildings:
                break

            first_key = (page_buildings[0].get("jyutaku_cd"), page_buildings[0].get("msk_kbn"))
            if first_key == seen_first:
                break

            for building in page_buildings:
                jid = building.get("jyutaku_cd")
                mkb = building.get("msk_kbn")
                if jid:
                    buildings_by_key[(jid, mkb)] = building
            seen_first = first_key
    except FetchError as exc:
        logger.error("JKK fetch failed: %s", exc)
        return []

    # Fetch detail page per (jyutaku_cd, msk_kbn); listing_id is based on
    # jyutaku_cd+room_number, so rooms appearing in multiple fetches are deduped.
    all_rooms_by_id: dict[str, dict] = {}
    unique_buildings = len({k[0] for k in buildings_by_key})
    for (jyutaku_cd, _), building_info in buildings_by_key.items():
        building_payload = dict(building_info)
        boshu_no = building_payload.pop("boshu_no", "")
        msk_kbn = building_payload.pop("msk_kbn", "")
        yusen_kbn = building_payload.pop("yusen_kbn", "0000")
        building_payload.pop("jyutaku_cd", None)
        building_payload.pop("listing_id", None)

        try:
            detail_html, _session = fetch_jkk_detail(
                _session, last_form_state, boshu_no, msk_kbn, jyutaku_cd, yusen_kbn
            )
            # Enrich with public building page URL + GPS from rooms.json
            reco = lookup_building(building_payload.get("name", ""))
            if reco:
                building_payload.setdefault("detail_url", reco.get("detail_url") or "")
                building_payload.setdefault("latitude",   reco.get("latitude"))
                building_payload.setdefault("longitude",  reco.get("longitude"))
            rooms = parse_jkk_detail_rooms(detail_html, building_payload, jyutaku_cd)
            for room in rooms:
                all_rooms_by_id[room["listing_id"]] = room
            logger.debug("JKK building %s msk=%s: %d rooms", jyutaku_cd, msk_kbn, len(rooms))
            time.sleep(0.3)
        except Exception as exc:
            logger.warning("JKK detail fetch failed for building %s: %s — skipping", jyutaku_cd, exc)

    all_rooms = list(all_rooms_by_id.values())
    logger.info("JKK: %d rooms from %d buildings (%d msk_kbn rows)", len(all_rooms), unique_buildings, len(buildings_by_key))
    return all_rooms


def run_ur_check() -> list[dict]:
    """Fetch UR buildings, enrich them, and return room-level listings."""
    ur_cfg = _config.get("ur", {})
    if not ur_cfg.get("enabled", True):
        logger.debug("UR scraping disabled in config — skipping.")
        return []

    try:
        session = create_ur_session()
        all_buildings = fetch_all_ur_buildings(session)

        all_bids = [b.get("id", "") for b in all_buildings if b.get("id")]
        stale_bids = set(get_stale_ur_building_ids(all_bids))
        for building in all_buildings:
            bid = building.get("id", "")
            if bid in stale_bids:
                bukken_url = building.get("bukkenUrl", "")
                if bukken_url:
                    address = fetch_ur_building_html(session, bukken_url)
                    if address:
                        upsert_ur_building_cache(bid, address)
                    time.sleep(0.3)

        building_cache = get_ur_building_cache()

        enriched_pairs = []
        vacant = [b for b in all_buildings if (b.get("roomCount") or 0) > 0]
        for building in vacant:
            bid = building.get("id", "")
            rooms = fetch_rooms_for_building(session, bid)
            for room in rooms:
                time.sleep(0.2)
                detail = fetch_ur_room_detail(session, bid, room.get("id", ""))
                cached = building_cache.get(bid, {})
                enriched_pairs.append((building, room, detail, cached))

        return parse_ur_listings(enriched_pairs)
    except URFetchError as exc:
        logger.error("UR fetch failed: %s", exc)
        return []
    except Exception as exc:
        logger.error("UR unexpected error: %s", exc)
        return []


def run_check() -> None:
    """Run one full scrape / persist / notify cycle."""
    global _is_first_run

    logger.info("=== Check cycle starting ===")

    jkk_listings = run_jkk_check()
    ur_listings = run_ur_check()
    all_listings = jkk_listings + ur_listings

    logger.info(
        "Fetched %d JKK + %d UR = %d total listings",
        len(jkk_listings), len(ur_listings), len(all_listings),
    )

    if not all_listings:
        logger.warning("Zero listings returned from all sources — possible site maintenance. Skipping cycle.")
        return

    if _is_first_run and not get_active_listings():
        logger.info("First run detected — saving baseline (%d listings) silently.", len(all_listings))
        upsert_and_detect_changes(all_listings)
        active = get_active_listings()
        save_snapshot(active)
        save_csv(active)
        geocode_missing_listings()
        generate_map_html(get_active_listings())
        if _config.get("github_pages", {}).get("auto_push", True):
            push_map_async()
        _is_first_run = False
        logger.info("=== Baseline saved. Monitoring starts next cycle. ===")
        return

    _is_first_run = False

    active_jkk_before = get_active_listing_count("JKK") if jkk_listings else -1
    change_report = upsert_and_detect_changes(all_listings)

    if active_jkk_before == 0 and jkk_listings:
        jkk_new_count = len([l for l in change_report.get("new", []) if l.get("source") == "JKK"])
        if jkk_new_count > 0:
            logger.info("JKK repopulation detected (%d new rooms) — suppressing notifications.", jkk_new_count)
            change_report["new"] = [l for l in change_report.get("new", []) if l.get("source") != "JKK"]

    # Accumulate post-suppression counts for the daily digest.
    _digest_stats["new"] += len(change_report.get("new", []))
    _digest_stats["removed"] += len(change_report.get("removed", []))
    _digest_stats["updated"] += len(change_report.get("updated", []))

    active = get_active_listings()
    save_snapshot(active)
    save_csv(active)
    geocode_missing_listings()
    generate_map_html(get_active_listings())
    if _config.get("github_pages", {}).get("auto_push", True):
        push_map_async()

    n_cfg = _config.get("notifications", {})
    notify_all: bool = n_cfg.get("notify_all_changes", True)
    notify_filtered: bool = n_cfg.get("notify_filtered_matches", True)

    filters = _config.get("filters", {})
    priority = None
    if notify_filtered and has_any_filter(filters):
        partitioned = partition_changes(change_report, filters)
        priority = partitioned.get("priority")

    total_changes = (
        len(change_report.get("new", []))
        + len(change_report.get("removed", []))
        + len(change_report.get("updated", []))
    )

    if total_changes > 0:
        notify_changes(
            change_report,
            notify_all=notify_all,
            notify_filtered=notify_filtered,
            priority_changes=priority,
        )

        # Telegram — one message per added/removed listing
        tg_cfg = _config.get("telegram", {})
        if tg_cfg.get("enabled") and tg_cfg.get("bot_token") and tg_cfg.get("chat_id"):
            notify_changes_telegram(
                bot_token=tg_cfg["bot_token"],
                chat_id=str(tg_cfg["chat_id"]),
                change_report=change_report,
                only_filtered=tg_cfg.get("only_filtered_matches", False),
                filtered_changes=priority,
            )
    else:
        logger.info("No changes detected.")

    logger.info(
        "=== Check cycle done — %d active listings | +%d -%d ~%d ===",
        len(active),
        len(change_report.get("new", [])),
        len(change_report.get("removed", [])),
        len(change_report.get("updated", [])),
    )


def run_region_cache_refresh() -> None:
    """Hourly: force-rebuild region transit cache for all active wards, then regenerate outputs."""
    logger.info("Hourly region cache refresh starting.")
    active = get_active_listings()
    wards = list({lst.get("ward", "") for lst in active if lst.get("ward")})
    if not wards:
        logger.info("No active wards — skipping region cache refresh.")
        return
    refresh_region_cache(wards)
    save_csv(active)
    generate_map_html(active)
    if _config.get("github_pages", {}).get("auto_push", True):
        push_map_async()
    logger.info("Region cache refresh complete (%d wards).", len(wards))


def run_digest() -> None:
    """Send a daily Telegram summary and reset the accumulated change counters."""
    global _digest_stats

    tg_cfg = _config.get("telegram", {})
    if not (tg_cfg.get("enabled") and tg_cfg.get("bot_token") and tg_cfg.get("chat_id")):
        return

    active_counts = {
        "JKK": get_active_listing_count("JKK"),
        "UR": get_active_listing_count("UR"),
    }

    send_digest(
        bot_token=tg_cfg["bot_token"],
        chat_id=str(tg_cfg["chat_id"]),
        active_counts=active_counts,
        changes_since_last_digest=_digest_stats.copy(),
    )
    _digest_stats = {"new": 0, "removed": 0, "updated": 0}


def main() -> None:
    setup_logging()

    global _config
    _config = load_config()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    init_db()

    interval = _config.get("check_interval_minutes", 10)
    logger.info("JKK + UR Tracker starting. Check interval: %d min.", interval)

    tg_cfg = _config.get("telegram", {})
    digest_time = tg_cfg.get("digest_time", "")
    if tg_cfg.get("enabled") and tg_cfg.get("bot_token") and tg_cfg.get("chat_id") and digest_time:
        try:
            schedule_daily(run_digest, digest_time)
        except Exception as exc:
            logger.warning(
                "Invalid telegram.digest_time %r — daily digest disabled: %s", digest_time, exc
            )

    schedule_every_hours(run_region_cache_refresh, 1)

    start_scheduler(run_check, interval)


if __name__ == "__main__":
    main()
