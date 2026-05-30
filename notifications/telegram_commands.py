"""
Telegram bot command handler.

Responds to backslash query commands sent to the configured group/chat:
  \\{ward}          — active listings in that ward (partial EN or JA match)
  \\rent{max}       — listings with base rent ≤ max yen
  \\size{min}       — listings with floor area ≥ min m²
  \\plan{floorplan} — listings with floor plan ≥ given plan (e.g. \\plan2DK)
  \\from{YYYYMMDD}  — listings first seen on/after that date (UTC)

Floor plan ranking: 1R < 1K < 1D < 1DK < 1LDK < 2K < 2DK < 2LDK < 3K < 3DK < 3LDK ...

IMPORTANT — GROUP CHAT SETUP:
  By default Telegram bots in groups only receive messages starting with '/'.
  To receive backslash commands, disable bot privacy mode once via @BotFather:
    /setprivacy → select @JKK_UR_Finder_bot → Disable

Command offset is persisted in data/telegram_offset.txt so CI jobs (which run
every ~15 min and exit) can process commands accumulated between runs.
"""

import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from storage.database import get_active_listings
from storage.translations import translate_ward
from utils.paths import DATA_DIR

logger = logging.getLogger(__name__)

OFFSET_FILE = DATA_DIR / "telegram_offset.txt"
MAX_RESULTS = 10


# ---------------------------------------------------------------------------
# Floor plan ranking
# ---------------------------------------------------------------------------

def _fp_rank(plan: str) -> int:
    """
    Compute a numeric rank for floor plan comparison (higher = larger).
    Pattern: {rooms}{suffix}  e.g. 1R, 2DK, 3LDK
    Suffix ranks: R=0, K=1, D=2, DK=3, LDK=4
    Overall rank: rooms * 10 + suffix_rank
    Returns -1 for unrecognised formats.
    """
    if not plan:
        return -1
    m = re.match(r"^(\d+)(R|LDK|DK|D|K)$", plan.strip().upper())
    if not m:
        return -1
    rooms = int(m.group(1))
    suffix_rank = {"R": 0, "K": 1, "D": 2, "DK": 3, "LDK": 4}.get(m.group(2), -1)
    if suffix_rank < 0:
        return -1
    return rooms * 10 + suffix_rank


# ---------------------------------------------------------------------------
# Command parsing
# ---------------------------------------------------------------------------

def _parse_command(text: str) -> Optional[tuple]:
    """
    Parse a backslash command string.
    Returns (cmd_type, arg) or None if not a recognised command.
    Typed commands (rent/size/plan/from) are checked before the ward fallback.
    """
    if not text or not text.strip().startswith("\\"):
        return None
    text = text.strip()

    for pattern, cmd in (
        (r"^\\rent(\d+)$", "rent"),
        (r"^\\size(\d+(?:\.\d+)?)$", "size"),
        (r"^\\plan(\w+)$", "plan"),
        (r"^\\from(\d{8})$", "from"),
    ):
        m = re.match(pattern, text, re.IGNORECASE)
        if m:
            raw = m.group(1)
            if cmd == "rent":
                return (cmd, int(raw))
            if cmd == "size":
                return (cmd, float(raw))
            return (cmd, raw)

    # Ward — any word/kanji sequence after backslash
    m = re.match(r"^\\([\w\u3000-\u9fff\u30a0-\u30ff]+)$", text)
    if m:
        return ("ward", m.group(1))

    return None


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def _norm_ward(s: str) -> str:
    """Normalise a ward string for comparison (lowercase, strip 区/Ward)."""
    return s.lower().replace("ward", "").replace("区", "").strip()


def _filter_listings(listings: list, cmd_type: str, arg) -> list:
    if cmd_type == "ward":
        query = _norm_ward(arg)
        return [
            l for l in listings
            if query in _norm_ward(l.get("ward") or "")
            or query in _norm_ward(translate_ward(l.get("ward") or ""))
        ]

    if cmd_type == "rent":
        return [l for l in listings if (l.get("rent_yen") or 0) <= arg]

    if cmd_type == "size":
        return [l for l in listings if (l.get("area_sqm") or 0) >= arg]

    if cmd_type == "plan":
        min_rank = _fp_rank(arg)
        if min_rank < 0:
            return []
        return [l for l in listings if _fp_rank(l.get("floor_plan") or "") >= min_rank]

    if cmd_type == "from":
        try:
            since = datetime.strptime(arg, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return []
        result = []
        for l in listings:
            fs = l.get("first_seen")
            if not fs:
                continue
            try:
                dt = datetime.fromisoformat(str(fs).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= since:
                    result.append(l)
            except (ValueError, TypeError):
                pass
        return result

    return listings


# ---------------------------------------------------------------------------
# Response sending
# ---------------------------------------------------------------------------

def _send(bot_token: str, chat_id: str, text: str) -> None:
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
    except Exception as exc:
        logger.warning("Command reply failed: %s", exc)


def _send_results(bot_token: str, chat_id: str, cmd_type: str, arg, results: list) -> None:
    """
    Send a header message then one message per listing (up to MAX_RESULTS).
    Sending listings individually avoids Telegram's 4096-char per-message limit.
    """
    from notifications.telegram_notify import _fmt_listing

    label_map = {
        "ward":  f"Ward: {arg}",
        "rent":  f"Base rent ≤ ¥{int(arg):,}",
        "size":  f"Area ≥ {arg:g} m²",
        "plan":  f"Floor plan ≥ {str(arg).upper()}",
        "from":  f"Active since {arg[:4]}-{arg[4:6]}-{arg[6:]}",
    }
    label = label_map.get(cmd_type, cmd_type)
    total = len(results)
    shown = results[:MAX_RESULTS]

    header = f"🔍 <b>{label}</b> — {total} listing{'s' if total != 1 else ''} found"
    if total > MAX_RESULTS:
        header += f"\n<i>Showing first {MAX_RESULTS} of {total}</i>"
    if total == 0:
        header += "\n\nNo active listings match this query."
    _send(bot_token, chat_id, header)

    for listing in shown:
        _send(bot_token, chat_id, _fmt_listing(listing))


# ---------------------------------------------------------------------------
# Offset persistence (survives CI cache restores)
# ---------------------------------------------------------------------------

def _load_offset() -> int:
    try:
        return int(OFFSET_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return 0


def _save_offset(offset: int) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        OFFSET_FILE.write_text(str(offset))
    except OSError as exc:
        logger.warning("Could not save telegram offset: %s", exc)


# ---------------------------------------------------------------------------
# Telegram getUpdates
# ---------------------------------------------------------------------------

def _get_updates(bot_token: str, offset: int, timeout: int = 20) -> list:
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{bot_token}/getUpdates",
            params={"offset": offset, "timeout": timeout, "allowed_updates": ["message"]},
            timeout=timeout + 5,
        )
        data = r.json()
        if data.get("ok"):
            return data.get("result", [])
    except Exception as exc:
        logger.debug("getUpdates error: %s", exc)
    return []


def _process_updates(bot_token: str, chat_id: str, updates: list) -> int:
    """
    Handle a batch of Telegram updates. Returns the next offset to use.
    Ignores updates from chats other than the configured chat_id.
    """
    next_offset = _load_offset()
    for update in updates:
        next_offset = update["update_id"] + 1
        msg = update.get("message", {})
        text = (msg.get("text") or "").strip()
        msg_chat_id = str(msg.get("chat", {}).get("id", ""))

        if msg_chat_id != str(chat_id):
            continue

        parsed = _parse_command(text)
        if not parsed:
            continue

        cmd_type, arg = parsed
        logger.info("Telegram command: \\%s %s", cmd_type, arg)
        listings = get_active_listings()
        results = _filter_listings(listings, cmd_type, arg)
        _send_results(bot_token, chat_id, cmd_type, arg, results)

    _save_offset(next_offset)
    return next_offset


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def handle_commands_once(bot_token: str, chat_id: str) -> None:
    """
    Process any commands that arrived since the last run (synchronous, one-shot).
    Designed for CI jobs: reads offset from data/telegram_offset.txt, processes
    pending updates, saves new offset so commands aren't repeated next run.
    """
    offset = _load_offset()
    updates = _get_updates(bot_token, offset, timeout=0)
    if updates:
        logger.info("Processing %d pending Telegram command(s).", len(updates))
        _process_updates(bot_token, chat_id, updates)
    else:
        logger.debug("No pending Telegram commands.")


def start_polling(bot_token: str, chat_id: str) -> None:
    """
    Start continuous long-poll command handling in a background daemon thread.
    No-op when running in CI (CI=true) — CI uses handle_commands_once() instead.
    """
    if os.environ.get("CI"):
        return

    def _loop() -> None:
        global _offset  # module-level only used within this thread
        offset = _load_offset()
        logger.info("Telegram command polling started (offset=%d).", offset)
        while True:
            try:
                updates = _get_updates(bot_token, offset, timeout=20)
                if updates:
                    offset = _process_updates(bot_token, chat_id, updates)
            except Exception as exc:
                logger.warning("Poll loop error: %s", exc)
                time.sleep(5)

    threading.Thread(target=_loop, daemon=True, name="tg-cmd-poll").start()
    logger.info("Telegram command handler started.")
