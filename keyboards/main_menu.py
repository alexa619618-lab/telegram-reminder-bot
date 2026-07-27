"""
Main menu reply keyboard and cancel keyboard.
"""
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove


def main_menu_keyboard(today_count: int = 0) -> ReplyKeyboardMarkup:
    """Persistent reply keyboard shown to the user at all times.
    
    Args:
        today_count: Number of today's reminders. If > 0, shown on button.
    """
    today_label = f"📅 امروز ({today_count})" if today_count > 0 else "📅 امروز"
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📋 یادآورهای من"),
                KeyboardButton(text=today_label),
            ],
            [
                KeyboardButton(text="⚙️ تنظیمات"),
                KeyboardButton(text="❓ راهنما"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="یادآوری‌ات رو بنویس...",
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard shown while bot is waiting for input, with a Cancel button."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ لغو")]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
