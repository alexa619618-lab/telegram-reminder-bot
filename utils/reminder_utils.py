"""
Shared utility helpers for reminder display and time handling.

Centralises logic that was previously duplicated across message_handler,
callback_handler, and inline_handler.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

import pytz

from models.reminder import RepeatType

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Repeat-type labels
# ---------------------------------------------------------------------------

_REPEAT_LABELS: dict[RepeatType, str] = {
    RepeatType.DAILY: "روزانه",
    RepeatType.WEEKLY: "هفتگی",
    RepeatType.MONTHLY: "ماهانه",
    RepeatType.YEARLY: "سالانه",
    RepeatType.EVERY_N_HOURS: "هر {n} ساعت",
    RepeatType.EVERY_N_MINUTES: "هر {n} دقیقه",
    RepeatType.EVERY_N_DAYS: "هر {n} روز",
    RepeatType.EVERY_N_WEEKS: "هر {n} هفته",
    RepeatType.WEEKDAY: "هر هفته",
    RepeatType.NONE: "",
}


def format_repeat_label(repeat_type: RepeatType, interval: int | None = None) -> str:
    """Return a human-readable Farsi label for a repeat type."""
    label = _REPEAT_LABELS.get(repeat_type, "")
    if "{n}" in label and interval:
        label = label.format(n=interval)
    return label


# ---------------------------------------------------------------------------
# Default-time helper
# ---------------------------------------------------------------------------

def apply_default_time(dt: datetime, time_str: str, tz: str) -> datetime:
    """
    Apply a user's default HH:MM to the date part of *dt*.

    Returns *dt* unchanged if *time_str* or *tz* cannot be parsed so that
    callers never receive an exception from this helper.
    """
    try:
        h, m = map(int, time_str.split(":"))
        local_tz = pytz.timezone(tz)
        local = dt.astimezone(local_tz).replace(hour=h, minute=m, second=0, microsecond=0)
        return local.astimezone(pytz.utc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("apply_default_time failed (time_str=%r tz=%r): %s", time_str, tz, exc)
        return dt


# ---------------------------------------------------------------------------
# Today-count helper
# ---------------------------------------------------------------------------

async def get_today_count(user_id: int, tz: str, session: "AsyncSession") -> int:
    """
    Return the number of pending/snoozed reminders due today for *user_id*.

    Never raises — returns 0 on any error so callers can safely use the
    result as a button label without extra guards.
    """
    try:
        from services.reminder_service import ReminderService
        svc = ReminderService(session)
        return await svc.count_today_by_user(user_id, tz)
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_today_count failed for user_id=%s: %s", user_id, exc)
        return 0
