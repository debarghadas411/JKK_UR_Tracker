"""
macOS notification module — displays pop-up dialogs via osascript.

Priority alerts (filter matches) use the "caution" icon.
Background alerts (any other change) use the "note" icon.
Dialogs run in a background thread so they never block the scheduler.
"""

import logging
import subprocess
import threading
from typing import Optional

from storage.translations import normalize_floor_plan, translate_ward

logger = logging.getLogger(__name__)


def _run_dialog(title: str, message: str, icon: str = "note") -> None:
    """Execute the osascript dialog command synchronously (called from a thread)."""
    # Escape double quotes inside the message/title to avoid syntax errors
    safe_title = title.replace('"', '\\"')
    safe_message = message.replace('"', '\\"')

    script = (
        f'display dialog "{safe_message}" '
        f'with title "{safe_title}" '
        f'buttons {{"OK"}} default button "OK" '
        f'with icon {icon}'
    )
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=300)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.warning("osascript dialog failed: %s", exc)


def show_dialog(title: str, message: str, is_priority: bool = False) -> None:
    """
    Show a macOS dialog in a non-blocking background thread.

    Args:
        title:       Dialog window title.
        message:     Body text shown in the dialog.
        is_priority: If True, uses the caution (⚠) icon; otherwise note (ℹ) icon.
    """
    icon = "caution" if is_priority else "note"
    thread = threading.Thread(
        target=_run_dialog,
        args=(title, message, icon),
        daemon=True,
        name=f"dialog-{'priority' if is_priority else 'bg'}",
    )
    thread.start()
    logger.debug("Dialog launched (priority=%s): %s", is_priority, title)


def notify_changes(
    change_report: dict,
    notify_all: bool = True,
    notify_filtered: bool = True,
    priority_changes: Optional[dict] = None,
) -> None:
    """
    High-level notification dispatcher.

    Args:
        change_report:    Full change report {"new": [...], "removed": [...], "updated": [...]}
        notify_all:       If True, send a background popup for any change.
        notify_filtered:  If True, send a priority popup for filter-matching changes.
        priority_changes: Subset of change_report that matches user filters (or None).
    """
    total_new     = len(change_report.get("new", []))
    total_removed = len(change_report.get("removed", []))
    total_updated = len(change_report.get("updated", []))
    total         = total_new + total_removed + total_updated

    if total == 0:
        return

    # Priority notification: filter-matching changes
    if notify_filtered and priority_changes:
        p_new = len(priority_changes.get("new", []))
        p_rem = len(priority_changes.get("removed", []))
        p_upd = len(priority_changes.get("updated", []))

        if p_new + p_rem + p_upd > 0:
            lines = ["Listings matching your filters changed:\n"]
            if p_new:
                lines.append(f"✅ New ({p_new}):")
                for lst in priority_changes["new"][:5]:
                    lines.append(_listing_summary(lst))
                if p_new > 5:
                    lines.append(f"    … and {p_new - 5} more")
            if p_rem:
                lines.append(f"\n❌ Removed ({p_rem}):")
                for lst in priority_changes["removed"][:5]:
                    lines.append(_listing_summary(lst))
                if p_rem > 5:
                    lines.append(f"    … and {p_rem - 5} more")
            if p_upd:
                lines.append(f"\n🔄 Updated: {p_upd} listing(s)")

            show_dialog("JKK + UR Tracker — Filter Match ⚠", "\n".join(lines), is_priority=True)

    # Background notification: any change
    if notify_all and total > 0:
        summary = "  ".join(filter(None, [
            f"✅ {total_new} new"      if total_new     else None,
            f"❌ {total_removed} removed" if total_removed else None,
            f"🔄 {total_updated} updated" if total_updated else None,
        ]))
        lines = [summary, ""]

        if total_new:
            lines.append("New:")
            for lst in change_report["new"][:3]:
                lines.append(_listing_summary(lst))
            if total_new > 3:
                lines.append(f"    … and {total_new - 3} more")

        if total_removed:
            lines.append("\nRemoved:")
            for lst in change_report["removed"][:3]:
                lines.append(_listing_summary(lst))
            if total_removed > 3:
                lines.append(f"    … and {total_removed - 3} more")

        show_dialog("JKK + UR Tracker — Listings Updated", "\n".join(lines), is_priority=False)


def _listing_summary(listing: dict) -> str:
    """One-line summary of a listing for use inside a macOS dialog."""
    source = listing.get("source", "JKK")
    name   = listing.get("name", "Unknown")
    ward   = translate_ward(listing.get("ward", ""))
    fp     = normalize_floor_plan(listing.get("floor_plan", ""))
    area   = listing.get("area_sqm")
    rent   = listing.get("rent_yen")

    detail = "  ".join(filter(None, [
        fp,
        f"{area} m²" if area else None,
        f"¥{rent:,}/mo" if rent else None,
    ]))
    ward_str = f"  —  {ward}" if ward else ""
    return f"    • [{source}] {name}{ward_str}    {detail}".rstrip()
