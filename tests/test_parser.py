"""
Test script for PersianTimeParser — covers all cases from the spec.
Run: cd telegram-bot && python tests/test_parser.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parser import parse_message
from datetime import datetime, timedelta
import pytz

TZ = "Asia/Tehran"
PASS = "✅"
FAIL = "❌"

_tz = pytz.timezone(TZ)


def _check(label: str, text: str, expect_time: bool = True,
           hour: int = None, minute: int = None, tomorrow: bool = False):
    """Check that parse_message extracts time correctly."""
    result = parse_message(text, TZ)
    ok_time = result.time_found == expect_time

    time_detail = ""
    if result.time_found and result.remind_at:
        local = result.remind_at.astimezone(_tz)
        time_detail = f" → {local.strftime('%H:%M')} ({local.strftime('%d')})"
        # Check expected hour/minute if provided
        if hour is not None and ok_time:
            if local.hour != hour:
                ok_time = False
                time_detail += f"  ⚠ انتظار: {hour:02d}:{(minute or 0):02d}"
        if minute is not None and ok_time and result.time_found:
            local2 = result.remind_at.astimezone(_tz)
            if local2.minute != minute:
                ok_time = False
                time_detail += f"  ⚠ دقیقه انتظار: {minute}"
        if tomorrow and ok_time:
            now_local = datetime.now(_tz)
            local2 = result.remind_at.astimezone(_tz)
            if local2.date() != (now_local + timedelta(days=1)).date():
                ok_time = False
                time_detail += "  ⚠ باید فردا باشد"

    body = f" | متن: «{result.text}»" if result.text else ""
    status = PASS if ok_time else FAIL
    print(f"  {status}  {label:30s}{time_detail}{body}")
    return ok_time


def run_tests():
    print("\n" + "="*65)
    print("  تست Parser فارسی")
    print("="*65)

    now_local = datetime.now(_tz)
    total, passed = 0, 0

    cases = [
        # ── relative time (time_found = True) ──────────────────────────
        dict(label="یه ساعت",         text="یه ساعت یادم بنداز",          hour=now_local.hour+1 if now_local.hour < 23 else 0),
        dict(label="یه دقیقه",        text="یه دقیقه یادم بنداز",         expect_time=True),
        dict(label="یه ربع",          text="یه ربع یادم بنداز",           minute=((now_local.minute + 15) % 60)),
        dict(label="یه ساعت دیگه",    text="یه ساعت دیگه یادم بنداز",     expect_time=True),
        dict(label="چند دقیقه دیگه",  text="چند دقیقه دیگه یادم بنداز",   expect_time=True),
        dict(label="دو ساعت",         text="دو ساعت دیگه یادم بنداز",     expect_time=True),
        dict(label="سه ساعت",         text="سه ساعت دیگه یادم بنداز",     expect_time=True),
        dict(label="نیم ساعت",        text="نیم ساعت دیگه یادم بنداز",    minute=((now_local.minute + 30) % 60)),
        dict(label="۳۰ دقیقه دیگه",   text="۳۰ دقیقه دیگه داروهام",       expect_time=True),
        # ── time of day ───────────────────────────────────────────────
        dict(label="هفت صبح",         text="هفت صبح یادم بنداز",          hour=7),
        dict(label="ده شب",           text="ده شب یادم بنداز",            hour=22),
        dict(label="امشب ۱۰",         text="امشب ۱۰ یادم بنداز",          hour=22),
        dict(label="امروز ۵ عصر",     text="امروز ۵ عصر یادم بنداز",      hour=17),
        dict(label="ده صبح",          text="ده صبح یادم بنداز",           hour=10),
        dict(label="نه شب",           text="نه شب یادم بنداز",            hour=21),
        # ── H و نیم / H و ربع ───────────────────────────────────────
        dict(label="هفت و نیم",       text="هفت و نیم یادم بنداز",        hour=7, minute=30),
        dict(label="هشت و ربع",       text="هشت و ربع یادم بنداز",        hour=8, minute=15),
        dict(label="هشت و نیم",       text="هشت و نیم یادم بنداز",        hour=8, minute=30),
        dict(label="ساعت یازده",      text="ساعت یازده یادم بنداز",       hour=11),
        # ── فردا ─────────────────────────────────────────────────────
        dict(label="فردا ۸",          text="فردا ۸ یادم بنداز",           hour=8, tomorrow=True),
        dict(label="فردا ۸ صبح",      text="فردا ۸ صبح یادم بنداز",       hour=8, tomorrow=True),
        dict(label="فردا ۸ شب",       text="فردا ۸ شب یادم بنداز",        hour=20, tomorrow=True),
        # ── شب/صبح ───────────────────────────────────────────────────
        dict(label="یازده شب",        text="یازده شب یادم بنداز",         hour=23),
        # ── repeat ────────────────────────────────────────────────────
        dict(label="هرشب ساعت ۱۰",   text="هرشب ساعت ۱۰ یادم بنداز",    hour=22),
        dict(label="هر شب ساعت ۱۰",  text="هر شب ساعت ۱۰ یادم بنداز",   hour=22),
        dict(label="هرروز ساعت ۹",    text="هرروز ساعت ۹ آب بخورم",       hour=9),
        dict(label="هر روز ساعت ۹",   text="هر روز ساعت ۹ آب بخورم",      hour=9),
    ]

    for case in cases:
        total += 1
        if _check(**case):
            passed += 1

    print()
    print(f"  نتیجه: {passed}/{total} موفق")
    print("="*65 + "\n")
    return passed == total


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
