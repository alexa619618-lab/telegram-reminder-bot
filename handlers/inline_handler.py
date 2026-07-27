"""
Inline mode handler — allows users to create reminders from any chat.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

import pytz
from aiogram import Router
from aiogram.types import (
    ChosenInlineResult,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from config import config
from models.reminder import RepeatType
from parser import parse_message
from utils.jalali import jalali_datetime_str
from utils.reminder_utils import apply_default_time

logger = logging.getLogger(__name__)
router = Router()


@router.inline_query()
async def inline_query_handler(query: InlineQuery) -> None:
    """
    When user types @botname <text>, parse it and offer a result card.
    """
    from database import AsyncSessionFactory
    from services.user_service import UserService

    text = (query.query or "").strip()
    tg_user = query.from_user

    if not text:
        await query.answer(
            results=[],
            cache_time=1,
            switch_pm_text="یادآوری بنویس...",
            switch_pm_parameter="start",
        )
        return

    # Get user settings
    async with AsyncSessionFactory() as session:
        svc = UserService(session)
        db_user = await svc.get_or_create(
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )
        await session.commit()
        tz = db_user.timezone
        default_time = db_user.default_reminder_time if db_user.default_time_enabled else None

    result = parse_message(text, tz)

    if result.time_found and result.text_found:
        remind_at = result.remind_at
        # Apply default time if no explicit clock given
        if default_time and "ساعت" not in text and ":" not in text:
            remind_at = apply_default_time(remind_at, default_time, tz)

        dt_str = jalali_datetime_str(remind_at, tz)
        body = result.text or text
        repeat_info = ""
        if result.repeat_type != RepeatType.NONE:
            repeat_info = f"\n🔁 تکرارشونده"

        result_id = f"full_{uuid.uuid4().hex[:8]}"
        article = InlineQueryResultArticle(
            id=result_id,
            title="✅ ثبت یادآوری",
            description=f"{body} — {dt_str}",
            input_message_content=InputTextMessageContent(
                message_text=(
                    f"⏰ *یادآوری ثبت شد*\n\n"
                    f"📝 {body}\n"
                    f"📅 {dt_str}{repeat_info}"
                ),
                parse_mode="Markdown",
            ),
        )
        await query.answer([article], cache_time=5)

    elif result.time_found:
        remind_at = result.remind_at
        if default_time:
            remind_at = apply_default_time(remind_at, default_time, tz)
        dt_str = jalali_datetime_str(remind_at, tz)
        article = InlineQueryResultArticle(
            id="time_only",
            title="⏰ زمان یافت شد — متن چیه؟",
            description=f"زمان: {dt_str} — متن رو هم بنویس",
            input_message_content=InputTextMessageContent(
                message_text=f"⏰ زمان: {dt_str}\nبرای تکمیل یادآوری به ربات بیا 👆"
            ),
        )
        await query.answer([article], cache_time=5)

    elif result.text_found:
        if default_time:
            # Schedule for tomorrow at default time
            local_tz = pytz.timezone(tz)
            now = datetime.now(local_tz)
            tomorrow = (now + timedelta(days=1)).replace(second=0, microsecond=0)
            remind_at = apply_default_time(tomorrow, default_time, tz)
            dt_str = jalali_datetime_str(remind_at, tz)
            body = result.text or text

            article = InlineQueryResultArticle(
                id=f"text_default_{uuid.uuid4().hex[:8]}",
                title=f"✅ ثبت با زمان پیش‌فرض ({default_time})",
                description=f"{body} — فردا {default_time}",
                input_message_content=InputTextMessageContent(
                    message_text=(
                        f"⏰ *یادآوری ثبت شد*\n\n"
                        f"📝 {body}\n"
                        f"📅 {dt_str}"
                    ),
                    parse_mode="Markdown",
                ),
            )
            await query.answer([article], cache_time=5)
        else:
            article = InlineQueryResultArticle(
                id="text_only",
                title="📝 متن دریافت شد — زمان لازم است",
                description="برای ثبت، زمان رو هم مشخص کن",
                input_message_content=InputTextMessageContent(
                    message_text="برای ثبت یادآوری با زمان کامل، به ربات بیا 👆"
                ),
            )
            await query.answer([article], cache_time=5)
    else:
        await query.answer(
            results=[],
            cache_time=1,
            switch_pm_text="یادآوری رو کامل‌تر بنویس...",
            switch_pm_parameter="start",
        )


@router.chosen_inline_result()
async def chosen_inline_result(chosen: ChosenInlineResult, bot) -> None:
    """
    When user selects an inline result, save the reminder in DB and schedule it.
    """
    from database import AsyncSessionFactory
    from services.user_service import UserService
    from services.reminder_service import ReminderService
    from scheduler import schedule_reminder

    tg_user = chosen.from_user
    text_input = chosen.query or ""

    reminder = None
    tz = "Asia/Tehran"
    db_user_id = None
    body = text_input

    try:
        async with AsyncSessionFactory() as session:
            user_svc = UserService(session)
            db_user = await user_svc.get_or_create(
                telegram_id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
            )
            await session.commit()

            tz = db_user.timezone
            default_time = db_user.default_reminder_time if db_user.default_time_enabled else None

            try:
                result = parse_message(text_input, tz)
            except Exception as parse_exc:
                logger.warning(
                    "Inline: parse_message failed for user %s input %r: %s",
                    tg_user.id, text_input[:80], parse_exc,
                )
                return

            if not result.time_found:
                if default_time:
                    local_tz = pytz.timezone(tz)
                    now = datetime.now(local_tz)
                    tomorrow = (now + timedelta(days=1)).replace(second=0, microsecond=0)
                    remind_at = apply_default_time(tomorrow, default_time, tz)
                else:
                    logger.info("Inline: no time found and no default — skipping save")
                    return
            else:
                remind_at = result.remind_at
                if default_time and "ساعت" not in text_input and ":" not in text_input:
                    remind_at = apply_default_time(remind_at, default_time, tz)

            body = result.text or text_input

            rem_svc = ReminderService(session)
            reminder = await rem_svc.create(
                user_id=db_user.id,
                text=body,
                remind_at=remind_at,
                repeat_type=result.repeat_type,
                repeat_interval=result.repeat_interval,
                weekday=result.weekday,
                via_inline=True,
            )
            await session.commit()
            db_user_id = db_user.telegram_id

    except Exception as exc:
        logger.exception("Inline chosen_result: unhandled error for user %s: %s", tg_user.id, exc)
        return

    # Schedule outside the session context
    if reminder is not None:
        schedule_reminder(bot, reminder)
        logger.info("Inline reminder saved & scheduled: id=%s for user=%s", reminder.id, tg_user.id)

        # Try to send confirmation to the user's private chat
        try:
            from utils.jalali import jalali_datetime_str
            dt_str = jalali_datetime_str(reminder.remind_at, tz)
            await bot.send_message(
                chat_id=db_user_id,
                text=f"✅ یادآوری از Inline ثبت شد!\n\n📝 {body}\n📅 {dt_str}",
            )
        except Exception:
            pass  # User may not have started the bot
