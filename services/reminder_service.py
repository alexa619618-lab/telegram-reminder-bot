"""
Repository pattern for Reminder CRUD operations.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import calendar as _cal
import pytz
from sqlalchemy import and_, func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.reminder import Reminder, ReminderStatus, RepeatType
from models.history import ReminderHistory

logger = logging.getLogger(__name__)


class ReminderService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        user_id: int,
        text: str,
        remind_at: datetime,
        repeat_type: RepeatType = RepeatType.NONE,
        repeat_interval: Optional[int] = None,
        weekday: Optional[int] = None,
        original_message_id: Optional[int] = None,
        original_chat_id: Optional[int] = None,
        via_inline: bool = False,
    ) -> Reminder:
        reminder = Reminder(
            user_id=user_id,
            text=text,
            remind_at=remind_at,
            repeat_type=repeat_type,
            repeat_interval=repeat_interval,
            original_message_id=original_message_id,
            original_chat_id=original_chat_id,
            via_inline=via_inline,
        )
        # For weekday repeats, store the weekday in repeat_interval
        if repeat_type == RepeatType.WEEKDAY and weekday is not None:
            reminder.repeat_interval = weekday

        self._session.add(reminder)
        await self._session.flush()
        logger.info("Created reminder id=%s for user_id=%s at %s", reminder.id, user_id, remind_at)
        return reminder

    async def get_by_id(self, reminder_id: int) -> Optional[Reminder]:
        stmt = (
            select(Reminder)
            .where(Reminder.id == reminder_id)
            .options(selectinload(Reminder.attachments))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_by_user(self, user_id: int) -> list[Reminder]:
        """Get all non-cancelled, non-expired reminders for a user, ordered by remind_at."""
        stmt = (
            select(Reminder)
            .where(
                and_(
                    Reminder.user_id == user_id,
                    Reminder.status.in_([ReminderStatus.PENDING, ReminderStatus.SNOOZED]),
                )
            )
            .order_by(Reminder.remind_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_by_user(self, user_id: int, limit: int = 50) -> list[Reminder]:
        """Get all reminders for a user (for history view)."""
        stmt = (
            select(Reminder)
            .where(Reminder.user_id == user_id)
            .order_by(Reminder.remind_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_today_by_user(self, user_id: int, tz: str = "Asia/Tehran") -> list[Reminder]:
        """Get pending/snoozed reminders scheduled for today (in user's timezone)."""
        local_tz = pytz.timezone(tz)
        now_local = datetime.now(local_tz)
        today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc)
        today_end = today_start + timedelta(days=1)

        stmt = (
            select(Reminder)
            .where(
                and_(
                    Reminder.user_id == user_id,
                    Reminder.remind_at >= today_start,
                    Reminder.remind_at < today_end,
                    Reminder.status.in_([ReminderStatus.PENDING, ReminderStatus.SNOOZED]),
                )
            )
            .order_by(Reminder.remind_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_today_by_user(self, user_id: int, tz: str = "Asia/Tehran") -> int:
        """Count pending/snoozed reminders for today (for the dynamic button label)."""
        local_tz = pytz.timezone(tz)
        now_local = datetime.now(local_tz)
        today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc)
        today_end = today_start + timedelta(days=1)

        stmt = (
            select(sa_func.count())
            .select_from(Reminder)
            .where(
                and_(
                    Reminder.user_id == user_id,
                    Reminder.remind_at >= today_start,
                    Reminder.remind_at < today_end,
                    Reminder.status.in_([ReminderStatus.PENDING, ReminderStatus.SNOOZED]),
                )
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def get_tomorrow_by_user(self, user_id: int, tz: str = "Asia/Tehran") -> list[Reminder]:
        """Get all pending reminders for tomorrow (in user's timezone)."""
        local_tz = pytz.timezone(tz)
        now_local = datetime.now(local_tz)
        tomorrow_start = (now_local + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).astimezone(pytz.utc)
        tomorrow_end = tomorrow_start + timedelta(days=1)

        stmt = (
            select(Reminder)
            .where(
                and_(
                    Reminder.user_id == user_id,
                    Reminder.remind_at >= tomorrow_start,
                    Reminder.remind_at < tomorrow_end,
                    Reminder.status.in_([ReminderStatus.PENDING, ReminderStatus.SNOOZED]),
                )
            )
            .order_by(Reminder.remind_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_this_week_by_user(self, user_id: int, tz: str = "Asia/Tehran") -> list[Reminder]:
        """Get pending reminders for the rest of this week (today+1 through end of week)."""
        local_tz = pytz.timezone(tz)
        now_local = datetime.now(local_tz)

        # Start from tomorrow
        week_start = (now_local + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).astimezone(pytz.utc)

        # End at end of Sunday (6 days from start of this week)
        # Find end of current week (Saturday in Iran = weekday 5 in Python = Saturday)
        # We use 7 days from now to be simple and include full week
        week_end = (now_local + timedelta(days=7)).replace(
            hour=23, minute=59, second=59, microsecond=0
        ).astimezone(pytz.utc)

        stmt = (
            select(Reminder)
            .where(
                and_(
                    Reminder.user_id == user_id,
                    Reminder.remind_at >= week_start,
                    Reminder.remind_at <= week_end,
                    Reminder.status.in_([ReminderStatus.PENDING, ReminderStatus.SNOOZED]),
                )
            )
            .order_by(Reminder.remind_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_recurring_by_user(self, user_id: int) -> list[Reminder]:
        """Get all recurring (repeat_type != NONE) pending reminders for a user."""
        stmt = (
            select(Reminder)
            .where(
                and_(
                    Reminder.user_id == user_id,
                    Reminder.repeat_type != RepeatType.NONE,
                    Reminder.status.in_([ReminderStatus.PENDING, ReminderStatus.SNOOZED]),
                )
            )
            .order_by(Reminder.remind_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_pending(self) -> list[Reminder]:
        """Get all pending/snoozed reminders (for scheduler reload on startup)."""
        stmt = select(Reminder).where(
            Reminder.status.in_([ReminderStatus.PENDING, ReminderStatus.SNOOZED])
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_sent(self, reminder: Reminder) -> Reminder:
        """Mark as sent; advance next_occurrence for repeating reminders."""
        if reminder.repeat_type != RepeatType.NONE:
            reminder.remind_at = self._next_occurrence(reminder)
            reminder.status = ReminderStatus.PENDING
        else:
            reminder.status = ReminderStatus.EXPIRED
        await self._add_history(reminder, "sent")
        await self._session.flush()
        return reminder

    async def mark_done(self, reminder: Reminder) -> Reminder:
        reminder.status = ReminderStatus.DONE
        await self._add_history(reminder, "done")
        await self._session.flush()
        return reminder

    async def mark_cancelled(self, reminder: Reminder) -> Reminder:
        reminder.status = ReminderStatus.CANCELLED
        await self._add_history(reminder, "cancelled")
        await self._session.flush()
        return reminder

    async def snooze(self, reminder: Reminder, new_time: datetime) -> Reminder:
        reminder.remind_at = new_time
        reminder.status = ReminderStatus.SNOOZED
        await self._add_history(reminder, "snoozed")
        await self._session.flush()
        return reminder

    # ------------------------------------------------------------------
    # Edit methods
    # ------------------------------------------------------------------

    async def update_text(self, reminder: Reminder, new_text: str) -> Reminder:
        """Update the reminder body text without creating a new reminder."""
        reminder.text = new_text
        reminder.updated_at = datetime.now(pytz.utc)
        await self._add_history(reminder, "edited_text")
        await self._session.flush()
        logger.info("Updated text for reminder id=%s", reminder.id)
        return reminder

    async def update_time(
        self,
        reminder: Reminder,
        new_remind_at: datetime,
        new_repeat_type: Optional[RepeatType] = None,
        new_repeat_interval: Optional[int] = None,
    ) -> Reminder:
        """Update the reminder time (and optionally repeat) without creating a new reminder."""
        reminder.remind_at = new_remind_at
        reminder.updated_at = datetime.now(pytz.utc)
        if new_repeat_type is not None:
            reminder.repeat_type = new_repeat_type
        if new_repeat_interval is not None:
            reminder.repeat_interval = new_repeat_interval
        # Re-activate if it was snoozed or expired
        if reminder.status in (ReminderStatus.SNOOZED, ReminderStatus.EXPIRED):
            reminder.status = ReminderStatus.PENDING
        await self._add_history(reminder, "edited_time")
        await self._session.flush()
        logger.info("Updated time for reminder id=%s to %s", reminder.id, new_remind_at)
        return reminder

    async def update_scheduler_job_id(self, reminder: Reminder, job_id: str) -> None:
        reminder.scheduler_job_id = job_id
        await self._session.flush()

    async def _add_history(self, reminder: Reminder, action: str) -> None:
        entry = ReminderHistory(reminder_id=reminder.id, action=action)
        self._session.add(entry)
        await self._session.flush()

    @staticmethod
    def _next_occurrence(reminder: Reminder) -> datetime:
        """Calculate the next fire time for a repeating reminder."""
        current = reminder.remind_at
        rt = reminder.repeat_type
        n = reminder.repeat_interval or 1

        if rt == RepeatType.EVERY_N_MINUTES:
            return current + timedelta(minutes=n)
        if rt == RepeatType.EVERY_N_HOURS:
            return current + timedelta(hours=n)
        if rt == RepeatType.DAILY:
            return current + timedelta(days=1)
        if rt == RepeatType.EVERY_N_DAYS:
            return current + timedelta(days=n)
        if rt == RepeatType.WEEKLY:
            return current + timedelta(weeks=1)
        if rt == RepeatType.EVERY_N_WEEKS:
            return current + timedelta(weeks=n)
        if rt == RepeatType.WEEKDAY:
            return current + timedelta(weeks=1)
        if rt == RepeatType.MONTHLY:
            # Same day next month (day clamped to month length)
            month = current.month + 1 if current.month < 12 else 1
            year = current.year if current.month < 12 else current.year + 1
            day = min(current.day, _cal.monthrange(year, month)[1])
            return current.replace(year=year, month=month, day=day)
        if rt == RepeatType.EVERY_N_MONTHS:
            # Advance N months (day clamped)
            total_months = current.month - 1 + n
            year = current.year + total_months // 12
            month = total_months % 12 + 1
            day = min(current.day, _cal.monthrange(year, month)[1])
            return current.replace(year=year, month=month, day=day)
        if rt == RepeatType.YEARLY:
            return current.replace(year=current.year + 1)

        return current + timedelta(days=1)  # fallback
