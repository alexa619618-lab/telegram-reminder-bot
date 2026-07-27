"""
Inline keyboards for reminder actions (sent with reminder notification and list view).
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def reminder_action_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    """
    Buttons shown with a reminder notification:
    ✅ Done | ❌ Delete
    ⏰ +10 min | 🕐 +1 hour | 📅 Tomorrow
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ انجام شد", callback_data=f"rem:done:{reminder_id}"),
        InlineKeyboardButton(text="❌ حذف", callback_data=f"rem:delete:{reminder_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="⏰ ۱۰ دقیقه بعد", callback_data=f"rem:snooze10:{reminder_id}"),
        InlineKeyboardButton(text="🕐 یک ساعت بعد", callback_data=f"rem:snooze60:{reminder_id}"),
        InlineKeyboardButton(text="📅 فردا", callback_data=f"rem:snooze1d:{reminder_id}"),
    )
    return builder.as_markup()


def snooze_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    """Extended snooze options."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏰ ۱۰ دقیقه", callback_data=f"rem:snooze10:{reminder_id}"),
        InlineKeyboardButton(text="🕐 ۳۰ دقیقه", callback_data=f"rem:snooze30:{reminder_id}"),
        InlineKeyboardButton(text="⏱ ۱ ساعت", callback_data=f"rem:snooze60:{reminder_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="📅 فردا", callback_data=f"rem:snooze1d:{reminder_id}"),
        InlineKeyboardButton(text="❌ حذف", callback_data=f"rem:delete:{reminder_id}"),
    )
    return builder.as_markup()


def confirm_reminder_keyboard() -> InlineKeyboardMarkup:
    """Shown when bot auto-detects a reminder from natural text."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ بله، ثبت کن", callback_data="confirm:yes"),
        InlineKeyboardButton(text="✏️ ویرایش", callback_data="confirm:edit"),
        InlineKeyboardButton(text="❌ لغو", callback_data="confirm:cancel"),
    )
    return builder.as_markup()


def list_item_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    """
    Buttons shown for each reminder in the list view:
    ✏️ ویرایش | 🗑 حذف
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✏️ ویرایش", callback_data=f"list:edit:{reminder_id}"),
        InlineKeyboardButton(text="🗑 حذف", callback_data=f"list:delete:{reminder_id}"),
    )
    return builder.as_markup()


def edit_options_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    """
    Sub-options shown after tapping ✏️ ویرایش:
    📝 ویرایش متن | 🕒 ویرایش زمان
    ❌ لغو
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📝 ویرایش متن", callback_data=f"edit:text:{reminder_id}"),
        InlineKeyboardButton(text="🕒 ویرایش زمان", callback_data=f"edit:time:{reminder_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="❌ لغو", callback_data="edit:cancel"),
    )
    return builder.as_markup()


def confirm_list_delete_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    """Confirmation keyboard for deleting a reminder from the list."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ بله، حذف کن", callback_data=f"list:confirm_delete:{reminder_id}"),
        InlineKeyboardButton(text="❌ خیر", callback_data="list:cancel_delete"),
    )
    return builder.as_markup()


def list_filter_button_keyboard() -> InlineKeyboardMarkup:
    """Single filter button shown on the list header — opens the filter menu."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔍 فیلتر", callback_data="filter:open"),
    )
    return builder.as_markup()


def filter_options_keyboard() -> InlineKeyboardMarkup:
    """Full filter options — shown after the user taps 🔍 فیلتر."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📅 امروز", callback_data="filter:today"),
        InlineKeyboardButton(text="🌤 فردا", callback_data="filter:tomorrow"),
    )
    builder.row(
        InlineKeyboardButton(text="📆 این هفته", callback_data="filter:week"),
        InlineKeyboardButton(text="🔁 تکرارشونده", callback_data="filter:recurring"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 همه", callback_data="filter:all"),
    )
    return builder.as_markup()


def filter_keyboard() -> InlineKeyboardMarkup:
    """Alias kept for backward compatibility."""
    return filter_options_keyboard()
