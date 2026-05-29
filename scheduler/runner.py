"""
Scheduler wrapper: runs the check job at a configurable interval.

Wraps the job in a try/except so transient errors never crash the loop.
"""

import logging
import time
from typing import Callable

import schedule

logger = logging.getLogger(__name__)

_POLL_SECONDS = 30  # how often the main loop wakes to check for pending jobs


def start(job_fn: Callable, interval_minutes: int) -> None:
    """
    Schedule job_fn to run every interval_minutes minutes, then loop forever.

    Runs job_fn once immediately on startup before entering the loop.
    """
    logger.info("Scheduler starting. Interval: every %d minute(s).", interval_minutes)

    # First run immediately
    _safe_run(job_fn)

    schedule.every(interval_minutes).minutes.do(_safe_run, job_fn)

    while True:
        schedule.run_pending()
        time.sleep(_POLL_SECONDS)


def schedule_daily(job_fn: Callable, time_str: str) -> None:
    """
    Register job_fn to run once per day at time_str (HH:MM, 24-hour, server local time).

    Raises schedule.ScheduleValueError if time_str is not a valid HH:MM string.
    Must be called before the start() loop begins, or the job will be picked up on
    the next schedule.run_pending() iteration.
    """
    schedule.every().day.at(time_str).do(_safe_run, job_fn)
    logger.info("Daily digest scheduled at %s (server local time).", time_str)


def schedule_every_hours(job_fn: Callable, hours: int) -> None:
    """Register job_fn to run every `hours` hours."""
    schedule.every(hours).hours.do(_safe_run, job_fn)
    logger.info("Job scheduled every %d hour(s).", hours)


def _safe_run(fn: Callable) -> None:
    """Execute fn and catch all exceptions so the scheduler loop keeps running."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        logger.error("Check cycle failed with unhandled exception: %s", exc, exc_info=True)
