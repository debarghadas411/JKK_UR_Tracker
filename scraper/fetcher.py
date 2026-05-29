"""
HTTP fetcher for JKK listing and detail pages.

Handles Shift-JIS (cp932) decoding, session refresh on 4xx responses,
and retry logic with exponential back-off.
"""

import logging
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .session import BASE_URL, SEARCH_URL, SessionError, create_session

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds; doubled each retry

_SERVICE_BASE = SEARCH_URL.rsplit("/", 1)[0]
NEXT_PAGE_URL = f"{_SERVICE_BASE}/AKIYAafterPage"
JKK_DETAIL_URL = f"{BASE_URL}/search/jkknet/service/akiyaSenDet"


class FetchError(Exception):
    """Raised after exhausting all retries."""


def _decode(response: requests.Response) -> str:
    """Force Windows-31J (cp932) decoding regardless of Content-Type header."""
    return response.content.decode("cp932", errors="replace")


def extract_form_state(html: str) -> dict:
    """
    Extract hidden form fields from a search result page.

    These fields (token, abcde, pagingInputDataGrid_*, etc.) must be
    re-submitted with each subsequent page request so the server can
    advance its server-side pagination cursor.
    """
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form", {"name": "frmMain"}) or soup.find("form")
    if not form:
        return {}
    state: dict = {}
    for inp in form.find_all("input", type="hidden"):
        name = inp.get("name")
        value = inp.get("value") or ""
        if name:
            state[name] = value

    xyz_m = re.search(r'xyz\.value\s*=\s*"([^"]+)"', html)
    if xyz_m:
        state["xyz"] = xyz_m.group(1)
    return state


def fetch_all_listings(session: requests.Session) -> tuple[str, requests.Session]:
    """POST to the JKK search endpoint with no filters to retrieve all listings."""
    post_data = _build_search_payload()
    delay = RETRY_BACKOFF

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug("Fetching listings (attempt %d/%d)", attempt, MAX_RETRIES)
            resp = session.post(SEARCH_URL, data=post_data, timeout=30)

            if resp.status_code in (401, 403, 404):
                logger.warning("HTTP %s — session likely expired; re-initialising.", resp.status_code)
                session = create_session()
                resp = session.post(SEARCH_URL, data=post_data, timeout=30)

            resp.raise_for_status()
            html = _decode(resp)
            logger.debug("Fetch successful, received %d bytes.", len(resp.content))
            return html, session

        except (requests.RequestException, SessionError) as exc:
            logger.warning("Fetch attempt %d failed: %s", attempt, exc)
            if attempt < MAX_RETRIES:
                logger.debug("Retrying in %ds…", delay)
                time.sleep(delay)
                delay *= 2
            else:
                raise FetchError(
                    f"All {MAX_RETRIES} fetch attempts failed. Last error: {exc}"
                ) from exc

    raise FetchError("Unexpected exit from retry loop.")


def fetch_next_page(
    session: requests.Session, form_state: dict
) -> tuple[str, requests.Session]:
    """Advance to the next results page using the server-side pagination cursor."""
    delay = RETRY_BACKOFF

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(NEXT_PAGE_URL, data=form_state, timeout=30)
            if resp.status_code in (401, 403, 404):
                session = create_session()
                resp = session.post(NEXT_PAGE_URL, data=form_state, timeout=30)
            resp.raise_for_status()
            return _decode(resp), session
        except (requests.RequestException, SessionError) as exc:
            if attempt < MAX_RETRIES:
                time.sleep(delay)
                delay *= 2
            else:
                raise FetchError(str(exc)) from exc

    raise FetchError("Unexpected exit from retry loop.")


def fetch_jkk_detail(
    session: requests.Session,
    form_state: dict,
    boshu_no: str,
    msk_kbn: str,
    jyutaku_cd: str,
    yusen_kbn: str = "0000",
) -> tuple[str, requests.Session]:
    """Fetch a JKK building detail page containing room-level availability."""
    payload = dict(form_state)
    payload.update({
        "akiyaRefRM.akiyaDatM.boshuNo": boshu_no,
        "akiyaRefRM.akiyaDatM.mskKbn": msk_kbn,
        "akiyaRefRM.akiyaDatM.jyutakuCd": jyutaku_cd,
        "akiyaRefRM.akiyaDatM.yusenKbn": yusen_kbn,
        "boshuNo": boshu_no,
        "mskKbn": msk_kbn,
        "jyutakuCd": jyutaku_cd,
        "yusenKbn": yusen_kbn,
        "sen_flg": "1",
    })

    delay = RETRY_BACKOFF
    headers = {"Referer": SEARCH_URL}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(JKK_DETAIL_URL, data=payload, headers=headers, timeout=30)
            if resp.status_code in (401, 403, 404):
                session = create_session()
                resp = session.post(JKK_DETAIL_URL, data=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            return _decode(resp), session
        except (requests.RequestException, SessionError) as exc:
            if attempt < MAX_RETRIES:
                time.sleep(delay)
                delay *= 2
            else:
                raise FetchError(str(exc)) from exc

    raise FetchError("Unexpected exit from retry loop.")


def _build_search_payload(filters: Optional[dict] = None) -> dict:
    """Build the POST payload for the JKK search form."""
    payload: dict = {
        "redirect": "false",
        "pageNo": "1",
    }

    if filters:
        if filters.get("wards"):
            payload["kusiCode"] = ",".join(filters["wards"])
        if filters.get("floor_plans"):
            payload["madoriCode"] = ",".join(filters["floor_plans"])
        if filters.get("rent_min") is not None:
            payload["yachinFrom"] = str(int(filters["rent_min"]))
        if filters.get("rent_max") is not None:
            payload["yachinTo"] = str(int(filters["rent_max"]))

    return payload
