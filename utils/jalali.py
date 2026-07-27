"""
Jalali (Shamsi) calendar utilities.
"""
from datetime import datetime

import jdatetime
import pytz


def to_jalali_str(dt: datetime, tz: str = "Asia/Tehran") -> str:
    """
    Convert a UTC or tz-aware datetime to a Jalali date string.
    Returns: e.g. "۱۴۰۳/۰۵/۱۲"
    """
    local_tz = pytz.timezone(tz)
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    local_dt = dt.astimezone(local_tz)
    jdt = jdatetime.datetime.fromgregorian(datetime=local_dt)
    return jdt.strftime("%Y/%m/%d")


def jalali_datetime_str(dt: datetime, tz: str = "Asia/Tehran") -> str:
    """
    Convert to a full Jalali date + time string.
    Returns: e.g. "۱۴۰۳/۰۵/۱۲ ساعت ۰۸:۳۰"
    """
    local_tz = pytz.timezone(tz)
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    local_dt = dt.astimezone(local_tz)
    jdt = jdatetime.datetime.fromgregorian(datetime=local_dt)
    date_part = jdt.strftime("%Y/%m/%d")
    time_part = local_dt.strftime("%H:%M")
    return f"{date_part} ساعت {time_part}"


def to_persian_digits(text: str) -> str:
    """Convert ASCII digits to Persian (Eastern Arabic) digits."""
    mapping = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
    return text.translate(mapping)


def from_persian_digits(text: str) -> str:
    """Convert Persian (Eastern Arabic) digits to ASCII digits."""
    mapping = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
    return text.translate(mapping)
