"""
Inline button callback handler — reminder actions, settings, and confirmations.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytz
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from config import config
from keyboards.main_menu import main_menu_keyboard
from keyboards.reminder_buttons import (
    confirm_list_delete_keyboard,
    edit_options_keyboard,
    filter_options_keyboard,
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
from scheduler import cancel_reminder, schedule_reminder
from services.reminder_service import ReminderService
from services.user_service import UserService
from states import ReminderEdit, ReminderList, Settings
from utils.jalali import jalali_datetime_str
from utils.reminder_utils import format_repeat_label, get_today_count

logger = logging.getLogger(__name__)
router = Router()


# ---------------------------------------------------------------------------
# Reminder action callbacks  (rem:<action>:<reminder_id>)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("rem:"))
async def reminder_action(call: CallbackQuery, db_user: User, session) -> None:
    _, action, rem_id_str = call.data.split(":", 2)
    reminder_id = int(rem_id_str)

    svc = ReminderService(session)
    reminder = await svc.get_by_id(reminder_id)

    if reminder is None or reminder.user_id != db_user.id:
        await call.answer("یادآور یافت نشد.", show_alert=True)
        return

    if action == "done":
        cancel_reminder(reminder_id)
        await svc.mark_done(reminder)
        await call.message.edit_text(
            call.message.text + "\n\n✅ *انجام شد*",
            parse_mode="Markdown",
            reply_markup=None,
        )
        await call.answer("✅ انجام شد!")
        # Refresh main menu so today count updates
        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await call.message.answer(
            "✅ یادآوری انجام شد.",
            reply_markup=main_menu_keyboard(today_count),
        )

    elif action == "delete":
        cancel_reminder(reminder_id)
        await svc.mark_cancelled(reminder)
        await call.message.edit_text(
            call.message.text + "\n\n❌ *حذف شد*",
            parse_mode="Markdown",
            reply_markup=None,
        )
        await call.answer("❌ حذف شد.")
        # Refresh main menu so today count updates
        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await call.message.answer(
            "🗑 یادآوری حذف شد.",
            reply_markup=main_menu_keyboard(today_count),
        )

    elif action.startswith("snooze"):
        now = datetime.now(pytz.utc)
        if action == "snooze10":
            new_time = now + timedelta(minutes=10)
            label = "۱۰ دقیقه"
        elif action == "snooze30":
            new_time = now + timedelta(minutes=30)
            label = "۳۰ دقیقه"
        elif action == "snooze60":
            new_time = now + timedelta(hours=1)
            label = "۱ ساعت"
        elif action == "snooze1d":
            tz = pytz.timezone(db_user.timezone)
            local_now = now.astimezone(tz)
            new_time = (local_now + timedelta(days=1)).replace(
                hour=9, minute=0, second=0, microsecond=0
            ).astimezone(pytz.utc)
            label = "فردا"
        else:
            await call.answer("نامعلوم")
            return

        cancel_reminder(reminder_id)
        await svc.snooze(reminder, new_time)
        schedule_reminder(call.bot, reminder)

        dt_str = jalali_datetime_str(new_time, db_user.timezone)
        await call.message.edit_text(
            call.message.text + f"\n\n⏰ *تعویق به {dt_str}*",
            parse_mode="Markdown",
            reply_markup=None,
        )
        await call.answer(f"⏰ {label} دیگه یادآوری می‌کنم.")
        # Refresh main menu so today count updates (especially for snooze to tomorrow)
        today_count = await get_today_count(db_user.id, db_user.timezone, session)
        await call.message.answer(
            f"⏰ یادآوری به {dt_str} موکول شد.",
            reply_markup=main_menu_keyboard(today_count),
        )

    else:
        await call.answer("نامشخص")


# ---------------------------------------------------------------------------
# Filter callbacks
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "filter:open")
async def filter_open(call: CallbackQuery) -> None:
    """User tapped 🔍 فیلتر — edit the header message to show filter options."""
    await call.message.edit_reply_markup(reply_markup=filter_options_keyboard())
    await call.answer()


@router.callback_query(F.data.startswith("filter:"))
async def handle_filter(call: CallbackQuery, db_user: User, session, state: FSMContext) -> None:
    """Apply the selected filter: delete old items, send new list."""
    filter_type = call.data.split(":", 1)[1]

    # "open" is handled by the handler above; skip it here
    if filter_type == "open":
        return

    svc = ReminderService(session)

    if filter_type == "today":
        reminders = await svc.get_today_by_user(db_user.id, db_user.timezone)
        title = "📅 یادآورهای امروز"
    elif filter_type == "tomorrow":
        reminders = await svc.get_tomorrow_by_user(db_user.id, db_user.timezone)
        title = "🌤 یادآورهای فردا"
    elif filter_type == "week":
        reminders = await svc.get_this_week_by_user(db_user.id, db_user.timezone)
        title = "📆 یادآورهای این هفته"
    elif filter_type == "recurring":
        reminders = await svc.get_recurring_by_user(db_user.id)
        title = "🔁 یادآورهای تکرارشونده"
    else:  # "all"
        reminders = await svc.get_pending_by_user(db_user.id)
        title = "📋 همه یادآورها"

    await call.answer()

    # ── Delete previous item messages ────────────────────────────────────
    data = await state.get_data()
    old_ids: list[int] = data.get("item_msg_ids", [])
    for msg_id in old_ids:
        try:
            await call.bot.delete_message(call.message.chat.id, msg_id)
        except Exception as del_exc:
            logger.debug("Could not delete list message %s: %s", msg_id, del_exc)

    # ── Update header to new filter title + restore single filter button ─
    count_text = f"{len(reminders)} مورد" if reminders else "بدون نتیجه"
    await call.message.edit_text(
        f"{title}: *{count_text}*",
        parse_mode="Markdown",
        reply_markup=list_filter_button_keyboard(),
    )

    if not reminders:
        await state.update_data(item_msg_ids=[], active_filter=filter_type)
        return

    # ── Send new item messages and track their IDs ────────────────────────
    new_ids: list[int] = []
    for i, rem in enumerate(reminders, 1):
        dt_str = jalali_datetime_str(rem.remind_at, db_user.timezone)
        repeat = format_repeat_label(rem.repeat_type, rem.repeat_interval)
        repeat_str = f"\n🔁 {repeat}" if repeat else ""
        status_icon = "⏰" if rem.status.value == "pending" else "💤"
        text_preview = (rem.text or "(بدون متن)")[:60]
        can_edit = rem.status.value in ("pending", "snoozed", "expired")

        m = await call.message.answer(
            f"{status_icon} *{i}.* {text_preview}\n"
            f"📅 {dt_str}{repeat_str}",
            parse_mode="Markdown",
            reply_markup=list_item_keyboard(rem.id) if can_edit else None,
        )
        new_ids.append(m.message_id)

    await state.set_state(ReminderList.viewing)
    await state.update_data(
        item_msg_ids=new_ids,
        active_filter=filter_type,
        header_msg_id=call.message.message_id,
        chat_id=call.message.chat.id,
    )


# ---------------------------------------------------------------------------
# List view: delete  (list:delete:<id> / list:confirm_delete:<id> / list:cancel_delete)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("list:delete:"))
async def list_delete_ask(call: CallbackQuery, db_user: User, session) -> None:
    """Ask for confirmation before deleting from the list."""
    reminder_id = int(call.data.split(":")[-1])

    svc = ReminderService(session)
    reminder = await svc.get_by_id(reminder_id)
    if reminder is None or reminder.user_id != db_user.id:
        await call.answer("یادآور یافت نشد.", show_alert=True)
        return

    text_preview = (reminder.text or "(بدون متن)")[:40]
    await call.message.edit_text(
        f"🗑 *حذف یادآور*\n\n"
        f"«{text_preview}»\n\n"
        "مطمئنی می‌خوای حذف بشه؟",
        parse_mode="Markdown",
        reply_markup=confirm_list_delete_keyboard(reminder_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("list:confirm_delete:"))
async def list_delete_confirm(call: CallbackQuery, db_user: User, session) -> None:
    """Actually delete the reminder after confirmation."""
    reminder_id = int(call.data.split(":")[-1])

    svc = ReminderService(session)
    reminder = await svc.get_by_id(reminder_id)
    if reminder is None or reminder.user_id != db_user.id:
        await call.answer("یادآور یافت نشد.", show_alert=True)
        return

    cancel_reminder(reminder_id)
    await svc.mark_cancelled(reminder)

    await call.message.edit_text(
        "✅ یادآور با موفقیت حذف شد.",
        reply_markup=None,
    )
    await call.answer("🗑 حذف شد.")
    # Refresh main menu so today count updates
    today_count = await get_today_count(db_user.id, db_user.timezone, session)
    await call.message.answer(
        "🗑 یادآوری حذف شد.",
        reply_markup=main_menu_keyboard(today_count),
    )


@router.callback_query(F.data == "list:cancel_delete")
async def list_delete_cancel(call: CallbackQuery) -> None:
    """Cancel deletion — dismiss the confirmation message."""
    await call.message.delete()
    await call.answer("لغو شد.")


# ---------------------------------------------------------------------------
# List view: edit flow  (list:edit:<id> → edit:text:<id> / edit:time:<id>)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("list:edit:"))
async def list_edit_show_options(call: CallbackQuery, db_user: User, session, state: FSMContext) -> None:
    """Show edit sub-options: edit text or edit time."""
    reminder_id = int(call.data.split(":")[-1])

    svc = ReminderService(session)
    reminder = await svc.get_by_id(reminder_id)
    if reminder is None or reminder.user_id != db_user.id:
        await call.answer("یادآور یافت نشد.", show_alert=True)
        return

    text_preview = (reminder.text or "(بدون متن)")[:40]
    dt_str = jalali_datetime_str(reminder.remind_at, db_user.timezone)

    await state.set_state(ReminderEdit.selecting_field)
    await state.update_data(reminder_id=reminder_id)

    await call.message.edit_text(
        f"✏️ *ویرایش یادآور*\n\n"
        f"📝 {text_preview}\n"
        f"📅 {dt_str}\n\n"
        "چه چیزی رو ویرایش کنم؟",
        parse_mode="Markdown",
        reply_markup=edit_options_keyboard(reminder_id),
    )
    await call.answer()


@router.callback_query(F.data == "edit:cancel")
async def edit_cancel(call: CallbackQuery, state: FSMContext) -> None:
    """Cancel edit flow."""
    await state.clear()
    await call.message.delete()
    await call.answer("لغو شد.")


@router.callback_query(F.data.startswith("edit:text:"))
async def edit_text_start(call: CallbackQuery, db_user: User, session, state: FSMContext) -> None:
    reminder_id = int(call.data.split(":")[-1])

    svc = ReminderService(session)
    reminder = await svc.get_by_id(reminder_id)
    if reminder is None or reminder.user_id != db_user.id:
        await call.answer("یادآور یافت نشد.", show_alert=True)
        return

    old_text = reminder.text or "(بدون متن)"

    await state.set_state(ReminderEdit.waiting_for_text)
    await state.update_data(reminder_id=reminder_id)

    await call.message.edit_text(
        f"📝 *ویرایش متن یادآور*\n\n"
        f"متن فعلی: «{old_text}»\n\n"
        "متن جدید رو بنویس:",
        parse_mode="Markdown",
        reply_markup=None,
    )
    await call.answer()


@router.callback_query(F.data.startswith("edit:time:"))
async def edit_time_start(call: CallbackQuery, db_user: User, session, state: FSMContext) -> None:
    reminder_id = int(call.data.split(":")[-1])

    svc = ReminderService(session)
    reminder = await svc.get_by_id(reminder_id)
    if reminder is None or reminder.user_id != db_user.id:
        await call.answer("یادآور یافت نشد.", show_alert=True)
        return

    dt_str = jalali_datetime_str(reminder.remind_at, db_user.timezone)

    await state.set_state(ReminderEdit.waiting_for_time)
    await state.update_data(reminder_id=reminder_id)

    await call.message.edit_text(
        f"🕒 *ویرایش زمان یادآور*\n\n"
        f"زمان فعلی: {dt_str}\n\n"
        "زمان جدید رو بنویس:\n"
        "مثال: `فردا ساعت ۱۰` یا `شنبه شب` یا `۳۰ دقیقه دیگه`",
        parse_mode="Markdown",
        reply_markup=None,
    )
    await call.answer()


# ---------------------------------------------------------------------------
# Settings callbacks
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "settings:change_time")
async def settings_change_time(call: CallbackQuery, db_user: User, state: FSMContext) -> None:
    await state.set_state(Settings.waiting_for_default_time)
    await call.message.answer(
        "🕘 *تنظیم ساعت پیش‌فرض*\n\n"
        "ساعت پیش‌فرض برای یادآورهایی که فقط روز مشخص شده.\n\n"
        "می‌تونی ساعت رو تایپ کنی یا از دکمه‌های زیر انتخاب کنی:\n\n"
        "نمونه‌های معتبر:\n"
        "• `08:30` یا `۰۸:۳۰`\n"
        "• `9` یا `۹` (= ۰۹:۰۰)\n"
        "• `۹ صبح` یا `ده شب` یا `21:15`",
        parse_mode="Markdown",
        reply_markup=default_time_options_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "settings:toggle")
async def settings_toggle(call: CallbackQuery, db_user: User, session) -> None:
    svc = UserService(session)
    await svc.toggle_default_time(db_user)
    status = "فعال" if db_user.default_time_enabled else "غیرفعال"
    await call.message.edit_reply_markup(
        reply_markup=settings_main_keyboard(
            db_user.default_reminder_time,
            db_user.default_time_enabled,
            db_user.forward_behavior,
            db_user.daily_agenda_enabled,
            db_user.daily_agenda_time,
        )
    )
    await call.answer(f"زمان پیش‌فرض {status} شد.")


@router.callback_query(F.data == "settings:toggle_forward")
async def settings_toggle_forward(call: CallbackQuery, db_user: User, session) -> None:
    svc = UserService(session)
    new_behavior = "use_default" if db_user.forward_behavior == "ask" else "ask"
    await svc.set_forward_behavior(db_user, new_behavior)
    await call.message.edit_reply_markup(
        reply_markup=settings_main_keyboard(
            db_user.default_reminder_time,
            db_user.default_time_enabled,
            db_user.forward_behavior,
            db_user.daily_agenda_enabled,
            db_user.daily_agenda_time,
        )
    )
    label = "زمان پیش‌فرض" if new_behavior == "use_default" else "پرسیدن هر بار"
    await call.answer(f"فوروارد: {label}")


@router.callback_query(F.data == "settings:delete_time")
async def settings_delete_time_ask(call: CallbackQuery, db_user: User, state: FSMContext) -> None:
    await state.set_state(Settings.confirming_delete)
    await call.message.answer(
        "🗑 مطمئنی می‌خوای زمان پیش‌فرض رو حذف کنی؟",
        reply_markup=confirm_delete_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("del_time:"))
async def settings_delete_time_confirm(call: CallbackQuery, db_user: User, session, state: FSMContext) -> None:
    choice = call.data.split(":", 1)[1]
    await state.clear()
    if choice == "yes":
        svc = UserService(session)
        await svc.delete_default_time(db_user)
        await call.message.edit_text("✅ زمان پیش‌فرض حذف شد.")
        await call.answer("حذف شد.")
    else:
        await call.message.edit_text("❌ لغو شد.")
        await call.answer("لغو شد.")


@router.callback_query(F.data.startswith("set_time:"))
async def settings_set_time_quick(call: CallbackQuery, db_user: User, session, state: FSMContext) -> None:
    value = call.data.split(":", 1)[1]
    if value == "cancel":
        await state.clear()
        await call.message.edit_text("❌ لغو شد.")
        await call.answer("لغو شد.")
        return

    svc = UserService(session)
    await svc.update_default_time(db_user, value, enabled=True)
    await state.clear()

    await call.message.edit_text(
        f"✅ زمان پیش‌فرض روی *{value}* تنظیم شد.",
        parse_mode="Markdown",
    )
    await call.answer(f"✅ {value} ثبت شد.")


@router.callback_query(F.data.startswith("fwd:"))
async def settings_fwd_behavior(call: CallbackQuery, db_user: User, session) -> None:
    behavior = call.data.split(":", 1)[1]
    svc = UserService(session)
    await svc.set_forward_behavior(db_user, behavior)
    label = "زمان پیش‌فرض" if behavior == "use_default" else "پرسیدن هر بار"
    await call.message.edit_text(
        f"✅ برای پیام‌های فوروارد: *{label}* تنظیم شد.",
        parse_mode="Markdown",
    )
    await call.answer()


# ---------------------------------------------------------------------------
# Daily agenda settings  (settings:daily_agenda)
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "settings:daily_agenda")
async def settings_daily_agenda(call: CallbackQuery, db_user: User) -> None:
    """Show daily agenda settings."""
    status = "✅ فعال" if db_user.daily_agenda_enabled else "❌ غیرفعال"
    await call.message.answer(
        f"☀️ *خلاصه برنامه روز*\n\n"
        f"وضعیت: {status}\n"
        f"ساعت ارسال: *{db_user.daily_agenda_time}*\n\n"
        "هر روز در ساعت انتخابی، اگر یادآوری داشتی، خلاصه‌ای از برنامه‌ات ارسال می‌شه.",
        parse_mode="Markdown",
        reply_markup=daily_agenda_keyboard(db_user.daily_agenda_enabled, db_user.daily_agenda_time),
    )
    await call.answer()


@router.callback_query(F.data == "agenda:enable")
async def agenda_enable(call: CallbackQuery, db_user: User, session) -> None:
    """Enable daily agenda."""
    from scheduler import schedule_daily_agenda
    svc = UserService(session)
    await svc.update_daily_agenda(db_user, enabled=True)

    schedule_daily_agenda(
        call.bot,
        user_id=db_user.id,
        telegram_id=db_user.telegram_id,
        agenda_time=db_user.daily_agenda_time,
        tz=db_user.timezone,
    )

    await call.message.edit_reply_markup(
        reply_markup=daily_agenda_keyboard(True, db_user.daily_agenda_time)
    )
    await call.answer("✅ خلاصه روزانه فعال شد.")


@router.callback_query(F.data == "agenda:disable")
async def agenda_disable(call: CallbackQuery, db_user: User, session) -> None:
    """Disable daily agenda."""
    from scheduler import cancel_daily_agenda
    svc = UserService(session)
    await svc.update_daily_agenda(db_user, enabled=False)

    cancel_daily_agenda(db_user.id)

    await call.message.edit_reply_markup(
        reply_markup=daily_agenda_keyboard(False, db_user.daily_agenda_time)
    )
    await call.answer("❌ خلاصه روزانه غیرفعال شد.")


@router.callback_query(F.data.startswith("agenda_time:"))
async def agenda_set_time_quick(call: CallbackQuery, db_user: User, session) -> None:
    """Set daily agenda time from quick options."""
    from scheduler import schedule_daily_agenda, cancel_daily_agenda
    time_str = call.data.split(":", 1)[1]

    svc = UserService(session)
    await svc.update_daily_agenda(db_user, enabled=db_user.daily_agenda_enabled, agenda_time=time_str)

    if db_user.daily_agenda_enabled:
        schedule_daily_agenda(
            call.bot,
            user_id=db_user.id,
            telegram_id=db_user.telegram_id,
            agenda_time=time_str,
            tz=db_user.timezone,
        )

    await call.message.edit_text(
        f"☀️ *خلاصه برنامه روز*\n\n"
        f"وضعیت: {'✅ فعال' if db_user.daily_agenda_enabled else '❌ غیرفعال'}\n"
        f"ساعت ارسال: *{time_str}*\n\n"
        "هر روز در ساعت انتخابی، اگر یادآوری داشتی، خلاصه‌ای از برنامه‌ات ارسال می‌شه.",
        parse_mode="Markdown",
        reply_markup=daily_agenda_keyboard(db_user.daily_agenda_enabled, time_str),
    )
    await call.answer(f"✅ ساعت {time_str} تنظیم شد.")


@router.callback_query(F.data == "agenda:custom_time")
async def agenda_custom_time(call: CallbackQuery, db_user: User, state: FSMContext) -> None:
    """Ask for custom daily agenda time."""
    await state.set_state(Settings.waiting_for_agenda_time)
    await call.message.answer(
        "🕐 *تنظیم ساعت خلاصه روزانه*\n\n"
        "ساعت دلخواه رو بنویس:\n"
        "مثال: `07:30` یا `۸` یا `۸ صبح`",
        parse_mode="Markdown",
    )
    await call.answer()


@router.callback_query(F.data == "agenda:back")
async def agenda_back(call: CallbackQuery, db_user: User) -> None:
    """Go back to main settings."""
    await call.message.edit_text(
        f"⚙️ *تنظیمات*\n\n"
        f"🕘 زمان پیش‌فرض: "
        f"{'✅ ' + db_user.default_reminder_time if db_user.default_time_enabled and db_user.default_reminder_time else '➖ تنظیم نشده'}\n"
        f"☀️ خلاصه روزانه: "
        f"{'✅ فعال' if db_user.daily_agenda_enabled else '🔴 غیرفعال'} — ساعت {db_user.daily_agenda_time}\n",
        parse_mode="Markdown",
        reply_markup=settings_main_keyboard(
            db_user.default_reminder_time,
            db_user.default_time_enabled,
            db_user.forward_behavior,
            db_user.daily_agenda_enabled,
            db_user.daily_agenda_time,
        ),
    )
    await call.answer()


# ---------------------------------------------------------------------------
# Confirm / edit / cancel  (for auto-detected reminder)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("confirm:"))
async def handle_confirmation(
    call: CallbackQuery, db_user: User, session, state: FSMContext
) -> None:
    choice = call.data.split(":", 1)[1]
    data = await state.get_data()

    if choice == "cancel":
        await state.clear()
        await call.message.edit_text("❌ لغو شد.")
        await call.answer()
        return

    if choice == "yes":
        remind_at_iso = data.get("remind_at")
        text = data.get("text", "")
        if not remind_at_iso or not text:
            await call.answer("خطا: اطلاعات ناقص است.", show_alert=True)
            return

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
        schedule_reminder(call.bot, reminder)

        await state.clear()
        dt_str = jalali_datetime_str(remind_at, db_user.timezone)
        await call.message.edit_text(
            f"✅ ثبت شد!\n\n📝 {text}\n📅 {dt_str}",
            parse_mode="Markdown",
            reply_markup=list_item_keyboard(reminder.id),
        )
        await call.answer("✅ ثبت شد!")

    elif choice == "edit":
        await state.clear()
        await call.message.edit_text(
            "لطفاً یادآوری رو دوباره با اطلاعات کامل‌تر بنویس:"
        )
        await call.answer()
