"""UR Chintai parser — normalises UR building/room data into unified listings."""

import hashlib
import html
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


def _parse_yen(text: str | None) -> int | None:
    """Extract the first integer from a yen string like '62,600円' or '（3,900円）'."""
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _parse_area_sqm(floorspace: str | None) -> float | None:
    """Parse float from HTML-escaped area string e.g. '61&#13217;' → 61.0."""
    if not floorspace:
        return None
    unescaped = html.unescape(floorspace)
    m = re.search(r"[\d.]+", unescaped)
    return float(m.group()) if m else None


def _parse_floor(floor_str: str | None) -> int | None:
    """Parse integer from floor string e.g. '5階' → 5."""
    if not floor_str:
        return None
    m = re.search(r"\d+", floor_str)
    return int(m.group()) if m else None


def _parse_shikikin_yen(shikikin: str, rent_yen: int) -> int | None:
    """Convert a deposit string like '2か月' into yen using the room rent."""
    if not shikikin or rent_yen is None:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:か月|ヶ月|ヵ月|ケ月|月)", shikikin)
    if not m:
        return None
    return int(float(m.group(1)) * rent_yen)


def _make_listing_id(building_id: str, room_id: str) -> str:
    """Generate a stable listing_id: 'ur_' + sha256(building_id|room_id)[:16]."""
    raw = f"{building_id}|{room_id}"
    return "ur_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def parse_ur_listings(raw_pairs: list[tuple]) -> list[dict]:
    """Convert UR tuples to unified listing dicts."""
    results = []
    for item in raw_pairs:
        try:
            if len(item) == 4:
                building, room, detail_data, cached_building = item
                listing = _parse_one(building, room, detail_data, cached_building)
            else:
                building, room = item
                listing = _parse_one(building, room)
            results.append(listing)
        except Exception as exc:
            building = item[0] if item else {}
            room = item[1] if len(item) > 1 else {}
            logger.warning(
                "Failed to parse UR room %s in building %s: %s",
                room.get("id"), building.get("id"), exc,
            )
    return results


def _parse_one(
    building: dict,
    room: dict,
    detail_data: dict | None = None,
    cached_building: dict | None = None,
) -> dict:
    building_id = building.get("id", "")
    room_id = room.get("id", "")

    floorspace_raw = room.get("floorspace", "")
    area_text = html.unescape(floorspace_raw) if floorspace_raw else ""

    commonfee = room.get("commonfee", "")
    rent_yen = _parse_yen(room.get("rent"))
    detail_data = detail_data or {}
    cached_building = cached_building or {}

    deposit_yen = _parse_shikikin_yen(detail_data.get("shikikin", ""), rent_yen)

    built_year = None
    year_text = detail_data.get("year")
    if year_text:
        m = re.search(r"\d+", str(year_text))
        if m:
            built_year = datetime.now().year - int(m.group())

    detail_path = room.get("urlDetail", "")
    detail_url = ("https://www.ur-net.go.jp" + detail_path) if detail_path else ""
    name_parts = [part for part in [building.get("name", ""), room.get("name", "")] if part]

    return {
        "listing_id":          _make_listing_id(building_id, room_id),
        "source":              "UR",
        "name":                "\u3000".join(name_parts),
        "ward":                building.get("skcs", ""),
        "priority_type":       "優先" if building.get("priorityLink") else "",
        "housing_type":        "UR賃貸住宅",
        "floor_plan":          room.get("type", ""),
        "area_text":           area_text,
        "area_sqm":            _parse_area_sqm(floorspace_raw),
        "rent_text":           room.get("rent", ""),
        "rent_yen":            rent_yen,
        "management_fee_yen":  _parse_yen(commonfee),
        "deposit_yen":         deposit_yen,
        "available_from":      detail_data.get("availableDate", "") or room.get("availableDate", ""),
        "address":             cached_building.get("address", ""),
        "built_year":          built_year,
        "floor":               _parse_floor(room.get("floor")),
        "access":              building.get("access", ""),
        "image_url":           building.get("image", ""),
        "detail_url":          detail_url,
        "ur_building_id":      building_id,
        "room_id":             room_id,
    }
