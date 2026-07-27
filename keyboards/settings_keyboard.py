"""
Keyboards for the settings menu.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def settings_main_keyboard(
    default_time: str | None,
    enabled: bool,
    forward_behavior: str,
    daily_agenda_enabled: bool = False,
    daily_agenda_time: str = "08:00",
) -> InlineKeyboardMarkup:
    """Main settings inline keyboard with current state displayed."""
    builder = InlineKeyboardBuilder()

    # Default time row
    if default_time:
        status_icon = "🟢" if enabled else "🔴"
        builder.row(
            InlineKeyboardButton(
                text=f"🕘 زمان پیش‌فرض: {default_time} {status_icon}",
                callback_data="settings:change_time",
            )
        )
        toggle_label = "⛔ غیرفعال کردن" if enabled else "✅ فعال کردن"
        builder.row(
            InlineKeyboardButton(text=toggle_label, callback_data="settings:toggle"),
            InlineKeyboardButton(text="🗑 حذف", callback_data="settings:delete_time"),
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="🕘 تنظیم زمان پیش‌فرض",
                callback_data="settings:change_time",
            )
        )

    # Forward behavior row
    fwd_icon = "✅" if forward_behavior == "use_default" else "🕒"
    fwd_label = (
        f"{fwd_icon} فوروارد: زمان پیش‌فرض"
        if forward_behavior == "use_default"
        else f"{fwd_icon} فوروارد: هر بار بپرس"
    )
    builder.row(
        InlineKeyboardButton(text=fwd_label, callback_data="settings:toggle_forward")
    )

    # Daily agenda row
    agenda_icon = "🟢" if daily_agenda_enabled else "🔴"
    builder.row(
        InlineKeyboardButton(
            text=f"☀️ خلاصه روزانه: {daily_agenda_time} {agenda_icon}",
            callback_data="settings:daily_agenda",
        )
    )

    return builder.as_markup()


def default_time_options_keyboard() -> InlineKeyboardMarkup:
    """Quick time preset options."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="08:00", callback_data="set_time:08:00"),
        InlineKeyboardButton(text="09:00", callback_data="set_time:09:00"),
        InlineKeyboardButton(text="10:00", callback_data="set_time:10:00"),
    )
    builder.row(
        InlineKeyboardButton(text="12:00", callback_data="set_time:12:00"),
        InlineKeyboardButton(text="18:00", callback_data="set_time:18:00"),
        InlineKeyboardButton(text="21:00", callback_data="set_time:21:00"),
    )
    builder.row(
        InlineKeyboardButton(text="❌ لغو", callback_data="set_time:cancel"),
    )
    return builder.as_markup()


def forward_behavior_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ استفاده از زمان پیش‌فرض", callback_data="fwd:use_default"),
        InlineKeyboardButton(text="🕒 هر بار زمان را بپرس", callback_data="fwd:ask"),
    )
    return builder.as_markup()


def confirm_delete_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ بله، حذف کن", callback_data="del_time:yes"),
        InlineKeyboardButton(text="❌ خیر", callback_data="del_time:no"),
    )
    return builder.as_markup()


def daily_agenda_keyboard(enabled: bool, current_time: str) -> InlineKeyboardMarkup:
    """Keyboard for daily agenda settings."""
    builder = InlineKeyboardBuilder()

    if enabled:
        builder.row(
            InlineKeyboardButton(text="❌ غیرفعال کردن", callback_data="agenda:disable"),
        )
    else:
        builder.row(
            InlineKeyboardButton(text="✅ فعال کردن", callback_data="agenda:enable"),
        )

    # Time presets
    builder.row(
        InlineKeyboardButton(text="07:00", callback_data="agenda_time:07:00"),
        InlineKeyboardButton(text="08:00", callback_data="agenda_time:08:00"),
        InlineKeyboardButton(text="09:00", callback_data="agenda_time:09:00"),
    )
    builder.row(
        InlineKeyboardButton(text="09:30", callback_data="agenda_time:09:30"),
        InlineKeyboardButton(text="10:00", callback_data="agenda_time:10:00"),
        InlineKeyboardButton(text="07:30", callback_data="agenda_time:07:30"),
    )
    builder.row(
        InlineKeyboardButton(text="✏️ ساعت دلخواه", callback_data="agenda:custom_time"),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="agenda:back"),
    )
    return builder.as_markup()
