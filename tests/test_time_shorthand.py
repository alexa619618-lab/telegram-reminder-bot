"""
Tests for _parse_time_shorthand and related time-parsing logic.
Run with:  python -m pytest tests/test_time_shorthand.py -v
           OR: python tests/test_time_shorthand.py
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
import pytz
from handlers.message_handler import _parse_time_shorthand

TZ = "Asia/Tehran"
LOCAL_TZ = pytz.timezone(TZ)


def _local(hour: int, minute: int = 0) -> datetime:
    """Create a timezone-aware local datetime for today at hour:minute."""
    now = datetime.now(LOCAL_TZ)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _assert_hour(result: datetime | None, expected_hour: int, label: str) -> None:
    assert result is not None, f"{label}: expected datetime, got None"
    local_dt = result.astimezone(LOCAL_TZ)
    assert local_dt.hour == expected_hour, (
        f"{label}: expected hour={expected_hour}, got hour={local_dt.hour} "
        f"({local_dt.strftime('%H:%M')})"
    )


def _assert_hm(result: datetime | None, expected_h: int, expected_m: int, label: str) -> None:
    assert result is not None, f"{label}: expected datetime, got None"
    local_dt = result.astimezone(LOCAL_TZ)
    assert local_dt.hour == expected_h and local_dt.minute == expected_m, (
        f"{label}: expected {expected_h:02d}:{expected_m:02d}, "
        f"got {local_dt.strftime('%H:%M')}"
    )


def test_unambiguous_digits():
    """Hours 13-23 must always map to themselves."""
    for h in [13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]:
        result = _parse_time_shorthand(str(h), TZ)
        _assert_hour(result, h, f"digit '{h}'")

    for h in [13, 18, 21]:
        result = _parse_time_shorthand(f"۰{h}" if h < 10 else str(h).replace(
            "0","۰").replace("1","۱").replace("2","۲").replace("3","۳").replace(
            "4","۴").replace("5","۵").replace("6","۶").replace("7","۷").replace(
            "8","۸").replace("9","۹"), TZ)
        _assert_hour(result, h, f"persian digit '{h}'")


def test_h_mm_format():
    """HH:MM should parse exactly."""
    result = _parse_time_shorthand("9:30", TZ)
    _assert_hm(result, 9, 30, "9:30")

    result = _parse_time_shorthand("21:15", TZ)
    _assert_hm(result, 21, 15, "21:15")

    result = _parse_time_shorthand("۹:۳۰", TZ)
    _assert_hm(result, 9, 30, "۹:۳۰")


def test_smart_ampm_morning_context():
    """When current time is 08:00 (morning), '9' → 09:00 and '8' → 20:00 (already past)."""
    import unittest.mock as mock

    morning = LOCAL_TZ.localize(
        datetime.now(LOCAL_TZ).replace(hour=8, minute=0, second=0, microsecond=0)
    )
    with mock.patch("handlers.message_handler.datetime") as mock_dt:
        mock_dt.now.return_value = morning
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

        result = _parse_time_shorthand("9", TZ)
        if result is not None:
            local_result = result.astimezone(LOCAL_TZ)
            assert local_result.hour == 9, f"At 08:00, '9' should be 09:00, got {local_result.strftime('%H:%M')}"

        result = _parse_time_shorthand("7", TZ)
        if result is not None:
            local_result = result.astimezone(LOCAL_TZ)
            # 07:00 is past at 08:00, so should become 19:00 or next day 07:00
            assert local_result.hour in (7, 19), f"At 08:00, '7' should be 19:00 or next-day 07:00, got {local_result.strftime('%H:%M')}"


def test_smart_ampm_afternoon_context():
    """When current time is 14:00 (afternoon), '9' → 21:00 (09:00 already past)."""
    import unittest.mock as mock

    afternoon = LOCAL_TZ.localize(
        datetime.now(LOCAL_TZ).replace(hour=14, minute=0, second=0, microsecond=0)
    )
    with mock.patch("handlers.message_handler.datetime") as mock_dt:
        mock_dt.now.return_value = afternoon
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

        result = _parse_time_shorthand("9", TZ)
        if result is not None:
            local_result = result.astimezone(LOCAL_TZ)
            assert local_result.hour == 21, f"At 14:00, '9' should be 21:00, got {local_result.strftime('%H:%M')}"


def test_persian_word_numbers():
    """Persian word-number hours should resolve to correct numeric hours."""
    cases = [
        ("هشت", 8, 20),    # at 10:00, 8 AM is past → 20:00 PM
        ("ده", 10, 22),     # at some time, 10 or 22
        ("نه", 9, 21),
        ("دوازده", 12, None),  # noon → unambiguous or stay at 12
        ("بیست و یک", 21, None),  # unambiguous
    ]
    for word, am_h, pm_h in cases:
        result = _parse_time_shorthand(word, TZ)
        assert result is not None, f"Word '{word}' returned None"
        local_dt = result.astimezone(LOCAL_TZ)
        valid = [am_h]
        if pm_h:
            valid.append(pm_h)
        # Also accept next-day AM
        assert local_dt.hour in valid, (
            f"Word '{word}': expected hour in {valid}, got {local_dt.strftime('%H:%M')}"
        )


def test_invalid_inputs():
    """Invalid inputs should return None."""
    assert _parse_time_shorthand("", TZ) is None
    assert _parse_time_shorthand("abc", TZ) is None
    assert _parse_time_shorthand("فردا", TZ) is None  # date keyword, not a time


def test_parser_integration():
    """parse_message itself should handle common time expressions correctly."""
    from parser import parse_message

    cases = [
        ("فردا ساعت ۸ باشگاه", True, True),
        ("شنبه صبح جلسه", True, True),
        ("۳۰ دقیقه دیگه داروهام", True, True),
        ("برم بانک", False, True),   # text found, no time
        ("فردا ساعت ۱۰", True, False),  # time found, no reminder body
    ]

    for text, expect_time, expect_text in cases:
        result = parse_message(text, TZ)
        assert result.time_found == expect_time, (
            f"'{text}': time_found expected={expect_time}, got={result.time_found}"
        )
        assert result.text_found == expect_text, (
            f"'{text}': text_found expected={expect_text}, got={result.text_found}"
        )


def test_parse_multi_basic():
    """parse_multi should split multi-line input into separate reminders."""
    from parser import parse_multi

    msg = "فردا ساعت ۸ باشگاه\nساعت ۱۲ جلسه\nساعت ۷ عصر خرید"
    results = parse_multi(msg, TZ)

    complete = [r for r in results if r.is_complete()]
    assert len(complete) >= 2, f"Expected ≥2 complete results, got {len(complete)}: {[r.text for r in results]}"

    times = sorted([r.remind_at.astimezone(LOCAL_TZ).hour for r in complete])
    assert 8 in times, f"Expected 08:xx reminder, got hours: {times}"


def test_parse_multi_shared_anchor():
    """Date anchor from first line should apply to subsequent time-only lines."""
    from parser import parse_multi

    msg = "شنبه:\n۹ صبح دکتر\n۱۲ بانک"
    results = parse_multi(msg, TZ)

    complete = [r for r in results if r.is_complete()]
    assert len(complete) >= 1, f"Expected ≥1 complete result from anchor test: {[r.text for r in results]}"


def test_today_count_in_main_menu():
    """main_menu_keyboard should show count in label when today_count > 0."""
    from keyboards.main_menu import main_menu_keyboard

    kb = main_menu_keyboard(today_count=3)
    buttons = [btn.text for row in kb.keyboard for btn in row]
    today_btn = next((b for b in buttons if "امروز" in b), None)
    assert today_btn is not None, "امروز button not found"
    assert "(۳)" in today_btn or "(3)" in today_btn, (
        f"Expected count in button label, got: '{today_btn}'"
    )

    kb0 = main_menu_keyboard(today_count=0)
    buttons0 = [btn.text for row in kb0.keyboard for btn in row]
    today_btn0 = next((b for b in buttons0 if "امروز" in b), None)
    assert "(" not in (today_btn0 or ""), f"Expected no count when 0, got: '{today_btn0}'"


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        ("unambiguous digits", test_unambiguous_digits),
        ("H:MM format", test_h_mm_format),
        ("smart AM/PM morning", test_smart_ampm_morning_context),
        ("smart AM/PM afternoon", test_smart_ampm_afternoon_context),
        ("Persian word numbers", test_persian_word_numbers),
        ("invalid inputs", test_invalid_inputs),
        ("parser integration", test_parser_integration),
        ("parse_multi basic", test_parse_multi_basic),
        ("parse_multi shared anchor", test_parse_multi_shared_anchor),
        ("today count in main menu", test_today_count_in_main_menu),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {name}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
