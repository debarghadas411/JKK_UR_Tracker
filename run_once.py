#!/usr/bin/env python3
"""
CI entry point — runs exactly one scrape/notify cycle then exits.

Designed for GitHub Actions (or any non-interactive environment).
Secrets are read from environment variables:
  TG_BOT_TOKEN  — Telegram bot token
  TG_CHAT_ID    — Telegram chat/group ID (integer, usually negative for groups)

Reads filters and other settings from config.public.yaml (committed, no secrets).
If config.yaml exists it is used instead (local override, git-ignored).
"""

import logging
import logging.handlers
import os
import sys

import yaml

from utils.paths import CONFIG_FILE, DATA_DIR, LOG_DIR, PROJECT_ROOT


def _load_config() -> dict:
    """Load config: prefer config.yaml (local), fall back to config.public.yaml (CI)."""
    public_cfg_path = PROJECT_ROOT / "config.public.yaml"

    if CONFIG_FILE.exists():
        path = CONFIG_FILE
    elif public_cfg_path.exists():
        path = public_cfg_path
    else:
        print("WARNING: No config.yaml or config.public.yaml found — using bare defaults.")
        return {}

    with path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    # Override Telegram credentials from environment variables when present.
    tg_token = os.environ.get("TG_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TG_CHAT_ID", "").strip()
    if tg_token and tg_chat:
        cfg.setdefault("telegram", {})
        cfg["telegram"]["enabled"] = True
        cfg["telegram"]["bot_token"] = tg_token
        cfg["telegram"]["chat_id"] = tg_chat
        # No daily digest in CI — digest is scheduled locally.
        cfg["telegram"].setdefault("digest_time", "")
        cfg["telegram"].setdefault("only_filtered_matches", False)

    return cfg


def _setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "jkk_tracker.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(sh)


def main() -> None:
    _setup_logging()
    logger = logging.getLogger(__name__)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    cfg = _load_config()

    # Inject config into main module before importing run_check.
    import main as tracker_main
    tracker_main._config = cfg

    from storage.database import init_db
    init_db()

    tracker_main.load_digest_stats()

    from storage.geocoder import load_geocode_seed
    load_geocode_seed()

    logger.info("run_once: starting single check cycle (CI=%s)", os.environ.get("CI", "false"))
    tracker_main.run_check()

    # Process any Telegram commands accumulated since the last run.
    tg_cfg = cfg.get("telegram", {})
    if tg_cfg.get("enabled") and tg_cfg.get("bot_token") and tg_cfg.get("chat_id"):
        from notifications.telegram_commands import handle_commands_once
        handle_commands_once(tg_cfg["bot_token"], str(tg_cfg["chat_id"]))

    logger.info("run_once: cycle complete — exiting.")


if __name__ == "__main__":
    main()
