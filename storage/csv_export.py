"""
TSV export: always reflects the current active listings with all fields.
"""

import csv
import logging
from pathlib import Path

from bs4 import BeautifulSoup
from utils.paths import DATA_DIR

from .region_cache import ensure_regions_cached
from .translations import (
    normalize_floor_plan,
    floor_plan_sort_key,
    translate_available_from,
    translate_housing_type,
    translate_priority_type,
    translate_ward,
)

logger = logging.getLogger(__name__)

TSV_PATH = DATA_DIR / "listings.tsv"
TSV_EN_PATH = DATA_DIR / "listings_english.tsv"

TSV_COLUMNS = [
    "listing_id",
    "name",
    "ward",
    "priority_type",
    "housing_type",
    "floor_plan",
    "area_text",
    "area_sqm",
    "rent_text",
    "rent_yen",
    "management_fee_yen",
    "deposit_yen",
    "available_from",
    "address",
    "built_year",
    "total_expense",
    "source",
    "floor",
    "access",
    "detail_url",
    "latitude",
    "longitude",
    "google_maps_url",
    "first_seen",
    "last_seen",
    "distance_shimbashi_km",
    "transit_shimbashi_min",
]

TSV_HEADERS = {
    "listing_id":             "ID",
    "name":                   "住宅名 (Building Name)",
    "ward":                   "地域 (Ward)",
    "priority_type":          "優先種別 (Priority Type)",
    "housing_type":           "住宅種別 (Housing Type)",
    "floor_plan":             "間取り (Floor Plan)",
    "area_text":              "床面積 (Area)",
    "area_sqm":               "床面積㎡ (Area sqm)",
    "rent_text":              "家賃 (Rent)",
    "rent_yen":               "家賃円 (Rent ¥)",
    "management_fee_yen":     "共益費円 (Mgmt Fee ¥)",
    "deposit_yen":            "敷金円 (Deposit ¥)",
    "available_from":         "入居可能日 (Available From)",
    "address":                "住所 (Address)",
    "built_year":             "竣工年 (Built Year)",
    "total_expense":          "月額合計円 (Total Monthly ¥)",
    "source":                 "ソース (Source)",
    "floor":                  "階 (Floor)",
    "access":                 "アクセス (Train Access)",
    "detail_url":             "詳細URL (Detail URL)",
    "latitude":               "緯度 (Latitude)",
    "longitude":              "経度 (Longitude)",
    "google_maps_url":        "Googleマップ (Google Maps)",
    "first_seen":             "初回確認 (First Seen UTC)",
    "last_seen":              "最終確認 (Last Seen UTC)",
    "distance_shimbashi_km":  "新橋駅距離km (Dist to Shimbashi km)",
    "transit_shimbashi_min":  "新橋駅電車分 (Train min to Shimbashi)",
}

TSV_HEADERS_EN = {
    "listing_id":             "ID",
    "name":                   "Building Name",
    "ward":                   "Ward / Area",
    "priority_type":          "Priority Type",
    "housing_type":           "Housing Type",
    "floor_plan":             "Floor Plan",
    "area_text":              "Area",
    "area_sqm":               "Area (sqm)",
    "rent_text":              "Monthly Rent",
    "rent_yen":               "Monthly Rent (¥)",
    "management_fee_yen":     "Management Fee (¥)",
    "deposit_yen":            "Deposit (¥)",
    "available_from":         "Available From",
    "address":                "Address",
    "built_year":             "Built Year",
    "total_expense":          "Total Monthly Cost (¥)",
    "source":                 "Source",
    "floor":                  "Floor",
    "access":                 "Train Access",
    "detail_url":             "Detail URL",
    "latitude":               "Latitude",
    "longitude":              "Longitude",
    "google_maps_url":        "Google Maps",
    "first_seen":             "First Seen (UTC)",
    "last_seen":              "Last Seen (UTC)",
    "distance_shimbashi_km":  "Distance to Shimbashi (km)",
    "transit_shimbashi_min":  "Train Time to Shimbashi (min)",
}

CSV_PATH = TSV_PATH
CSV_EN_PATH = TSV_EN_PATH


def save_csv(listings: list[dict]) -> None:
    """Overwrite both TSV files (original + English) with active listings."""
    TSV_PATH.parent.mkdir(parents=True, exist_ok=True)

    wards = list({lst.get("ward", "") for lst in listings if lst.get("ward")})
    region_data = ensure_regions_cached(wards)

    sorted_listings = _sort_listings(listings)

    _write_tsv(TSV_PATH, sorted_listings, TSV_HEADERS, translate=False, region_data=region_data)
    _write_tsv(TSV_EN_PATH, sorted_listings, TSV_HEADERS_EN, translate=True, region_data=region_data)

    logger.debug(
        "TSVs saved: %d listings → %s + %s",
        len(listings), TSV_PATH.name, TSV_EN_PATH.name,
    )


def _sort_listings(listings: list[dict]) -> list[dict]:
    """Sort by ward → floor plan (numerically) → area → rent → built year."""
    def _key(lst: dict) -> tuple:
        ward = (lst.get("ward") or "").strip()
        fp   = floor_plan_sort_key(lst.get("floor_plan"))
        area = lst.get("area_sqm") or 0
        rent = lst.get("rent_yen") or 0
        year = lst.get("built_year") or 0
        return (ward, fp[0], fp[1], area, rent, year)
    return sorted(listings, key=_key)


def _strip_number_commas(value: object) -> object:
    if isinstance(value, str):
        return value.replace(",", "")
    return value


def _write_tsv(
    path: Path,
    listings: list[dict],
    headers: dict,
    translate: bool,
    region_data: dict,
) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=TSV_COLUMNS,
            extrasaction="ignore",
            delimiter="\t",
        )
        writer.writerow({col: headers[col] for col in TSV_COLUMNS})
        for listing in listings:
            row = {col: listing.get(col, "") for col in TSV_COLUMNS}

            rent = listing.get("rent_yen")
            mgmt = listing.get("management_fee_yen")
            if rent is not None and mgmt is not None:
                row["total_expense"] = rent + mgmt
            elif rent is not None:
                row["total_expense"] = rent
            else:
                row["total_expense"] = ""

            row["rent_text"] = _strip_number_commas(row["rent_text"])
            row["area_text"] = _strip_number_commas(row["area_text"])

            # Normalise floor plan to ASCII code (both TSVs: 1LDK, 2DK, etc.)
            row["floor_plan"] = normalize_floor_plan(row.get("floor_plan"))

            original_ward = listing.get("ward", "")
            rd = region_data.get(original_ward, {})
            row["distance_shimbashi_km"] = (
                rd["distance_km"] if rd.get("distance_km") is not None else ""
            )
            row["transit_shimbashi_min"] = (
                rd["transit_minutes"] if rd.get("transit_minutes") is not None else ""
            )

            lat = listing.get("latitude")
            lng = listing.get("longitude")
            row["google_maps_url"] = (
                f"https://maps.google.com/?q={lat},{lng}" if lat and lng else ""
            )

            if translate:
                row = _translate_row(row)

            raw_access = row.get("access") or ""
            if raw_access and "<" in raw_access:
                row["access"] = BeautifulSoup(raw_access, "lxml").get_text(separator=", ").strip()

            writer.writerow(row)


def _translate_row(row: dict) -> dict:
    translated = dict(row)
    translated["ward"]           = translate_ward(row.get("ward"))
    translated["priority_type"]  = translate_priority_type(row.get("priority_type"))
    translated["housing_type"]   = translate_housing_type(row.get("housing_type"))
    translated["available_from"] = translate_available_from(row.get("available_from"))
    # floor_plan is already normalised to ASCII code (1LDK etc.) — no further translation
    return translated
