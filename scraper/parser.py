"""
HTML parser for JKK listing and detail pages.

Search results are parsed into intermediate building dictionaries. Detail pages
are parsed into room-level listing dictionaries.
"""

import hashlib
import logging
import re
from typing import Any, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def parse_listings(html: str) -> list[dict]:
    """
    Parse a search results page into intermediate building dictionaries.

    Each dict contains building metadata plus the detail-page parameters needed
    to fetch room-level availability.
    """
    soup = BeautifulSoup(html, "lxml")
    listings: list[dict] = []

    result_table = _find_results_table(soup)
    if result_table is None:
        logger.warning("Could not locate the listings table in the HTML response.")
        return listings

    rows = result_table.find_all("tr")
    for row in rows:
        listing = _parse_row(row)
        if listing:
            listings.append(listing)

    logger.info("Parsed %d buildings from page.", len(listings))
    return listings


def has_next_page(html: str) -> bool:
    """Return True if the response HTML contains a 'next page' navigation link."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["a", "input", "button"]):
        text = tag.get_text(strip=True)
        if "後ろへ" in text or "次へ" in text or "次ページ" in text:
            return True
    return False


def parse_total_count(html: str) -> Optional[int]:
    """Extract the total number of matching listings from the results page."""
    match = re.search(r"(\d+)件が該当", html)
    return int(match.group(1)) if match else None


def parse_jkk_detail_rooms(detail_html: str, building_info: dict, jyutaku_cd: str) -> list[dict]:
    """Parse a JKK detail page into one listing dict per room."""
    soup = BeautifulSoup(detail_html, "lxml")
    room_table = _find_room_table(soup)
    if room_table is None:
        logger.warning("Could not locate room table for JKK building %s.", jyutaku_cd)
        return []

    built_year = None
    built_text = _extract_label_value(soup, "竣工年月日")
    if built_text:
        year_m = re.search(r"(\d{4})", built_text)
        if year_m:
            built_year = int(year_m.group(1))

    building_name = _extract_label_value(soup, "住宅名") or building_info.get("name", "")

    container = room_table.find("tbody") or room_table
    rows = container.find_all("tr", recursive=False)
    results: list[dict] = []
    i = 2

    while i < len(rows):
        main_row = rows[i]
        main_cells = main_row.find_all(["td", "th"], recursive=False)
        room_number = _direct_cell_text(main_cells, 1)

        if len(main_cells) != 13 or not re.match(r"^\d+-\d+", room_number):
            i += 1
            continue

        if i + 1 >= len(rows):
            break

        sub_row = rows[i + 1]
        sub_cells = sub_row.find_all(["td", "th"], recursive=False)
        if len(sub_cells) != 2:
            i += 1
            continue

        unit_type = re.sub(r"\s*注意\s*$", "", _direct_cell_text(main_cells, 3))
        floor_plan = _direct_cell_text(main_cells, 4)
        rent_text = _direct_cell_text(main_cells, 6)
        deposit_text = _direct_cell_text(main_cells, 7)
        common_fee_text = _direct_cell_text(main_cells, 8)
        address = _direct_cell_text(main_cells, 9)
        available_from = _direct_cell_text(main_cells, 10)
        area_text = _direct_cell_text(sub_cells, 0)
        floor_text = _direct_cell_text(sub_cells, 1)

        listing_id = hashlib.sha256(f"{jyutaku_cd}|{room_number}".encode("utf-8")).hexdigest()[:16]
        display_name = " ".join(part for part in [building_name, room_number] if part)

        results.append({
            **building_info,
            "listing_id": listing_id,
            "source": "JKK",
            "name": display_name or building_name,
            "floor_plan": floor_plan,
            "area_text": area_text,
            "area_sqm": _parse_float(area_text),
            "rent_text": rent_text,
            "rent_yen": _parse_int(rent_text),
            "management_fee_yen": _parse_int(common_fee_text),
            "deposit_yen": _parse_int(deposit_text),
            "available_from": available_from,
            "address": address,
            "built_year": built_year,
            "floor": _parse_int(floor_text),
            "room_number": room_number,
            "unit_type": unit_type,
        })
        i += 3

    return results


def _find_results_table(soup: BeautifulSoup) -> Optional[Any]:
    """
    Locate the main listing results table.

    JKK renders results in a nested-table layout. The listing table has
    11 columns per row. We identify it by finding the table where the most
    direct-child rows all share a consistent column count of ≥ 5.
    """
    best_table = None
    best_score = 0

    for table in soup.find_all("table"):
        tbody = table.find("tbody")
        container = tbody if tbody else table
        direct_rows = container.find_all("tr", recursive=False)
        if not direct_rows:
            continue

        counts = [len(r.find_all(["td", "th"])) for r in direct_rows]
        mode_cells = max(set(counts), key=counts.count)
        if mode_cells < 5:
            continue
        n_consistent = counts.count(mode_cells)
        if n_consistent > best_score:
            best_score = n_consistent
            best_table = table

    if best_table and best_score >= 2:
        return best_table

    tables = soup.find_all("table")
    if tables:
        return max(tables, key=lambda t: len(t.find_all("tr")))

    return None


def _find_room_table(soup: BeautifulSoup) -> Optional[Any]:
    """Find the inner room table by checking for 部屋番号 in direct-child cells only."""
    for table in soup.find_all("table"):
        container = table.find("tbody") or table
        rows = container.find_all("tr", recursive=False)
        for row in rows[:3]:
            direct_cells = row.find_all(["td", "th"], recursive=False)
            texts = [c.get_text(strip=True) for c in direct_cells]
            if "部屋番号" in texts:
                return table
    return None


def _parse_row(row: Any) -> Optional[dict]:
    """Extract a building dict plus JKK detail parameters from a search row."""
    cells = row.find_all(["td", "th"], recursive=False)
    if len(cells) < 11:
        return None

    def cell_text(idx: int) -> str:
        if idx >= len(cells):
            return ""
        return cells[idx].get_text(separator=" ", strip=True)

    name = cell_text(1)
    if not name or name == "住宅名":
        return None

    detail_cell = cells[10]
    detail_link = detail_cell.find("a", onclick=re.compile(r"senPage\("))
    if not detail_link:
        return None

    onclick = detail_link.get("onclick") or ""
    match = re.search(
        r"senPage\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*\)",
        onclick,
    )
    if not match:
        return None

    boshu_no, msk_kbn, jyutaku_cd, yusen_kbn = match.groups()

    return {
        "listing_id": jyutaku_cd,
        "name": name,
        "ward": cell_text(2),
        "priority_type": cell_text(3),
        "housing_type": cell_text(4),
        "boshu_no": boshu_no,
        "msk_kbn": msk_kbn,
        "jyutaku_cd": jyutaku_cd,
        "yusen_kbn": yusen_kbn,
    }


def _extract_label_value(soup: BeautifulSoup, label: str) -> str:
    label_node = soup.find(string=re.compile(label))
    if not label_node:
        return ""

    label_cell = label_node.find_parent(["td", "th", "dt"])
    if not label_cell:
        return ""

    if label_cell.name == "dt":
        sibling = label_cell.find_next_sibling("dd")
    else:
        sibling = label_cell.find_next_sibling(["td", "th"])

    return sibling.get_text(" ", strip=True) if sibling else ""


def _direct_cell_text(cells: list[Any], idx: int) -> str:
    if idx >= len(cells):
        return ""
    return cells[idx].get_text(separator=" ", strip=True)


def _parse_float(text: str) -> Optional[float]:
    """Extract the first float-like number from a string."""
    match = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
    if match:
        try:
            return float(match.group().replace(",", ""))
        except ValueError:
            pass
    return None


def _parse_int(text: str) -> Optional[int]:
    """Extract the first integer-like number from a string."""
    match = re.search(r"\d+", text.replace(",", ""))
    if match:
        try:
            return int(match.group())
        except ValueError:
            pass
    return None
