"""
Session manager for JKK website.

The site requires a POST-based session initialisation before any search
requests will succeed. This module handles that handshake and returns a
requests.Session with valid cookies ready to use.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://jhomes.to-kousya.or.jp"
INIT_URL = f"{BASE_URL}/search/jkknet/service/akiyaJyoukenStartInit"
SEARCH_URL = f"{BASE_URL}/search/jkknet/service/akiyaJyoukenRef"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": BASE_URL,
}


class SessionError(Exception):
    """Raised when session initialisation fails."""


def create_session() -> requests.Session:
    """
    Initialise a JKK session and return a ready-to-use requests.Session.

    Flow:
      1. GET the init page to pick up any initial cookies.
      2. POST back to the same URL with redirect=true to establish the session.
      3. Return the session (cookies are stored automatically).
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        logger.debug("GET session init page: %s", INIT_URL)
        resp = session.get(INIT_URL, timeout=20)
        resp.raise_for_status()
        time.sleep(1)

        logger.debug("POST to establish session: %s", INIT_URL)
        resp = session.post(
            INIT_URL,
            data={"redirect": "true", "url": INIT_URL},
            timeout=20,
            allow_redirects=True,
        )
        resp.raise_for_status()

        logger.info("Session established successfully.")
        return session

    except requests.RequestException as exc:
        raise SessionError(f"Failed to initialise JKK session: {exc}") from exc
