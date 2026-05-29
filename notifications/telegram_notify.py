"""
Telegram Bot notification integration.

Sends one message per added/removed listing to a Telegram group or chat.

Setup (one-time, ~5 minutes):
  1. Open Telegram and search for @BotFather.
  2. Send /newbot and follow the prompts → copy the bot token.
  3. Add your bot to your group (or use it in a private chat).
  4. Get the chat_id:
       a. Send any message in the group.
       b. Open in browser:
          https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
       c. Find "chat": {"id": -XXXXXXXXXX} — that number is your chat_id.
          (Group IDs are negative; private chats are positive.)
  5. Paste both values into config.yaml under telegram:

       telegram:
         enabled: true
         bot_token: "123456:ABC-..."
         chat_id: "-1001234567890"

API docs: https://core.telegram.org/bots/api#sendmessage
"""

import logging
from typing import Optional

import requests

from storage.translations import normalize_floor_plan, translate_ward

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
_REQUEST_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Low-level send
# ---------------------------------------------------------------------------

def send_message(bot_token: str, chat_id: str, text: str) -> bool:
    """
    Send a Telegram message. Returns True on success.
    Uses HTML parse mode; text is auto-truncated to 4096 chars.
    """
    text = text[:4096]
    url = _API_BASE.format(token=bot_token)
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            return True
        logger.warning("Telegram API returned HTTP %d: %s", resp.status_code, resp.text)
        return False
    except requests.RequestException as exc:
        logger.warning("Telegram request failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Listing formatters
# ---------------------------------------------------------------------------

def _fmt_listing(listing: dict) -> str:
    """Return an HTML-formatted listing summary for a Telegram message."""
    source    = listing.get("source", "?")
    name      = listing.get("name", "Unknown")
    ward      = translate_ward(listing.get("ward", ""))
    fp        = normalize_floor_plan(listing.get("floor_plan", ""))
    area      = listing.get("area_sqm")
    rent      = listing.get("rent_yen")
    mgmt      = listing.get("management_fee_yen")
    floor_num = listing.get("floor")
    built     = listing.get("built_year")
    access    = listing.get("access", "")
    url       = listing.get("detail_url", "")
    lat       = listing.get("latitude")
    lng       = listing.get("longitude")

    lines = [f"<b>[{source}] {name}</b>"]

    if ward:
        lines.append(f"📍 {ward}")

    fp_area = "  ·  ".join(filter(None, [fp, f"{area} m²" if area else None]))
    if fp_area:
        lines.append(f"🏠 {fp_area}")

    if rent:
        if mgmt:
            rent_str = f"¥{rent:,} + ¥{mgmt:,} mgmt = <b>¥{rent + mgmt:,}/mo</b>"
        else:
            rent_str = f"<b>¥{rent:,}/mo</b>"
        lines.append(f"💴 {rent_str}")

    meta = "  ·  ".join(filter(None, [
        f"Floor {floor_num}" if floor_num else None,
        f"Built {built}" if built else None,
    ]))
    if meta:
        lines.append(f"🏗 {meta}")

    if access and "<" in access:
        try:
            from bs4 import BeautifulSoup
            access = BeautifulSoup(access, "lxml").get_text(separator=", ").strip()
        except Exception:
            pass
    if access:
        lines.append(f"🚉 {access}")

    if url:
        lines.append(f'🔗 <a href="{url}">View Listing</a>')

    if lat and lng:
        maps_url = f"https://maps.google.com/?q={lat},{lng}"
        lines.append(f'🗺 <a href="{maps_url}">Google Maps</a>')

    return "\n".join(lines)


def notify_new_listing(bot_token: str, chat_id: str, listing: dict) -> bool:
    """Send a Telegram message for one newly appeared listing."""
    body = _fmt_listing(listing)
    text = f"✅ <b>New listing available</b>\n\n{body}"
    ok = send_message(bot_token, chat_id, text)
    if ok:
        logger.debug("Telegram sent: new listing %s", listing.get("name", ""))
    return ok


def notify_removed_listing(bot_token: str, chat_id: str, listing: dict) -> bool:
    """Send a Telegram message for one listing that disappeared."""
    body = _fmt_listing(listing)
    text = f"❌ <b>Listing removed</b>\n\n{body}"
    ok = send_message(bot_token, chat_id, text)
    if ok:
        logger.debug("Telegram sent: removed listing %s", listing.get("name", ""))
    return ok


# ---------------------------------------------------------------------------
# High-level dispatcher — called from main.py
# ---------------------------------------------------------------------------

def notify_changes_telegram(
    bot_token: str,
    chat_id: str,
    change_report: dict,
    only_filtered: bool = False,
    filtered_changes: Optional[dict] = None,
) -> None:
    """
    Send individual Telegram messages for each added/removed listing.

    Args:
        bot_token:        Telegram bot token from @BotFather.
        chat_id:          Target group or chat ID (string or int).
        change_report:    Full {"new": [...], "removed": [...], "updated": [...]}
        only_filtered:    If True, only send for filter-matching listings.
        filtered_changes: The subset matching user filters (used when only_filtered=True).
    """
    source = filtered_changes if (only_filtered and filtered_changes) else change_report

    new_listings     = source.get("new", [])
    removed_listings = source.get("removed", [])

    sent = 0
    for listing in new_listings:
        if notify_new_listing(bot_token, chat_id, listing):
            sent += 1

    for listing in removed_listings:
        if notify_removed_listing(bot_token, chat_id, listing):
            sent += 1

    if sent:
        logger.info("Telegram: sent %d message(s)", sent)


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------

def send_digest(
    bot_token: str,
    chat_id: str,
    active_counts: dict,
    changes_since_last_digest: dict,
) -> bool:
    """
    Send a daily summary digest to Telegram.

    Args:
        bot_token:                Telegram bot token.
        chat_id:                  Target group or chat ID.
        active_counts:            {"JKK": int, "UR": int} — current active listing counts.
        changes_since_last_digest: {"new": int, "removed": int, "updated": int}.
    """
    from datetime import datetime, timezone, timedelta

    jst = timezone(timedelta(hours=9))
    now_str = datetime.now(jst).strftime("%Y-%m-%d %H:%M JST")

    jkk = active_counts.get("JKK", 0)
    ur = active_counts.get("UR", 0)
    total = jkk + ur

    new_c = changes_since_last_digest.get("new", 0)
    rem_c = changes_since_last_digest.get("removed", 0)
    upd_c = changes_since_last_digest.get("updated", 0)

    lines = [
        "📊 <b>Daily Listing Digest</b>",
        f"<i>{now_str}</i>",
        "",
        "<b>Active listings:</b>",
        f"  • JKK: {jkk} rooms",
        f"  • UR: {ur} rooms",
        f"  • Total: {total} rooms",
        "",
        "<b>Since last digest:</b>",
    ]

    if new_c + rem_c + upd_c == 0:
        lines.append("  No changes detected.")
    else:
        if new_c:
            lines.append(f"  ✅ {new_c} new listing(s)")
        if rem_c:
            lines.append(f"  ❌ {rem_c} removed")
        if upd_c:
            lines.append(f"  🔄 {upd_c} updated")

    text = "\n".join(lines)
    ok = send_message(bot_token, chat_id, text)
    if ok:
        logger.info("Telegram: sent daily digest")
    return ok
