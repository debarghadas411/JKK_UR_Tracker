"""
Geocode Tokyo addresses using Japan's GSI (Geospatial Information Authority) API.

Results are cached in the `geocode_cache` DB table so each unique address is
only looked up once.  A maximum of MAX_PER_CYCLE new addresses are geocoded
per scrape cycle to avoid delaying the normal check cadence.
"""

import json
import logging
import pathlib
import time
from typing import Optional

import requests

from .database import (
    get_geocode_cache_entry,
    get_listings_missing_geocode,
    geocode_cache_count,
    update_listing_geocode,
    upsert_geocode_cache,
)

logger = logging.getLogger(__name__)

GSI_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch"
MAX_PER_CYCLE = 10
INTER_CALL_DELAY = 0.6  # seconds between API calls

SEED_FILE = pathlib.Path(__file__).parent.parent / "geocode_seed.json"


def load_geocode_seed() -> None:
    """
    Import geocode_seed.json into the DB cache when the cache is empty.
    This lets CI start with all known addresses pre-resolved without API calls.
    """
    if not SEED_FILE.exists():
        return
    if geocode_cache_count() > 0:
        return  # Cache already populated — nothing to do

    seed = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    for address, coords in seed.items():
        upsert_geocode_cache(address, coords["lat"], coords["lon"])
    logger.info("Geocoder: loaded %d addresses from seed file.", len(seed))


def _geocode_address(address: str) -> Optional[tuple]:
    """
    Call the GSI AddressSearch API for *address* and return (lat, lon) or None.

    Tokyo prefecture prefix is added when absent to improve result accuracy.
    """
    query = address if address.startswith("東京都") else "東京都" + address
    try:
        resp = requests.get(GSI_URL, params={"q": query}, timeout=10)
        resp.raise_for_status()
        features = resp.json()
        if features:
            coords = features[0]["geometry"]["coordinates"]  # [lon, lat]
            return float(coords[1]), float(coords[0])
    except Exception as exc:
        logger.warning("GSI geocode failed for '%s': %s", address, exc)
    return None


def geocode_missing_listings(source: str = "UR") -> int:
    """
    Geocode up to MAX_PER_CYCLE listings (of *source*) that lack coordinates.

    Returns the number of *new* addresses geocoded via the API (cache hits
    are applied instantly without counting against the limit).
    """
    listings = get_listings_missing_geocode(source)
    if not listings:
        return 0

    # Collect unique addresses (many rooms share a building address)
    address_to_listing_ids: dict[str, list[str]] = {}
    for lst in listings:
        addr = (lst.get("address") or "").strip()
        if addr:
            address_to_listing_ids.setdefault(addr, []).append(lst["listing_id"])

    resolved: dict[str, tuple[float, float]] = {}
    api_calls = 0

    for addr in address_to_listing_ids:
        cached = get_geocode_cache_entry(addr)
        if cached:
            resolved[addr] = (cached["latitude"], cached["longitude"])
            continue

        if api_calls >= MAX_PER_CYCLE:
            break

        result = _geocode_address(addr)
        if result:
            lat, lon = result
            upsert_geocode_cache(addr, lat, lon)
            resolved[addr] = result
            logger.debug("Geocoded '%s' → %.6f, %.6f", addr, lat, lon)
        else:
            # Cache a sentinel so we don't keep retrying bad addresses
            upsert_geocode_cache(addr, 0.0, 0.0)

        api_calls += 1
        time.sleep(INTER_CALL_DELAY)

    # Apply coordinates to all matching listings
    applied = 0
    for addr, (lat, lon) in resolved.items():
        if lat == 0.0 and lon == 0.0:
            continue
        for lid in address_to_listing_ids.get(addr, []):
            update_listing_geocode(lid, lat, lon)
            applied += 1

    if applied:
        logger.info("Geocoder: applied coordinates to %d %s listings.", applied, source)
    return api_calls
