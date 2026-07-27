"""
Main message handler — handles all text messages and forwarded messages.
Uses a state machine for multi-turn conversations.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import pytz
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config import config
from keyboards.main_menu import cancel_keyboard, main_menu_keyboard
from keyboards.reminder_buttons import (
    confirm_reminder_keyboard,
    filter_keyboard,
    list_filter_button_keyboard,
    list_item_keyboard,
)
from keyboards.settings_keyboard import (
    confirm_delete_keyboard,
    daily_agenda_keyboard,
    default_time_options_keyboard,
    forward_behavior_keyboard,
    settings_main_keyboard,
)
from models.reminder import RepeatType
from models.user import User
from parser import parse_message, parse_multi
from scheduler import cancel_reminder, schedule_reminder
from services.reminder_service import ReminderService
from services.user_service import UserService
from states import ForwardReminder, ReminderCreation, ReminderEdit, ReminderList, Settings
from utils.jalali import jalali_datetime_str
from utils.reminder_utils import apply_default_time, format_repeat_label, get_today_count

logger = logging.getLogger(__name__)
router = Router()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_explicit_time(text: str) -> bool:
    """Check if the text contains an explicit clock time."""
    return "ساعت" in text or ":" in text


# Persian word-to-int map for standalone time words (یک, دو, … بیست و سه)
_PERSIAN_WORD_HOURS: dict[str, int] = {
    "یک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5,
    "شش": 6, "هفت": 7, "هشت": 8, "نه": 9, "ده": 10,
    "یازده": 11, "دوازده": 12, "سیزده": 13, "چهارده": 14,
    "پانزده": 15, "شانزده": 16, "هفده": 17, "هجده": 18,
    "نوزده": 19, "بیست": 20,
    "بیست و یک": 21, "بیست و دو": 22, "بیست و سه": 23,
}


def _parse_time_shorthand(text: str, tz: str) -> datetime | None:
    """
    Resolve a bare time shorthand that parse_message() cannot handle alone.

    Accepts:
    • Pure digit / Persian digit: "9"، "۹"، "12"، "21"
    • H:MM / HH:MM:  "9:30"، "۹:۳۰"
    • Persian word numbers: "هشت"، "ده"، "نه"، "بیست و یک"

    Smart AM/PM for ambiguous hours (1-12):
    • Tries `hour` as-is first  →  if that moment is still in the future, use it
    • Else tries `hour + 12`    →  if that's in the future, use it
    • Else schedules for next day at `hour:00`

    Examples at 10:00 local:
        "9"  → 21:00 today  (09:00 already past)
        "11" → 11:00 today  (still ahead)
        "12" → 12:00 today  (still ahead)
        "21" → 21:00 today  (unambiguous, still ahead)
        "هشت" → 20:00 today  (08:00 already past)

    Returns UTC datetime or None if unresolvable.
    """
    from utils.jalali import from_persian_digits

    raw = text.strip()
    if not raw:
        return None

    local_tz = pytz.timezone(tz)
    now_local = datetime.now(local_tz)

    hour: int | None = None
    minute: int = 0

    # 1. Try Persian word numbers (longest match first to avoid "سه" inside "سیزده")
    for word, val in sorted(_PERSIAN_WORD_HOURS.items(), key=lambda x: -len(x[0])):
        if re.fullmatch(word, raw):
            hour = val
            break

    # 2. Try digit / Persian digit
    if hour is None:
        converted = from_persian_digits(raw)
        m_hm = re.fullmatch(r"(\d{1,2}):(\d{2})", converted)
        if m_hm:
            h_val, mn_val = int(m_hm.group(1)), int(m_hm.group(2))
            if 0 <= h_val <= 23 and 0 <= mn_val <= 59:
                hour, minute = h_val, mn_val
        else:
            m_h = re.fullmatch(r"(\d{1,2})", converted)
            if m_h:
                h_val = int(m_h.group(1))
                if 0 <= h_val <= 23:
                    hour = h_val

    if hour is None:
        return None

    # 3. Build the candidate datetime(s)
    def _make_local(h: int, mn: int) -> datetime:
        return now_local.replace(hour=h, minute=mn, second=0, microsecond=0)

    if 1 <= hour <= 12 and minute == 0:
        # Ambiguous: could be AM or PM
        am_dt = _make_local(hour, 0)
        pm_dt = _make_local(hour + 12, 0) if hour + 12 <= 23 else None

        if am_dt > now_local:
            chosen = am_dt
        elif pm_dt and pm_dt > now_local:
            chosen = pm_dt
        else:
            chosen = am_dt + timedelta(days=1)
    else:
        # Unambiguous (0 or 13-23, or has explicit minutes)
        candidate = _make_local(hour, minute)
        if candidate <= now_local:
            candidate += timedelta(days=1)
        chosen = candidate

    return chosen.astimezone(pytz.utc)


# ---------------------------------------------------------------------------
# /start command
# ---------------------------------------------------------------------------

@router.message(Command("start"))
async def cmd_start(message: Message, db_user: User, session, state: FSMContext) -> None:
    await state.clear()
    name = db_user.first_name or "دوست"
    today_count = await get_today_count(db_user.id, db_user.timezone, session)
    await message.answer(
        f"سلام {name}! 👋\n\n"
        "من دستیار یادآوری شخصی توام.\n"
        "فقط کافیه بنویسی چی رو کِی یادآوری کنم:\n\n"
        "مثال:\n"
        "• فردا ساعت ۸ یادم بنداز برم بانک\n"
        "• شنبه صبح قبض برق رو پرداخت کن\n"
        "• ۲۰ دقیقه دیگه لباس‌ها رو دربیار\n"
        "• هر روز ساعت ۹ یادم بنداز آب بخورم\n",
        reply_markup=main_menu_keyboard(today_count),
    )


# ---------------------------------------------------------------------------
# Cancel (works from any state)
# ---------------------------------------------------------------------------

@router.message(F.text == "❌ لغو")
async def cancel_action(message: Message, db_user: User, session, state: FSMContext) -> None:
    current = await state.get_state()
    await state.clear()
    today_count = await get_today_count(db_user.id, db_user.timezone, session)
    if current:
        await message.answer(
            "❌ عملیات لغو شد.",
            reply_markup=main_menu_keyboard(today_count),
        )
    else:
        await message.answer("منوی اصلی:", reply_markup=main_menu_keyboard(today_count))


# ---------------------------------------------------------------------------
# Main menu buttons
# ---------------------------------------------------------------------------

@router.message(F.text == "📋 یادآورهای من")
async def list_reminders(message: Message, db_user: User, session, state: FSMContext) -> None:
    svc = ReminderService(session)
    reminders = await svc.get_pending_by_user(db_user.id)
    if not reminders:
        await message.answer("📭 هیچ یادآور فعالی ندارید.")
        return

    # Send header with single filter button — store its message_id for later edits
    header_msg = await message.answer(
        f"📋 *{len(reminders)} یادآور فعال*",
        parse_mode="Markdown",
        reply_markup=list_filter_button_keyboard(),
    )

    item_msg_ids: list[int] = []
    for i, rem in enumerate(reminders, 1):
        dt_str = jalali_datetime_str(rem.remind_at, db_user.timezone)
        repeat = format_repeat_label(rem.repeat_type, rem.repeat_interval)
        repeat_str = f"\n🔁 {repeat}" if repeat else ""
        status_icon = "⏰" if rem.status.value == "pending" else "💤"
        text_preview = (rem.text or "(بدون متن)")[:60]

        m = await message.answer(
            f"{status_icon} *{i}.* {text_preview}\n"
            f"📅 {dt_str}{repeat_str}",
            parse_mode="Markdown",
            reply_markup=list_item_keyboard(rem.id),
        )
        item_msg_ids.append(m.message_id)

    # Save context so the filter callback can clean up and refresh
    await state.set_state(ReminderList.viewing)
    await state.update_data(
        header_msg_id=header_msg.message_id,
        item_msg_ids=item_msg_ids,
        chat_id=message.chat.id,
        active_filter="all",
    )


@router.message(F.text.startswith("📅 امروز"))
async def list_today(message: Message, db_user: User, session) -> None:
    svc = ReminderService(session)
    reminders = await svc.get_today_by_user(db_user.id, db_user.timezone)
    if not reminders:
        await message.answer("📭 هیچ یادآوری برای امروز ندارید.")
        return

    await message.answer(
        f"📅 *{len(reminders)} یادآوری برای امروز:*",
        parse_mode="Markdown",
    )

    for i, rem in enumerate(reminders, 1):
        local_tz = pytz.timezone(db_user.timezone)
        local_dt = rem.remind_at.astimezone(local_tz)
        time_str = local_dt.strftime("%H:%M")
        text_preview = (rem.text or "(بدون متن)")[:60]
        repeat = format_repeat_label(rem.repeat_type, rem.repeat_interval)
        repeat_str = f"\n🔁 {repeat}" if repeat else ""
        status_map = {
            "pending": "⏰", "done": "✅", "snoozed": "💤",
            "cancelled": "❌", "expired": "⌛",
        }
        icon = status_map.get(rem.status.value, "⏰")

        # نمایش دکمه برای یادآورهای فعال (pending/snoozed)
        can_edit = rem.status.value in ("pending", "snoozed", "expired")
        await message.answer(
            f"{icon} *{i}.* {time_str}  {text_preview}{repeat_str}",
            parse_mode="Markdown",
            reply_markup=list_item_keyboard(rem.id) if can_edit else None,
        )


@router.message(F.text == "❓ راهنما")
async def show_help(message: Message) -> None:
    await message.answer(
        "📖 *راهنمای استفاده*\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📝 *ثبت یادآوری*\n"
        "فقط بنویس — هر ترکیبی از زمان و متن:\n"
        "• `فردا ساعت ۸ برم بانک`\n"
        "• `شنبه عصر قبض برق`\n"
        "• `سه روز دیگه دکتر`\n"
        "• `۲۰ دقیقه دیگه لباس‌ها`\n"
        "• `امشب تماس با مشتری`\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📋 *چند یادآوری باهم*\n"
        "هر یادآوری رو در یک *خط جداگانه* بنویس — همه با هم ثبت می‌شن:\n"
        "```\n"
        "فردا ۸ باشگاه\n"
        "ساعت ۱۲ جلسه\n"
        "ساعت ۷ خرید\n"
        "```\n\n"
        "━━━━━━━━━━━━━━━\n"
        "🔁 *تکرارشونده*\n"
        "• `هر روز ساعت ۹ آب بخورم`\n"
        "• `هر دوشنبه جلسه`\n"
        "• `هفتگی ورزش`\n"
        "• `هر ۳ ساعت داروهام`\n"
        "• `ماهانه پرداخت اقساط`\n\n"
        "━━━━━━━━━━━━━━━\n"
        "🔍 *فیلتر یادآورها*\n"
        "در «📋 یادآورهای من» دکمه فیلتر موجوده:\n"
        "امروز • فردا • این هفته • تکرارشونده\n\n"
        "━━━━━━━━━━━━━━━\n"
        "☀️ *خلاصه برنامه روز*\n"
        "هر روز در ساعت دلخواه، لیست یادآوری‌های همون روز برات ارسال می‌شه.\n"
        "از ⚙️ تنظیمات فعال/غیرفعال و ساعتش رو تنظیم کن.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📨 *فوروارد پیام*\n"
        "یک پیام رو فوروارد کن — می‌پرسم کِی یادآوری کنم.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "🕘 *زمان پیش‌فرض*\n"
        "از ⚙️ تنظیمات ساعت پیش‌فرض رو تنظیم کن.\n"
        "اگر روز نوشتی ولی ساعت ننوشتی، از همون استفاده می‌شه.",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# Settings menu
# ---------------------------------------------------------------------------

@router.message(F.text == "⚙️ تنظیمات")
async def show_settings(message: Message, db_user: User, state: FSMContext) -> None:
    await state.set_state(Settings.main)
    await message.answer(
        _settings_text(db_user),
        parse_mode="Markdown",
        reply_markup=settings_main_keyboard(
            db_user.default_reminder_time,
            db_user.default_time_enabled,
            db_user.forward_behavior,
            db_user.daily_agenda_enabled,
            db_user.daily_agenda_time,
        ),
    )


def _settings_text(user: User) -> str:
    if user.default_reminder_time and user.default_time_enabled:
        time_line = f"✅ فعال — ساعت {user.default_reminder_time}"
    elif user.default_reminder_time and not user.default_time_enabled:
        time_line = f"🔴 غیرفعال — ساعت {user.default_reminder_time}"
    else:
        time_line = "➖ تنظیم نشده"

    fwd = "✅ استفاده از زمان پیش‌فرض" if user.forward_behavior == "use_default" else "🕒 هر بار بپرس"
    agenda_status = "✅ فعال" if user.daily_agenda_enabled else "🔴 غیرفعال"

    return (
        "⚙️ *تنظیمات*\n\n"
        f"🕘 زمان پیش‌فرض: {time_line}\n"
        f"📨 پیام فوروارد: {fwd}\n"
        f"☀️ خلاصه روزانه: {agenda_status} — ساعت {user.daily_agenda_time}\n"
    )


# ---------------------------------------------------------------------------
# Waiting for default time input
# ---------------------------------------------------------------------------

@router.message(Settings.waiting_for_default_time)
async def receive_default_time(message: Message, db_user: User, session, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text == "❌ لغو":
        await state.clear()
        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await message.answer("لغو شد.", reply_markup=main_menu_keyboard(today_count))
        return

    from utils.jalali import from_persian_digits

    # Try to parse using the full parser first (handles "۹ صبح", "ده شب", etc.)
    from parser import parse_message as _parse
    parsed = _parse(text, db_user.timezone)
    if parsed.time_found and parsed.remind_at:
        local_tz = pytz.timezone(db_user.timezone)
        local_dt = parsed.remind_at.astimezone(local_tz)
        time_str = f"{local_dt.hour:02d}:{local_dt.minute:02d}"
        svc = UserService(session)
        await svc.update_default_time(db_user, time_str, enabled=True)
        await state.clear()
        await message.answer(
            f"✅ زمان پیش‌فرض روی *{time_str}* تنظیم شد.\n\n"
            "برای پیام‌های فوروارد شده از همین زمان استفاده بشه؟",
            parse_mode="Markdown",
            reply_markup=forward_behavior_keyboard(),
        )
        return

    # Fallback: plain HH:MM or H format
    time_str = from_persian_digits(text)
    m = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
    if not m:
        m2 = re.match(r"^(\d{1,2})$", time_str)
        if m2:
            h = int(m2.group(1))
            if 0 <= h <= 23:
                time_str = f"{h:02d}:00"
                m = True

    if not m:
        await message.answer(
            "⚠️ فرمت ساعت رو متوجه نشدم.\n\n"
            "می‌تونی ساعت رو به این شکل‌ها بنویسی:\n"
            "• `08:30` یا `۰۸:۳۰`\n"
            "• `9` یا `۹` (= ۰۹:۰۰)\n"
            "• `۹ صبح` یا `ده شب`\n"
            "• `21:15`\n\n"
            "یا از دکمه‌های بالا انتخاب کن.",
            parse_mode="Markdown",
        )
        return

    if not isinstance(m, bool):
        h, mn = int(m.group(1)), int(m.group(2))
        if not (0 <= h <= 23 and 0 <= mn <= 59):
            await message.answer("⚠️ ساعت وارد شده معتبر نیست.")
            return
        time_str = f"{h:02d}:{mn:02d}"

    svc = UserService(session)
    await svc.update_default_time(db_user, time_str, enabled=True)

    await state.clear()
    await message.answer(
        f"✅ زمان پیش‌فرض روی *{time_str}* تنظیم شد.\n\n"
        "برای پیام‌های فوروارد شده از همین زمان استفاده بشه؟",
        parse_mode="Markdown",
        reply_markup=forward_behavior_keyboard(),
    )


# ---------------------------------------------------------------------------
# Waiting for daily agenda time input
# ---------------------------------------------------------------------------

@router.message(Settings.waiting_for_agenda_time)
async def receive_agenda_time(message: Message, db_user: User, session, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text == "❌ لغو":
        await state.clear()
        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await message.answer("لغو شد.", reply_markup=main_menu_keyboard(today_count))
        return

    from utils.jalali import from_persian_digits

    # Try full parser first
    from parser import parse_message as _parse
    parsed = _parse(text, db_user.timezone)
    if parsed.time_found and parsed.remind_at:
        local_tz = pytz.timezone(db_user.timezone)
        local_dt = parsed.remind_at.astimezone(local_tz)
        time_str = f"{local_dt.hour:02d}:{local_dt.minute:02d}"
    else:
        # Fallback: plain HH:MM or H format
        time_str_raw = from_persian_digits(text)
        m = re.match(r"^(\d{1,2}):(\d{2})$", time_str_raw)
        if not m:
            m2 = re.match(r"^(\d{1,2})$", time_str_raw)
            if m2:
                h = int(m2.group(1))
                if 0 <= h <= 23:
                    time_str_raw = f"{h:02d}:00"
                    m = True

        if not m:
            await message.answer(
                "⚠️ فرمت ساعت رو متوجه نشدم.\n"
                "مثال: `08:00` یا `۷` یا `۷ صبح`",
                parse_mode="Markdown",
            )
            return

        if not isinstance(m, bool):
            h, mn = int(m.group(1)), int(m.group(2))
            if not (0 <= h <= 23 and 0 <= mn <= 59):
                await message.answer("⚠️ ساعت وارد شده معتبر نیست.")
                return
            time_str_raw = f"{h:02d}:{mn:02d}"
        time_str = time_str_raw

    # Update daily agenda time and keep enabled status
    from scheduler import schedule_daily_agenda, cancel_daily_agenda
    svc = UserService(session)
    await svc.update_daily_agenda(db_user, enabled=db_user.daily_agenda_enabled, agenda_time=time_str)
    await state.clear()

    # Reschedule the job
    if db_user.daily_agenda_enabled:
        schedule_daily_agenda(
            message.bot,
            user_id=db_user.id,
            telegram_id=db_user.telegram_id,
            agenda_time=time_str,
            tz=db_user.timezone,
        )
    else:
        cancel_daily_agenda(db_user.id)

    today_count = await get_today_count(db_user.id, db_user.timezone, session)
    await message.answer(
        f"✅ ساعت ارسال خلاصه روزانه روی *{time_str}* تنظیم شد.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(today_count),
    )


# ---------------------------------------------------------------------------
# Forwarded messages
# ---------------------------------------------------------------------------

@router.message(F.forward_origin)
async def handle_forward(message: Message, db_user: User, session, state: FSMContext) -> None:
    """User forwarded a message — save it and ask for time (or use default)."""
    await state.clear()

    text_content = message.text or message.caption or "(پیام فوروارد شده)"

    if db_user.forward_behavior == "use_default" and db_user.default_reminder_time and db_user.default_time_enabled:
        local_tz = pytz.timezone(db_user.timezone)
        now = datetime.now(local_tz)
        tomorrow = (now + timedelta(days=1)).replace(second=0, microsecond=0)
        remind_at = apply_default_time(tomorrow, db_user.default_reminder_time, db_user.timezone)

        svc = ReminderService(session)
        reminder = await svc.create(
            user_id=db_user.id,
            text=text_content[:500],
            remind_at=remind_at,
            original_message_id=message.message_id,
        )
        schedule_reminder(message.bot, reminder)

        dt_str = jalali_datetime_str(remind_at, db_user.timezone)
        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await message.answer(
            f"✅ ثبت شد!\n\n📅 یادآوری در: *{dt_str}*",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(today_count),
        )
        return

    # Ask for time
    await state.set_state(ForwardReminder.waiting_for_time)
    await state.update_data(
        forward_text=text_content[:500],
        original_message_id=message.message_id,
    )
    await message.answer(
        "📨 پیام فوروارد شد.\n\nکِی یادآوری کنم؟\nمثال: `فردا ساعت ۸` یا `شنبه صبح`",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(),
    )


@router.message(ForwardReminder.waiting_for_time)
async def receive_time_for_forward(
    message: Message, db_user: User, session, state: FSMContext
) -> None:
    if (message.text or "").strip() == "❌ لغو":
        await state.clear()
        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await message.answer("❌ لغو شد.", reply_markup=main_menu_keyboard(today_count))
        return

    data = await state.get_data()
    raw_text = message.text or ""
    result = parse_message(raw_text, db_user.timezone)

    # Fallback: try standalone time shorthand (e.g. "9", "هشت", "21")
    remind_at = None
    if result.time_found:
        remind_at = result.remind_at
    else:
        remind_at = _parse_time_shorthand(raw_text.strip(), db_user.timezone)

    if remind_at is None:
        await message.answer(
            "⚠️ زمان را متوجه نشدم. لطفاً دوباره بنویس.\n"
            "مثال: `فردا ساعت ۸` یا `شنبه صبح` یا `۹` یا `۲۱`",
            parse_mode="Markdown",
        )
        return

    if db_user.default_reminder_time and db_user.default_time_enabled and result.time_found:
        if not _has_explicit_time(raw_text):
            remind_at = apply_default_time(remind_at, db_user.default_reminder_time, db_user.timezone)

    svc = ReminderService(session)
    reminder = await svc.create(
        user_id=db_user.id,
        text=data.get("forward_text", "(پیام فوروارد شده)"),
        remind_at=remind_at,
        original_message_id=data.get("original_message_id"),
    )
    schedule_reminder(message.bot, reminder)

    await state.clear()
    dt_str = jalali_datetime_str(remind_at, db_user.timezone)
    today_count = await get_today_count(db_user.id, db_user.timezone, session)
    await message.answer("منوی اصلی:", reply_markup=main_menu_keyboard(today_count))
    await message.answer(
        f"✅ ثبت شد!\n\n📅 یادآوری در: *{dt_str}*",
        parse_mode="Markdown",
        reply_markup=list_item_keyboard(reminder.id),
    )


# ---------------------------------------------------------------------------
# State: waiting for text (we already have time)
# ---------------------------------------------------------------------------

@router.message(ReminderCreation.waiting_for_text)
async def receive_text_for_reminder(
    message: Message, db_user: User, session, state: FSMContext
) -> None:
    if (message.text or "").strip() == "❌ لغو":
        await state.clear()
        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await message.answer("❌ لغو شد.", reply_markup=main_menu_keyboard(today_count))
        return

    data = await state.get_data()
    text = (message.text or "").strip()
    if not text:
        await message.answer("متن یادآوری رو بنویس:")
        return

    remind_at_iso = data.get("remind_at")
    remind_at = datetime.fromisoformat(remind_at_iso)
    repeat_type = RepeatType(data.get("repeat_type", "none"))
    repeat_interval = data.get("repeat_interval")
    weekday = data.get("weekday")

    svc = ReminderService(session)
    reminder = await svc.create(
        user_id=db_user.id,
        text=text,
        remind_at=remind_at,
        repeat_type=repeat_type,
        repeat_interval=repeat_interval,
        weekday=weekday,
    )
    schedule_reminder(message.bot, reminder)

    await state.clear()
    dt_str = jalali_datetime_str(remind_at, db_user.timezone)
    repeat_str = ""
    if repeat_type != RepeatType.NONE:
        label = format_repeat_label(repeat_type, repeat_interval)
        repeat_str = f"\n🔁 تکرار: *{label}*"

    today_count = await get_today_count(db_user.id, db_user.timezone, session)
    await message.answer("منوی اصلی:", reply_markup=main_menu_keyboard(today_count))
    await message.answer(
        f"✅ ثبت شد!\n\n📝 {text}\n📅 {dt_str}{repeat_str}",
        parse_mode="Markdown",
        reply_markup=list_item_keyboard(reminder.id),
    )


# ---------------------------------------------------------------------------
# State: waiting for time (we already have text)
# ---------------------------------------------------------------------------

@router.message(ReminderCreation.waiting_for_time)
async def receive_time_for_reminder(
    message: Message, db_user: User, session, state: FSMContext
) -> None:
    if (message.text or "").strip() == "❌ لغو":
        await state.clear()
        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await message.answer("❌ لغو شد.", reply_markup=main_menu_keyboard(today_count))
        return

    data = await state.get_data()
    raw_text = message.text or ""
    result = parse_message(raw_text, db_user.timezone)

    # Fallback: bare number/word like "9", "هشت", "21"
    remind_at = None
    if result.time_found:
        remind_at = result.remind_at
    else:
        remind_at = _parse_time_shorthand(raw_text.strip(), db_user.timezone)

    if remind_at is None:
        await message.answer(
            "⚠️ زمان رو متوجه نشدم. دوباره بنویس:\n"
            "مثال: `فردا ساعت ۸` یا `شنبه صبح` یا `۹` یا `هشت`",
            parse_mode="Markdown",
        )
        return

    if db_user.default_reminder_time and db_user.default_time_enabled and result.time_found:
        if not _has_explicit_time(raw_text):
            remind_at = apply_default_time(remind_at, db_user.default_reminder_time, db_user.timezone)

    text = data.get("text", "")
    repeat_type = result.repeat_type
    repeat_interval = result.repeat_interval

    svc = ReminderService(session)
    reminder = await svc.create(
        user_id=db_user.id,
        text=text,
        remind_at=remind_at,
        repeat_type=repeat_type,
        repeat_interval=repeat_interval,
        weekday=result.weekday,
    )
    schedule_reminder(message.bot, reminder)

    await state.clear()
    dt_str = jalali_datetime_str(remind_at, db_user.timezone)
    repeat_str = ""
    if repeat_type != RepeatType.NONE:
        label = format_repeat_label(repeat_type, repeat_interval)
        repeat_str = f"\n🔁 تکرار: *{label}*"

    today_count = await get_today_count(db_user.id, db_user.timezone, session)
    await message.answer("منوی اصلی:", reply_markup=main_menu_keyboard(today_count))
    await message.answer(
        f"✅ ثبت شد!\n\n📝 {text}\n📅 {dt_str}{repeat_str}",
        parse_mode="Markdown",
        reply_markup=list_item_keyboard(reminder.id),
    )


# ---------------------------------------------------------------------------
# Edit states
# ---------------------------------------------------------------------------

@router.message(ReminderEdit.waiting_for_text)
async def edit_receive_text(
    message: Message, db_user: User, session, state: FSMContext
) -> None:
    """Receive new text for an existing reminder — UPDATE, don't create."""
    if (message.text or "").strip() == "❌ لغو":
        await state.clear()
        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await message.answer("❌ لغو شد.", reply_markup=main_menu_keyboard(today_count))
        return

    new_text = (message.text or "").strip()
    if not new_text:
        await message.answer("متن نمی‌تونه خالی باشه. دوباره بنویس:")
        return

    data = await state.get_data()
    reminder_id = data.get("reminder_id")
    if not reminder_id:
        await state.clear()
        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await message.answer("خطا: یادآور یافت نشد.", reply_markup=main_menu_keyboard(today_count))
        return

    svc = ReminderService(session)
    reminder = await svc.get_by_id(reminder_id)
    if reminder is None or reminder.user_id != db_user.id:
        await state.clear()
        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await message.answer("خطا: یادآور یافت نشد.", reply_markup=main_menu_keyboard(today_count))
        return

    await svc.update_text(reminder, new_text)

    await state.clear()
    dt_str = jalali_datetime_str(reminder.remind_at, db_user.timezone)
    today_count = await get_today_count(db_user.id, db_user.timezone, session)
    await message.answer(
        f"✅ متن یادآور ویرایش شد!\n\n"
        f"📝 {new_text}\n"
        f"📅 {dt_str}",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(today_count),
    )


@router.message(ReminderEdit.waiting_for_time)
async def edit_receive_time(
    message: Message, db_user: User, session, state: FSMContext
) -> None:
    """Receive new time for an existing reminder — UPDATE, don't create."""
    if (message.text or "").strip() == "❌ لغو":
        await state.clear()
        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await message.answer("❌ لغو شد.", reply_markup=main_menu_keyboard(today_count))
        return

    data = await state.get_data()
    reminder_id = data.get("reminder_id")
    if not reminder_id:
        await state.clear()
        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await message.answer("خطا: یادآور یافت نشد.", reply_markup=main_menu_keyboard(today_count))
        return

    svc = ReminderService(session)
    reminder = await svc.get_by_id(reminder_id)
    if reminder is None or reminder.user_id != db_user.id:
        await state.clear()
        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await message.answer("خطا: یادآور یافت نشد.", reply_markup=main_menu_keyboard(today_count))
        return

    raw_text = message.text or ""
    result = parse_message(raw_text, db_user.timezone)

    # Fallback: bare number/word like "9", "هشت", "21"
    new_remind_at = None
    if result.time_found:
        new_remind_at = result.remind_at
    else:
        new_remind_at = _parse_time_shorthand(raw_text.strip(), db_user.timezone)

    if new_remind_at is None:
        await message.answer(
            "⚠️ زمان رو متوجه نشدم. دوباره بنویس:\n"
            "مثال: `فردا ساعت ۱۰` یا `شنبه شب` یا `۳۰ دقیقه دیگه` یا `۹` یا `۲۱`",
            parse_mode="Markdown",
        )
        return

    if db_user.default_reminder_time and db_user.default_time_enabled and result.time_found:
        if not _has_explicit_time(raw_text):
            new_remind_at = apply_default_time(
                new_remind_at, db_user.default_reminder_time, db_user.timezone
            )

    cancel_reminder(reminder_id)
    await svc.update_time(
        reminder,
        new_remind_at,
        new_repeat_type=result.repeat_type if result.repeat_type != RepeatType.NONE else None,
        new_repeat_interval=result.repeat_interval,
    )

    schedule_reminder(message.bot, reminder)

    await state.clear()
    dt_str = jalali_datetime_str(new_remind_at, db_user.timezone)
    repeat_str = ""
    if reminder.repeat_type != RepeatType.NONE:
        label = format_repeat_label(reminder.repeat_type, reminder.repeat_interval)
        repeat_str = f"\n🔁 تکرار: *{label}*"

    today_count = await get_today_count(db_user.id, db_user.timezone, session)
    await message.answer(
        f"✅ زمان یادآور ویرایش شد!\n\n"
        f"📝 {reminder.text or '(بدون متن)'}\n"
        f"📅 {dt_str}{repeat_str}",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(today_count),
    )


# ---------------------------------------------------------------------------
# Non-text messages while in a waiting state — prevent the user getting stuck
# ---------------------------------------------------------------------------

@router.message(
    ~F.text,
    ReminderCreation.waiting_for_text,
)
@router.message(
    ~F.text,
    ReminderCreation.waiting_for_time,
)
@router.message(
    ~F.text,
    ForwardReminder.waiting_for_time,
)
@router.message(
    ~F.text,
    ReminderEdit.waiting_for_text,
)
@router.message(
    ~F.text,
    ReminderEdit.waiting_for_time,
)
@router.message(
    ~F.text,
    Settings.waiting_for_default_time,
)
@router.message(
    ~F.text,
    Settings.waiting_for_agenda_time,
)
async def reject_non_text_in_state(message: Message) -> None:
    """Tell the user we only accept text while waiting for input."""
    await message.answer("⚠️ لطفاً پیام متنی بفرست.")


# ---------------------------------------------------------------------------
# Free-form messages (no state) — main NLP entry point
# ---------------------------------------------------------------------------

@router.message(F.text)
async def handle_free_text(message: Message, db_user: User, session, state: FSMContext) -> None:
    text = (message.text or "").strip()

    # Try multi-reminder parsing first (when message has newlines)
    if "\n" in text:
        try:
            multi_results = parse_multi(text, db_user.timezone)
        except Exception as exc:
            logger.warning("parse_multi failed for user %s: %s", db_user.id, exc)
            multi_results = []
        if len(multi_results) >= 2:
            # Check if we got at least 2 complete results
            complete = [r for r in multi_results if r.is_complete()]
            if len(complete) >= 2:
                await _handle_multi_reminders(message, db_user, session, complete, multi_results)
                return

    # Single reminder flow
    try:
        result = parse_message(text, db_user.timezone)
    except Exception as exc:
        logger.warning("parse_message failed for user %s input %r: %s", db_user.id, text[:80], exc)
        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await message.answer(
            "⚠️ خطایی در پردازش پیام رخ داد. دوباره امتحان کن.",
            reply_markup=main_menu_keyboard(today_count),
        )
        return

    # Case 1: Both time and text found — save immediately
    if result.time_found and result.text_found:
        remind_at = result.remind_at

        # Apply default time if day was given but no explicit clock time
        if db_user.default_reminder_time and db_user.default_time_enabled:
            if not _has_explicit_time(text):
                remind_at = apply_default_time(
                    remind_at, db_user.default_reminder_time, db_user.timezone
                )

        svc = ReminderService(session)
        reminder = await svc.create(
            user_id=db_user.id,
            text=result.text,
            remind_at=remind_at,
            repeat_type=result.repeat_type,
            repeat_interval=result.repeat_interval,
            weekday=result.weekday,
        )
        schedule_reminder(message.bot, reminder)

        dt_str = jalali_datetime_str(remind_at, db_user.timezone)
        repeat_str = ""
        if result.repeat_type != RepeatType.NONE:
            label = format_repeat_label(result.repeat_type, result.repeat_interval)
            repeat_str = f"\n🔁 تکرار: *{label}*"

        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await message.answer("منوی اصلی:", reply_markup=main_menu_keyboard(today_count))
        await message.answer(
            f"✅ ثبت شد!\n\n📝 {result.text}\n📅 {dt_str}{repeat_str}",
            parse_mode="Markdown",
            reply_markup=list_item_keyboard(reminder.id),
        )
        return

    # Case 2: Only time found — ask for reminder text
    if result.time_found and not result.text_found:
        remind_at = result.remind_at
        if db_user.default_reminder_time and db_user.default_time_enabled:
            if not _has_explicit_time(text):
                remind_at = apply_default_time(
                    remind_at, db_user.default_reminder_time, db_user.timezone
                )
        await state.set_state(ReminderCreation.waiting_for_text)
        await state.update_data(
            remind_at=remind_at.isoformat(),
            repeat_type=result.repeat_type.value,
            repeat_interval=result.repeat_interval,
            weekday=result.weekday,
        )
        dt_str = jalali_datetime_str(remind_at, db_user.timezone)
        await message.answer(
            f"⏰ زمان: *{dt_str}*\n\nچی رو یادآوری کنم؟",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard(),
        )
        return

    # Case 3: Only text found — ask for time
    if result.text_found and not result.time_found:
        await state.set_state(ReminderCreation.waiting_for_time)
        await state.update_data(text=result.text)
        await message.answer(
            f"📝 یادآوری: *{result.text}*\n\nکِی یادآوری کنم؟\nمثال: فردا ساعت ۸ یا شنبه صبح",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard(),
        )
        return

    # Fallback
    today_count = await get_today_count(db_user.id, db_user.timezone, session)
    await message.answer(
        "🤔 متوجه نشدم.\n\n"
        "یه پیام کامل‌تر بنویس، مثلاً:\n"
        "• فردا ساعت ۸ برم دکتر\n"
        "• شنبه صبح قبض برق\n"
        "• ۳۰ دقیقه دیگه داروهام\n\n"
        "یا از ❓ راهنما استفاده کن.",
        reply_markup=main_menu_keyboard(today_count),
    )


async def _handle_multi_reminders(
    message: Message,
    db_user: User,
    session,
    complete_results,
    all_results,
) -> None:
    """Save multiple reminders from a single message and show a summary."""
    from services.reminder_service import ReminderService

    svc = ReminderService(session)
    saved = []
    errors = []

    for r in all_results:
        if r.is_complete():
            try:
                remind_at = r.remind_at
                if db_user.default_reminder_time and db_user.default_time_enabled:
                    # Apply default time only if no explicit clock was in the original text
                    if not r.time_found:
                        remind_at = apply_default_time(
                            remind_at, db_user.default_reminder_time, db_user.timezone
                        )
                reminder = await svc.create(
                    user_id=db_user.id,
                    text=r.text,
                    remind_at=remind_at,
                    repeat_type=r.repeat_type,
                    repeat_interval=r.repeat_interval,
                    weekday=r.weekday,
                )
                schedule_reminder(message.bot, reminder)
                saved.append((r.text, remind_at))
            except Exception as exc:
                logger.warning("Failed to save one of multi-reminders: %s", exc)
                errors.append(r.text or "؟")
        else:
            if r.text_found:
                errors.append(r.text or "؟")

    if not saved:
        # Fallback: nothing saved, treat as single
        result = complete_results[0] if complete_results else None
        if result:
            remind_at = result.remind_at
            reminder = await svc.create(
                user_id=db_user.id,
                text=result.text,
                remind_at=remind_at,
                repeat_type=result.repeat_type,
                repeat_interval=result.repeat_interval,
                weekday=result.weekday,
            )
            schedule_reminder(message.bot, reminder)
            dt_str = jalali_datetime_str(remind_at, db_user.timezone)
            today_count = await get_today_count(db_user.id, db_user.timezone, session)
            await message.answer("منوی اصلی:", reply_markup=main_menu_keyboard(today_count))
            await message.answer(
                f"✅ ثبت شد!\n\n📝 {result.text}\n📅 {dt_str}",
                parse_mode="Markdown",
            )
        return

    # Build summary
    local_tz = pytz.timezone(db_user.timezone)
    lines = [f"✅ *{len(saved)} یادآوری ثبت شد.*\n"]
    for text, remind_at in saved:
        local_dt = remind_at.astimezone(local_tz)
        time_str = local_dt.strftime("%H:%M")
        lines.append(f"🕐 {time_str}  {text}")

    if errors:
        lines.append(f"\n⚠️ *{len(errors)} مورد ثبت نشد:*")
        for e in errors:
            lines.append(f"• {e}")

    today_count = await get_today_count(db_user.id, db_user.timezone, session)
    await message.answer("منوی اصلی:", reply_markup=main_menu_keyboard(today_count))
    await message.answer("\n".join(lines), parse_mode="Markdown")

