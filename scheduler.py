"""
APScheduler integration.

- AsyncIOScheduler runs in the event loop.
- On startup all PENDING reminders from the DB are re-loaded.
- Reminder notifications are sent via the bot instance.
- Daily agenda jobs are loaded on startup and managed per-user.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from config import config
from database import AsyncSessionFactory
from models.reminder import Reminder, RepeatType
from utils.jalali import jalali_datetime_str

if TYPE_CHECKING:
    from aiogram import Bot

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=config.SCHEDULER_TIMEZONE)


# ---------------------------------------------------------------------------
# Sending logic — regular reminders
# ---------------------------------------------------------------------------

async def _send_reminder(bot: "Bot", reminder_id: int) -> None:
    """Called by APScheduler when a reminder fires."""
    from keyboards.reminder_buttons import reminder_action_keyboard
    from services.reminder_service import ReminderService

    try:
        is_repeating = False

        async with AsyncSessionFactory() as session:
            svc = ReminderService(session)
            reminder = await svc.get_by_id(reminder_id)
            if reminder is None:
                logger.warning("Scheduler: reminder %s not found — skipping", reminder_id)
                return

            if reminder.status not in ("pending", "snoozed"):
                logger.info(
                    "Scheduler: reminder %s already handled (status=%s) — skipping",
                    reminder_id, reminder.status,
                )
                return

            is_repeating = reminder.repeat_type != RepeatType.NONE

            # Mark sent — also advances next occurrence for repeating reminders
            await svc.mark_sent(reminder)
            await session.commit()

            # Build message
            text_body = reminder.text or "(بدون متن)"
            jalali = jalali_datetime_str(datetime.now(pytz.timezone(config.TIMEZONE)))
            msg = f"🔔 *یادآوری*\n\n{text_body}\n\n🗓 {jalali}"

            # Fetch user's Telegram ID
            from models.user import User
            from sqlalchemy import select
            result = await session.execute(select(User).where(User.id == reminder.user_id))
            user = result.scalar_one_or_none()
            if user is None:
                logger.warning("Scheduler: user not found for reminder %s", reminder_id)
                return

            send_ok = True
            try:
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=msg,
                    parse_mode="Markdown",
                    reply_markup=reminder_action_keyboard(reminder.id),
                )
            except Exception as send_exc:
                logger.exception(
                    "Scheduler: failed to send reminder %s to user %s: %s",
                    reminder_id, user.telegram_id, send_exc,
                )
                send_ok = False

            # Always reschedule repeating reminders even if send failed —
            # otherwise the job is lost until the next bot restart.
            if is_repeating:
                schedule_reminder(bot, reminder)
            elif send_ok:
                _schedule_followup(bot, reminder_id)

    except Exception as exc:
        logger.exception("Scheduler: unhandled error in _send_reminder(%s): %s", reminder_id, exc)


async def _send_followup(bot: "Bot", reminder_id: int) -> None:
    """Smart Follow-Up: اگر کاربر واکنشی نشان نداد، یادآوری مجدد ارسال می‌شود."""
    from keyboards.reminder_buttons import reminder_action_keyboard
    from services.reminder_service import ReminderService
    from models.reminder import ReminderStatus

    try:
        async with AsyncSessionFactory() as session:
            svc = ReminderService(session)
            reminder = await svc.get_by_id(reminder_id)
            if reminder is None:
                logger.warning("Follow-up: reminder %s not found — skipping", reminder_id)
                return

            # فقط اگر status هنوز expired باشد (یعنی کاربر هیچ اقدامی نکرده)
            if reminder.status != ReminderStatus.EXPIRED:
                logger.info(
                    "Follow-up skipped for reminder %s (status=%s)", reminder_id, reminder.status
                )
                return

            text_body = reminder.text or "(بدون متن)"
            msg = f"⏰ *یادآوری مجدد*\n\nهنوز این کار رو انجام ندادی؟\n\n📝 {text_body}"

            from models.user import User
            from sqlalchemy import select
            result = await session.execute(select(User).where(User.id == reminder.user_id))
            user = result.scalar_one_or_none()
            if user is None:
                logger.warning("Follow-up: user not found for reminder %s", reminder_id)
                return

            try:
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=msg,
                    parse_mode="Markdown",
                    reply_markup=reminder_action_keyboard(reminder.id),
                )
                logger.info("Smart follow-up sent for reminder %s", reminder_id)
            except Exception as send_exc:
                logger.exception(
                    "Follow-up: failed to send for reminder %s to user %s: %s",
                    reminder_id, user.telegram_id, send_exc,
                )

    except Exception as exc:
        logger.exception("Follow-up: unhandled error for reminder %s: %s", reminder_id, exc)


def _schedule_followup(bot: "Bot", reminder_id: int) -> None:
    """Schedule a Smart Follow-Up job 1 hour after the original reminder fires."""
    job_id = f"rem_followup_{reminder_id}"
    followup_time = datetime.now(pytz.utc) + timedelta(hours=1)
    try:
        scheduler.add_job(
            _send_followup,
            trigger=DateTrigger(run_date=followup_time),
            args=[bot, reminder_id],
            id=job_id,
            replace_existing=True,
        )
        logger.info("Smart Follow-Up scheduled for reminder %s at %s", reminder_id, followup_time)
    except Exception as exc:
        logger.warning("Could not schedule follow-up for reminder %s: %s", reminder_id, exc)


# ---------------------------------------------------------------------------
# Scheduling helpers — regular reminders
# ---------------------------------------------------------------------------

def schedule_reminder(bot: "Bot", reminder: Reminder) -> None:
    """Add (or replace) an APScheduler job for this reminder."""
    job_id = f"rem_{reminder.id}"

    # Remove existing job if any
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass

    fire_time = reminder.remind_at
    if fire_time.tzinfo is None:
        fire_time = pytz.utc.localize(fire_time)

    # If the time is already past, fire in 5 seconds (for recovery on restart)
    if fire_time <= datetime.now(pytz.utc):
        fire_time = datetime.now(pytz.utc) + timedelta(seconds=5)

    try:
        scheduler.add_job(
            _send_reminder,
            trigger=DateTrigger(run_date=fire_time),
            args=[bot, reminder.id],
            id=job_id,
            replace_existing=True,
        )
        logger.info("Scheduled reminder %s at %s", reminder.id, fire_time)
    except Exception as exc:
        logger.error(
            "Failed to schedule reminder %s at %s: %s", reminder.id, fire_time, exc
        )


def cancel_reminder(reminder_id: int) -> None:
    """Remove APScheduler jobs (main + follow-up) for a reminder."""
    for job_id in [f"rem_{reminder_id}", f"rem_followup_{reminder_id}"]:
        try:
            scheduler.remove_job(job_id)
            logger.info("Cancelled scheduler job %s", job_id)
        except Exception:
            pass  # Job may not exist


async def load_pending_reminders(bot: "Bot") -> None:
    """On startup, re-schedule all pending/snoozed reminders from the DB."""
    from services.reminder_service import ReminderService

    async with AsyncSessionFactory() as session:
        svc = ReminderService(session)
        reminders = await svc.get_all_pending()
        logger.info("Loading %d pending reminders from database", len(reminders))
        for reminder in reminders:
            schedule_reminder(bot, reminder)


# ---------------------------------------------------------------------------
# Daily agenda
# ---------------------------------------------------------------------------

async def _send_daily_agenda(bot: "Bot", user_telegram_id: int, user_id: int, tz: str) -> None:
    """Send the daily agenda message to a user if they have reminders today."""
    from services.reminder_service import ReminderService

    async with AsyncSessionFactory() as session:
        svc = ReminderService(session)
        reminders = await svc.get_today_by_user(user_id, tz)

        # Only send if there are reminders today
        if not reminders:
            logger.info("Daily agenda: no reminders today for user %s — skipping", user_telegram_id)
            return

        # Build the agenda message
        local_tz = pytz.timezone(tz)
        lines = ["☀️ *برنامه امروز*\n"]
        for rem in reminders:
            local_dt = rem.remind_at.astimezone(local_tz)
            time_str = local_dt.strftime("%H:%M")
            text_preview = (rem.text or "(بدون متن)")[:50]
            lines.append(f"🕐 {time_str}  {text_preview}")

        msg = "\n".join(lines)

        try:
            await bot.send_message(
                chat_id=user_telegram_id,
                text=msg,
                parse_mode="Markdown",
            )
            logger.info("Daily agenda sent to user %s (%d reminders)", user_telegram_id, len(reminders))
        except Exception as exc:
            logger.exception("Failed to send daily agenda to user %s: %s", user_telegram_id, exc)


def schedule_daily_agenda(bot: "Bot", user_id: int, telegram_id: int, agenda_time: str, tz: str) -> None:
    """
    Schedule (or replace) the daily agenda job for a specific user.
    agenda_time: HH:MM string (local time in user's timezone)
    """
    job_id = f"daily_agenda_{user_id}"

    # Cancel any existing job first
    cancel_daily_agenda(user_id)

    try:
        hour, minute = map(int, agenda_time.split(":"))
        trigger = CronTrigger(hour=hour, minute=minute, timezone=tz)
        scheduler.add_job(
            _send_daily_agenda,
            trigger=trigger,
            args=[bot, telegram_id, user_id, tz],
            id=job_id,
            replace_existing=True,
        )
        logger.info(
            "Daily agenda scheduled for user %s at %s (%s)", telegram_id, agenda_time, tz
        )
    except Exception as exc:
        logger.warning("Could not schedule daily agenda for user %s: %s", user_id, exc)


def cancel_daily_agenda(user_id: int) -> None:
    """Remove the daily agenda job for a user."""
    job_id = f"daily_agenda_{user_id}"
    try:
        scheduler.remove_job(job_id)
        logger.info("Cancelled daily agenda job for user %s", user_id)
    except Exception:
        pass  # Job may not exist


async def load_daily_agenda_jobs(bot: "Bot") -> None:
    """On startup, re-schedule daily agenda jobs for all users who have it enabled."""
    from services.user_service import UserService

    async with AsyncSessionFactory() as session:
        svc = UserService(session)
        users = await svc.get_all_with_daily_agenda()
        logger.info("Loading daily agenda jobs for %d users", len(users))
        for user in users:
            schedule_daily_agenda(
                bot,
                user_id=user.id,
                telegram_id=user.telegram_id,
                agenda_time=user.daily_agenda_time,
                tz=user.timezone,
            )
