"""
FSM states for conversation flows.
"""
from aiogram.fsm.state import State, StatesGroup


class ReminderCreation(StatesGroup):
    """States when creating a reminder."""
    waiting_for_time = State()   # We have text, need time
    waiting_for_text = State()   # We have time, need text
    confirming = State()         # Both extracted, confirm with user


class ForwardReminder(StatesGroup):
    """States when handling a forwarded message."""
    waiting_for_time = State()


class Settings(StatesGroup):
    """States for settings menu."""
    main = State()
    waiting_for_default_time = State()
    confirming_delete = State()
    waiting_for_agenda_time = State()   # Waiting for daily agenda time input


class ReminderEdit(StatesGroup):
    """States for editing an existing reminder."""
    selecting_field = State()    # Showing edit options (text vs time)
    waiting_for_text = State()   # Waiting for new reminder body text
    waiting_for_time = State()   # Waiting for new reminder time


class ReminderList(StatesGroup):
    """States while the user is browsing the reminders list."""
    viewing = State()   # Active list — tracks header msg + item msg IDs for clean refresh
