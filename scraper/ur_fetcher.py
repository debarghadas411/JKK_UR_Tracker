"""
UR Chintai scraper — building list, room list, and room/detail enrichment.
"""

import logging
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

UR_API_BASE = "https://chintai.r6.ur-net.go.jp/chintai/api/"
UR_TDFK = "13"
UR_AREAS = ["01", "02", "03", "04", "05", "06"]
INTER_CALL_DELAY = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = 2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.ur-net.go.jp/chintai/kanto/tokyo/list/",
}


class URFetchError(Exception):
    """Raised after exhausting all retries on a UR API call."""


def create_ur_session() -> requests.Session:
    """Create a requests session with UR headers preconfigured."""
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def _parse_building_id_parts(building_id: str) -> tuple[str, str, str]:
    """Split a building ID like '20_5630' into API parameters."""
    prefix, suffix = building_id.split("_", 1)
    if not prefix or len(suffix) < 2:
        raise ValueError(f"Invalid UR building id: {building_id}")
    return prefix, suffix[:-1], suffix[-1]


def fetch_all_ur_listings() -> list[tuple[dict, dict]]:
    """Return a flat list of (building_dict, room_dict) tuples for all vacant UR rooms."""
    session = create_ur_session()
    all_buildings = fetch_all_ur_buildings(session)

    results: list[tuple[dict, dict]] = []
    vacant_buildings = [b for b in all_buildings if (b.get("roomCount") or 0) > 0]
    logger.info("Phase B: fetching rooms for %d buildings with vacancies.", len(vacant_buildings))

    for building in vacant_buildings:
        building_id = building.get("id", "")
        time.sleep(INTER_CALL_DELAY)
        rooms = _fetch_rooms_for_building(session, building_id)
        for room in rooms:
            results.append((building, room))

    logger.info("Phase B complete: %d total vacant rooms found.", len(results))
    return results


def fetch_all_ur_buildings(session: requests.Session) -> list[dict]:
    """Phase A only: fetch and return all UR buildings across configured areas."""
    all_buildings: list[dict] = []
    failed_areas = 0

    for area_code in UR_AREAS:
        time.sleep(INTER_CALL_DELAY)
        try:
            buildings = _fetch_buildings_for_area(session, area_code)
            all_buildings.extend(buildings)
            logger.debug("Area %s: %d buildings fetched.", area_code, len(buildings))
        except URFetchError as exc:
            failed_areas += 1
            logger.warning("Area %s fetch failed: %s", area_code, exc)

    if failed_areas == len(UR_AREAS):
        raise URFetchError("All 6 UR area fetches failed — aborting UR scrape.")

    logger.info(
        "Phase A complete: %d buildings across %d areas (%d area(s) failed).",
        len(all_buildings), len(UR_AREAS), failed_areas,
    )
    return all_buildings


def fetch_rooms_for_building(session: requests.Session, building_id: str) -> list[dict]:
    """Fetch room rows for a single UR building."""
    return _fetch_rooms_for_building(session, building_id)


def fetch_ur_room_detail(session: requests.Session, building_id: str, room_id: str) -> dict:
    """Fetch UR room detail API data for one room."""
    if not building_id or not room_id:
        return {}

    try:
        shisya, danchi, shikibetu = _parse_building_id_parts(building_id)
    except ValueError as exc:
        logger.warning("Skipping UR room detail for invalid building id %s: %s", building_id, exc)
        return {}

    url = UR_API_BASE + "bukken/detail/detail_room/"
    payload = {
        "id": room_id,
        "shisya": shisya,
        "danchi": danchi,
        "shikibetu": shikibetu,
        "sp": "",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(url, data=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data[0] if data else {}
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF ** attempt
                time.sleep(wait)
            else:
                logger.warning(
                    "Room detail fetch failed for building %s room %s after %d attempts: %s",
                    building_id, room_id, MAX_RETRIES, exc,
                )
                return {}

    return {}


def fetch_ur_building_html(session: requests.Session, bukken_url: str) -> Optional[str]:
    """Fetch a UR building HTML page and extract its address."""
    if not bukken_url:
        return None

    url = "https://www.ur-net.go.jp" + bukken_url
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return _extract_ur_address(resp.text)
        except Exception as exc:
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF ** attempt
                time.sleep(wait)
            else:
                logger.warning("UR building HTML fetch failed for %s: %s", bukken_url, exc)
                return None

    return None


def _extract_ur_address(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "lxml")

    # UR building pages use <th>住所</th> or <th>所在地</th> → next <td>
    for label in ("住所", "所在地"):
        th = soup.find(lambda tag: tag.name == "th" and label in tag.get_text(strip=True))
        if th:
            td = th.find_next_sibling("td")
            if td:
                text = td.get_text(" ", strip=True)
                if text:
                    return text

        dt = soup.find(lambda tag: tag.name == "dt" and label in tag.get_text(strip=True))
        if dt:
            dd = dt.find_next_sibling("dd")
            if dd:
                text = dd.get_text(" ", strip=True)
                if text:
                    return text

    return None


def _fetch_buildings_for_area(session: requests.Session, area_code: str) -> list[dict]:
    """POST to list_bukken/ with tdfk=13 and area=area_code."""
    url = UR_API_BASE + "bukken/search/list_bukken/"
    payload = {"tdfk": UR_TDFK, "area": area_code}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(url, data=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            logger.warning("Area %s: unexpected response type %s", area_code, type(data))
            return []
        except Exception as exc:
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF ** attempt
                logger.debug("Area %s attempt %d failed (%s) — retrying in %ds.", area_code, attempt, exc, wait)
                time.sleep(wait)
            else:
                raise URFetchError(f"Area {area_code} failed after {MAX_RETRIES} attempts: {exc}") from exc

    return []


def _fetch_rooms_for_building(session: requests.Session, building_id: str) -> list[dict]:
    """POST to room/list/ with tdfk=13, id=building_id, mode=init."""
    url = UR_API_BASE + "room/list/"
    payload = {"tdfk": UR_TDFK, "id": building_id, "mode": "init"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(url, data=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return []
        except Exception as exc:
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF ** attempt
                logger.debug(
                    "Building %s room fetch attempt %d failed (%s) — retrying in %ds.",
                    building_id, attempt, exc, wait,
                )
                time.sleep(wait)
            else:
                logger.warning(
                    "Building %s room fetch failed after %d attempts: %s — skipping.",
                    building_id, MAX_RETRIES, exc,
                )
                return []

    return []
