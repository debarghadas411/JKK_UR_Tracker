"""
Filter engine: applies config.yaml filters to listing change reports.

A listing "matches" a filter set when ALL active (non-null/non-empty)
conditions are satisfied.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def matches_filter(listing: dict, filters: dict) -> bool:
    """
    Return True if the listing satisfies every active filter condition.

    A filter condition is "active" if it is not None and not an empty list.
    """
    wards = filters.get("wards") or []
    floor_plans = filters.get("floor_plans") or []
    sources = filters.get("sources") or []
    rent_min: Optional[float] = filters.get("rent_min")
    rent_max: Optional[float] = filters.get("rent_max")
    area_min: Optional[float] = filters.get("area_min")
    area_max: Optional[float] = filters.get("area_max")
    age_max: Optional[int] = filters.get("building_age_max")
    floor_min: Optional[int] = filters.get("floor_min")
    floor_max: Optional[int] = filters.get("floor_max")

    if wards and listing.get("ward") not in wards:
        return False

    if floor_plans and listing.get("floor_plan") not in floor_plans:
        return False

    if sources and listing.get("source") not in sources:
        return False

    rent = listing.get("rent_yen")
    if rent is not None:
        if rent_min is not None and rent < rent_min:
            return False
        if rent_max is not None and rent > rent_max:
            return False

    area = listing.get("area_sqm")
    if area is not None:
        if area_min is not None and area < area_min:
            return False
        if area_max is not None and area > area_max:
            return False

    age = listing.get("building_age")
    if age is not None and age_max is not None and age > age_max:
        return False

    flr = listing.get("floor")
    if flr is not None:
        if floor_min is not None and flr < floor_min:
            return False
        if floor_max is not None and flr > floor_max:
            return False

    return True


def partition_changes(change_report: dict, filters: dict) -> dict:
    """
    Split a change report into priority (matches filters) and background groups.

    Returns:
        {
            "priority": {"new": [...], "removed": [...], "updated": [...]},
            "background": {"new": [...], "removed": [...], "updated": [...]},
        }
    """
    result = {
        "priority":   {"new": [], "removed": [], "updated": []},
        "background": {"new": [], "removed": [], "updated": []},
    }

    for listing in change_report.get("new", []):
        bucket = "priority" if matches_filter(listing, filters) else "background"
        result[bucket]["new"].append(listing)

    for listing in change_report.get("removed", []):
        bucket = "priority" if matches_filter(listing, filters) else "background"
        result[bucket]["removed"].append(listing)

    for entry in change_report.get("updated", []):
        new_listing = entry.get("new", {})
        bucket = "priority" if matches_filter(new_listing, filters) else "background"
        result[bucket]["updated"].append(entry)

    return result


def has_any_filter(filters: dict) -> bool:
    """Return True if at least one filter condition is active."""
    return bool(
        (filters.get("wards") or [])
        or (filters.get("floor_plans") or [])
        or (filters.get("sources") or [])
        or filters.get("rent_min") is not None
        or filters.get("rent_max") is not None
        or filters.get("area_min") is not None
        or filters.get("area_max") is not None
        or filters.get("building_age_max") is not None
        or filters.get("floor_min") is not None
        or filters.get("floor_max") is not None
    )
