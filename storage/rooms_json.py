"""
Cache and lookup JKK building metadata from rooms.json.

rooms.json is served by the JKK public website and contains one record per building
with the building's public page URL (detail_url) and GPS coordinates (latitude / longitude).
"""

import logging
import re
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

ROOMS_JSON_URL = "https://www.to-kousya.or.jp/chintai/cms/json/rooms.json"
JKK_SITE_BASE = "https://www.to-kousya.or.jp"
CACHE_TTL = 3600  # seconds

_cache: dict = {}
_cache_time: float = 0.0


def _normalize_name(name: str) -> str:
    """Strip 【…】 brackets and whitespace for fuzzy matching."""
    return re.sub(r"【[^】]*】", "", name).strip()


def _fetch() -> dict:
    """Download rooms.json and build a name→metadata lookup dict."""
    resp = requests.get(ROOMS_JSON_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("data", [])

    lookup: dict = {}
    for item in items:
        name = item.get("name", "")
        page_url = item.get("page_url", "")
        lat_raw = item.get("map_latitude")
        lon_raw = item.get("map_longitude")
        if not name:
            continue
        entry = {
            "detail_url": (JKK_SITE_BASE + page_url) if page_url else "",
            "latitude":   float(lat_raw) if lat_raw else None,
            "longitude":  float(lon_raw) if lon_raw else None,
        }
        lookup[name] = entry
        norm = _normalize_name(name)
        if norm and norm != name:
            lookup.setdefault(norm, entry)

    logger.debug("rooms.json loaded: %d buildings", len(items))
    return lookup


def get_lookup() -> dict:
    """Return the cached lookup, refreshing if stale."""
    global _cache, _cache_time
    if _cache and time.time() - _cache_time < CACHE_TTL:
        return _cache
    try:
        _cache = _fetch()
        _cache_time = time.time()
    except Exception as exc:
        logger.warning("Failed to fetch rooms.json: %s — using stale cache.", exc)
    return _cache


def lookup_building(building_name: str) -> Optional[dict]:
    """
    Return {detail_url, latitude, longitude} for a JKK building name, or None.

    Matching order:
    1. Exact match
    2. Normalised match (strip 【…】)
    3. Prefix: building_name starts with a normalised rooms.json name
    4. Prefix: a normalised rooms.json name starts with building_name
    """
    if not building_name:
        return None
    lkp = get_lookup()

    if building_name in lkp:
        return lkp[building_name]

    norm_query = _normalize_name(building_name)
    if norm_query in lkp:
        return lkp[norm_query]

    for key, value in lkp.items():
        norm_key = _normalize_name(key)
        if norm_query and norm_key:
            if norm_query.startswith(norm_key) or norm_key.startswith(norm_query):
                return value

    return None
