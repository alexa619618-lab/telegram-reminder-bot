"""
Persian Natural Language Time Parser — v3.

Extracts datetime and repeat information from Persian text using
a multi-stage rule-based pipeline — no AI required.

Pipeline stages:
  1. Normalization   — unify digits, whitespace, half-spaces
  2. Tokenization    — lightweight token extraction
  3. Rule Matching   — ordered priority rules (repeat → time)
  4. Conflict Resolution — explicit time overrides defaults
  5. DateTime Resolution — final UTC datetime assembly

New in v3:
  • Word-number hours: «ساعت هفت», «ساعت ده»
  • Word-number + period: «ده شب», «هشت صبح»
  • «امشب ۱۰» — tonight with explicit hour
  • غروب (18:00) and بامداد (4:00) keywords
  • Without-space repeats: هرشب / هرروز / هرهفته (already covered by s*)
  • Better tolerance for extra spaces, half-spaces, common typos
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import jdatetime
import pytz

from config import config
from models.reminder import RepeatType


# ---------------------------------------------------------------------------
# Stage 1 — Normalization helpers
# ---------------------------------------------------------------------------

_FA_TO_EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def fa_to_en(text: str) -> str:
    """Convert Persian/Arabic digits to ASCII digits."""
    return text.translate(_FA_TO_EN)


def normalise(text: str) -> str:
    """
    Normalise Persian text:
      - Convert Persian/Arabic digits to ASCII
      - Replace ZWNJ (half-space) with regular space
      - Collapse all whitespace runs to a single space
      - Strip leading/trailing whitespace
      - Normalise Arabic/Persian letter variants
    """
    text = fa_to_en(text)
    text = text.replace("\u200c", " ")   # ZWNJ (half-space) → space
    text = text.replace("\u200b", " ")   # zero-width space
    text = text.replace("\u00a0", " ")   # non-breaking space
    text = text.replace("\u0643", "\u06a9")  # Arabic ك → Persian ک
    text = text.replace("\u0649", "\u06cc")  # Arabic ى → Persian ی
    text = text.replace("\u064a", "\u06cc")  # Arabic ي → Persian ی
    text = text.replace("\u0647\u0654", "\u0647")  # ه‎ٔ → ه
    # Normalise common colloquial shortcuts
    text = text.replace("نيم", "نیم")
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Stage 2 — Word-number tables (Tokenization support)
# ---------------------------------------------------------------------------

_WORD_NUMS: dict[str, int] = {
    "یک": 1,   "يك": 1,   "یکی": 1,   "یه": 1,   "يه": 1,
    "دو": 2,   "سه": 3,   "چهار": 4,  "پنج": 5,
    "شش": 6,   "هفت": 7,  "هشت": 8,   "نه": 9,
    "ده": 10,  "یازده": 11, "دوازده": 12,
    "سیزده": 13, "چهارده": 14, "پانزده": 15,
    "شانزده": 16, "هفده": 17, "هجده": 18,
    "نوزده": 19, "بیست": 20,
    "سی": 30,  "چهل": 40, "پنجاه": 50,
}

_COMPOUND_WORD_NUMS: dict[str, int] = {
    "بیست و یک": 21, "بیست و دو": 22, "بیست و سه": 23,
    "بیست و چهار": 24, "بیست و پنج": 25, "بیست و شش": 26,
    "بیست و هفت": 27, "بیست و هشت": 28, "بیست و نه": 29,
    "سی و پنج": 35, "چهل و پنج": 45,
}

_ORDINALS: dict[str, int] = {
    "اول": 1,  "دوم": 2,  "سوم": 3,  "چهارم": 4, "پنجم": 5,
    "ششم": 6,  "هفتم": 7, "هشتم": 8, "نهم": 9,   "دهم": 10,
    "یازدهم": 11, "دوازدهم": 12, "سیزدهم": 13, "چهاردهم": 14,
    "پانزدهم": 15, "شانزدهم": 16, "هفدهم": 17, "هجدهم": 18,
    "نوزدهم": 19, "بیستم": 20,
    "بیست و یکم": 21, "بیست و دوم": 22, "بیست و سوم": 23,
    "بیست و چهارم": 24, "بیست و پنجم": 25, "بیست و ششم": 26,
    "بیست و هفتم": 27, "بیست و هشتم": 28, "بیست و نهم": 29,
    "سی ام": 30, "سی‌ام": 30, "سیم": 30, "سی و یکم": 31,
}

_JALALI_MONTHS: dict[str, int] = {
    "فروردین": 1,   "اردیبهشت": 2, "خرداد": 3,
    "تیر": 4,       "مرداد": 5,    "شهریور": 6,
    "مهر": 7,       "آبان": 8,     "آذر": 9,
    "دی": 10,       "بهمن": 11,    "اسفند": 12,
}

_ORDINAL_PATTERN = "|".join(re.escape(k) for k in sorted(_ORDINALS, key=len, reverse=True))
_WORD_NUM_PATTERN = "|".join(
    re.escape(k) for k in sorted({**_COMPOUND_WORD_NUMS, **_WORD_NUMS}, key=len, reverse=True)
)
_MONTH_PATTERN = "|".join(re.escape(k) for k in sorted(_JALALI_MONTHS, key=len, reverse=True))


def _word_to_int(word: str) -> int | None:
    """Convert a Persian word number to int (compound first, then simple)."""
    w = word.strip()
    if w in _COMPOUND_WORD_NUMS:
        return _COMPOUND_WORD_NUMS[w]
    return _WORD_NUMS.get(w)


# ---------------------------------------------------------------------------
# Stage 3 — Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ParseResult:
    """Holds the result of parsing a user message."""
    remind_at: Optional[datetime] = None       # Absolute datetime (UTC)
    text: Optional[str] = None                 # The reminder body text
    repeat_type: RepeatType = RepeatType.NONE
    repeat_interval: Optional[int] = None
    weekday: Optional[int] = None              # 0=Mon … 6=Sun (for WEEKDAY repeat)
    time_found: bool = False
    text_found: bool = False
    is_repeat: bool = False

    def is_complete(self) -> bool:
        return self.remind_at is not None and self.text_found


# ---------------------------------------------------------------------------
# Day-of-week mapping
# ---------------------------------------------------------------------------

_WEEKDAYS: dict[str, int] = {
    "شنبه": 5,
    "يكشنبه": 6, "یکشنبه": 6, "يك شنبه": 6, "یک شنبه": 6,
    "دوشنبه": 0, "دو شنبه": 0,
    "سه‌شنبه": 1, "سه شنبه": 1, "سه‌ شنبه": 1,
    "چهارشنبه": 2, "چهار‌شنبه": 2, "چهار شنبه": 2,
    "پنجشنبه": 3, "پنج‌شنبه": 3, "پنج شنبه": 3,
    "جمعه": 4,
}

_WEEKDAY_PATTERN = "|".join(re.escape(k) for k in sorted(_WEEKDAYS, key=len, reverse=True))


def _next_weekday(target_weekday: int, now: datetime) -> datetime:
    """Return the next occurrence of target_weekday (0=Mon…6=Sun) from now."""
    days_ahead = (target_weekday - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (now + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Jalali date helpers
# ---------------------------------------------------------------------------

def _jalali_to_gregorian(jyear: int, jmonth: int, jday: int, tz: pytz.BaseTzInfo) -> datetime:
    """Convert a Jalali date to a UTC-aware Gregorian datetime (at 09:00 local)."""
    jdt = jdatetime.datetime(jyear, jmonth, jday, 9, 0, 0)
    gdt = jdt.togregorian()
    local = tz.localize(gdt)
    return local.astimezone(pytz.utc)


def _current_jalali(now: datetime) -> jdatetime.datetime:
    return jdatetime.datetime.fromgregorian(datetime=now)


# ---------------------------------------------------------------------------
# Stage 3 — Core parser
# ---------------------------------------------------------------------------

class PersianTimeParser:
    """
    Multi-stage stateless parser.
    Call ``parse(text, user_tz)`` to get a ParseResult.

    Internal pipeline per call:
      normalise → _extract_repeat → _extract_time → _clean_body
    """

    def __init__(self) -> None:
        self._tz_cache: dict[str, pytz.BaseTzInfo] = {}

    def _tz(self, tz_name: str) -> pytz.BaseTzInfo:
        if tz_name not in self._tz_cache:
            self._tz_cache[tz_name] = pytz.timezone(tz_name)
        return self._tz_cache[tz_name]

    def _now(self, tz_name: str) -> datetime:
        return datetime.now(self._tz(tz_name))

    def _localise(self, dt: datetime, tz_name: str) -> datetime:
        if dt.tzinfo is None:
            dt = self._tz(tz_name).localize(dt)
        return dt

    def _to_utc(self, dt: datetime) -> datetime:
        return dt.astimezone(pytz.utc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, raw: str, tz_name: str = "Asia/Tehran") -> ParseResult:
        result = ParseResult()
        text = normalise(raw)
        now_local = self._now(tz_name)

        # Stage 3a: Detect and strip repeat patterns
        text, result = self._extract_repeat(text, result, now_local, tz_name)

        # Stage 3b: Extract time expression
        text, result = self._extract_time(text, result, now_local, tz_name)

        # Stage 5: Body is whatever remains
        body = self._clean_body(text)
        if body:
            result.text = body
            result.text_found = True

        return result

    # ------------------------------------------------------------------
    # Stage 3a — Repeat extraction
    # ------------------------------------------------------------------

    def _extract_repeat(
        self, text: str, result: ParseResult, now: datetime, tz: str
    ) -> tuple[str, ParseResult]:
        patterns = [
            # ── minutes ──────────────────────────────────────────────────
            (r"هر\s*ربع\s*ساعت",
             lambda m, r, n, z: self._set_repeat(r, RepeatType.EVERY_N_MINUTES, 15)),
            (r"هر\s*نیم\s*ساعت",
             lambda m, r, n, z: self._set_repeat(r, RepeatType.EVERY_N_MINUTES, 30)),
            (r"هر\s*(\d+)\s*دقیقه", self._handle_every_n_minutes),
            (rf"هر\s*({_WORD_NUM_PATTERN})\s*دقیقه", self._handle_every_n_minutes_word),

            # ── hours ─────────────────────────────────────────────────────
            (r"هر\s*(\d+)\s*ساعت", self._handle_every_n_hours),
            (rf"هر\s*({_WORD_NUM_PATTERN})\s*ساعت", self._handle_every_n_hours_word),
            # هر صبح / هر شب — DAILY at specific default time
            (r"هر\s*صبح", self._handle_every_morning),
            (r"هر\s*شب",  self._handle_every_night),

            # ── days ──────────────────────────────────────────────────────
            (r"یک\s*روز\s*در\s*میان|یک‌روز‌درمیان",
             lambda m, r, n, z: self._set_repeat(r, RepeatType.EVERY_N_DAYS, 2)),
            (r"هر\s*(\d+)\s*روز(?!\s*در)", self._handle_every_n_days),
            (rf"هر\s*({_WORD_NUM_PATTERN})\s*روز(?!\s*در)", self._handle_every_n_days_word),
            # هرروز / هر روز / روزانه  — without-space already covered by \s*
            (r"(?:هر\s*روز|روزانه|هرروز)",
             lambda m, r, n, z: self._set_repeat(r, RepeatType.DAILY)),

            # ── weeks ─────────────────────────────────────────────────────
            (r"هر\s*(\d+)\s*هفته", self._handle_every_n_weeks),
            (rf"هر\s*({_WORD_NUM_PATTERN})\s*هفته", self._handle_every_n_weeks_word),
            # هرهفته / هفتگی
            (r"(?:هر\s*هفته|هفتگی|هفته\s*ای\s*یک\s*بار)",
             lambda m, r, n, z: self._set_repeat(r, RepeatType.WEEKLY)),

            # ── specific weekday ──────────────────────────────────────────
            (rf"هر\s*({_WEEKDAY_PATTERN})", self._handle_every_weekday),

            # ── months ────────────────────────────────────────────────────
            (r"هر\s*(\d+)\s*ماه", self._handle_every_n_months),
            (rf"هر\s*({_WORD_NUM_PATTERN})\s*ماه", self._handle_every_n_months_word),
            # هرماه / ماهانه
            (r"(?:هر\s*ماه|ماهانه|ماهی\s*یک\s*بار)",
             lambda m, r, n, z: self._set_repeat(r, RepeatType.MONTHLY)),

            # ── years ─────────────────────────────────────────────────────
            (r"(?:هر\s*سال|سالانه|سالی\s*یک\s*بار)",
             lambda m, r, n, z: self._set_repeat(r, RepeatType.YEARLY)),
        ]

        for pattern, handler in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                result = handler(m, result, now, tz)
                text = text[:m.start()] + text[m.end():]
                text = re.sub(r"\s+", " ", text).strip()
                result.is_repeat = True
                break

        return text, result

    # ── repeat handlers ───────────────────────────────────────────────────

    @staticmethod
    def _set_repeat(
        result: ParseResult,
        repeat_type: RepeatType,
        interval: int | None = None,
        weekday: int | None = None,
    ) -> ParseResult:
        result.repeat_type = repeat_type
        if interval is not None:
            result.repeat_interval = interval
        if weekday is not None:
            result.weekday = weekday
        return result

    def _handle_every_n_minutes(self, m, result, now, tz):
        return self._set_repeat(result, RepeatType.EVERY_N_MINUTES, int(m.group(1)))

    def _handle_every_n_minutes_word(self, m, result, now, tz):
        val = _word_to_int(m.group(1))
        return self._set_repeat(result, RepeatType.EVERY_N_MINUTES, val) if val else result

    def _handle_every_n_hours(self, m, result, now, tz):
        return self._set_repeat(result, RepeatType.EVERY_N_HOURS, int(m.group(1)))

    def _handle_every_n_hours_word(self, m, result, now, tz):
        val = _word_to_int(m.group(1))
        return self._set_repeat(result, RepeatType.EVERY_N_HOURS, val) if val else result

    def _handle_every_morning(self, m, result, now, tz):
        result = self._set_repeat(result, RepeatType.DAILY)
        result._tod_hint = "صبح"  # type: ignore[attr-defined]
        return result

    def _handle_every_night(self, m, result, now, tz):
        result = self._set_repeat(result, RepeatType.DAILY)
        result._tod_hint = "شب"  # type: ignore[attr-defined]
        return result

    def _handle_every_n_days(self, m, result, now, tz):
        return self._set_repeat(result, RepeatType.EVERY_N_DAYS, int(m.group(1)))

    def _handle_every_n_days_word(self, m, result, now, tz):
        val = _word_to_int(m.group(1))
        return self._set_repeat(result, RepeatType.EVERY_N_DAYS, val) if val else result

    def _handle_every_n_weeks(self, m, result, now, tz):
        return self._set_repeat(result, RepeatType.EVERY_N_WEEKS, int(m.group(1)))

    def _handle_every_n_weeks_word(self, m, result, now, tz):
        val = _word_to_int(m.group(1))
        return self._set_repeat(result, RepeatType.EVERY_N_WEEKS, val) if val else result

    def _handle_every_weekday(self, m, result, now, tz):
        day_name = m.group(1)
        target = _WEEKDAYS.get(day_name)
        if target is not None:
            result = self._set_repeat(result, RepeatType.WEEKDAY, weekday=target)
            # Set initial date to next occurrence
            dt = _next_weekday(target, now)
            result.remind_at = self._to_utc(dt)
            result.time_found = True
        return result

    def _handle_every_n_months(self, m, result, now, tz):
        return self._set_repeat(result, RepeatType.EVERY_N_MONTHS, int(m.group(1)))

    def _handle_every_n_months_word(self, m, result, now, tz):
        val = _word_to_int(m.group(1))
        return self._set_repeat(result, RepeatType.EVERY_N_MONTHS, val) if val else result

    # ------------------------------------------------------------------
    # Stage 3b — Time extraction (ordered by priority)
    # ------------------------------------------------------------------

    def _extract_time(
        self, text: str, result: ParseResult, now: datetime, tz: str
    ) -> tuple[str, ParseResult]:
        rules = [
            # ── relative: minutes / hours ────────────────────────────────
            self._rule_relative_minutes_word,  # نیم ساعت / ربع ساعت
            self._rule_relative_minutes,       # ۲۰ دقیقه دیگه
            self._rule_relative_hours_word,    # دو ساعت دیگه (word)
            self._rule_relative_hours,         # ۲ ساعت دیگه
            self._rule_relative_days_word,     # دو روز دیگه (word)
            self._rule_relative_days,          # ۲ روز دیگه
            self._rule_relative_weeks_word,    # دو هفته دیگه (word)
            self._rule_relative_weeks,         # ۲ هفته دیگه
            self._rule_relative_months_word,   # یک ماه دیگه (word)
            self._rule_relative_months,        # ۲ ماه دیگه
            # ── absolute anchors ────────────────────────────────────────
            self._rule_next_week,
            self._rule_next_month,
            self._rule_next_year,
            self._rule_start_of_month,
            self._rule_end_of_month,
            self._rule_end_of_week,
            self._rule_psfarda,
            self._rule_farda,
            self._rule_emshab,
            self._rule_emrooz,
            self._rule_weekday_with_tod,       # شنبه صبح / جمعه شب
            self._rule_weekday,
            # ── Jalali explicit dates ────────────────────────────────────
            self._rule_jalali_full,            # ۱۴۰۳/۴/۱۵
            self._rule_jalali_day_month_digit, # ۱۵ تیر / تیر ۱۵
            self._rule_jalali_ordinal_month,   # پانزدهم مهر
            # ── clock time (always last) ─────────────────────────────────
            self._rule_explicit_time,
        ]

        for rule in rules:
            new_text, new_result, matched = rule(text, result, now, tz)
            if matched:
                text, result = new_text, new_result
                break

        # Stage 4 — Conflict Resolution:
        # After a day rule fires, a second explicit clock time may still be present.
        # Use strict=True so a bare TOD keyword (صبح/شب/...) cannot silently
        # override an already-precise explicit clock time.
        if result.time_found:
            new_text, new_result, matched = self._rule_explicit_time(
                text, result, now, tz, strict=True
            )
            if matched:
                text, result = new_text, new_result
            # After weekday/farda rules set a date, pick up a standalone digit hour
            # that _rule_explicit_time cannot see (e.g. "شنبه ۱۰", "چهارشنبه ۱۴")
            if not matched:
                text, result = self._rule_standalone_hour(text, result, now, tz)
            # Apply AM/PM adjustment for cases like "نه و نیم شب" where a precise
            # time was set but a bare period keyword still remains in the text.
            text, result = self._apply_ampm_adjust(text, result, tz)

        # Apply tod_hint from "هر صبح" / "هر شب"
        tod_hint = getattr(result, "_tod_hint", None)
        if tod_hint:
            tod_map = {
                "صبح": config.TIME_MORNING,
                "شب":  config.TIME_NIGHT,
            }
            hm = tod_map.get(tod_hint)
            if hm:
                if result.remind_at is None:
                    # هیچ زمانی تنظیم نشده — از زمان پیش‌فرض استفاده کن
                    dt = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
                    if dt <= now:
                        dt += timedelta(days=1)
                    result.remind_at = self._to_utc(dt)
                    result.time_found = True
                elif tod_hint == "شب":
                    # یک ساعت صریح پیدا شد — اگر < 13 بود به PM تبدیل کن
                    # (هرشب ساعت ۱۰ → ۲۲:۰۰)
                    local_dt = result.remind_at.astimezone(self._tz(tz))
                    if 1 <= local_dt.hour <= 12:
                        new_local = local_dt.replace(
                            hour=local_dt.hour + 12, second=0, microsecond=0
                        )
                        result.remind_at = self._to_utc(new_local)

        # Fallback: if repeat found but no date/time, use morning default
        if result.is_repeat and result.remind_at is None:
            h, mn = config.TIME_MORNING
            dt = now.replace(hour=h, minute=mn, second=0, microsecond=0)
            if dt <= now:
                dt += timedelta(days=1)
            result.remind_at = self._to_utc(dt)
            result.time_found = True

        return text, result

    # ------------------------------------------------------------------
    # Individual time rules
    # ------------------------------------------------------------------

    # ── relative minutes ─────────────────────────────────────────────────

    def _rule_relative_minutes(self, text, result, now, tz):
        """۲۰ دقیقه دیگه — یا فقط ۲۰ دقیقه (بدون دیگه)"""
        # با دیگه/بعد (اولویت بالاتر)
        m = re.search(r"(\d+)\s*دقیقه\s*(?:دیگه|دیگر|بعد|دیگ)", text)
        if m:
            dt = now + timedelta(minutes=int(m.group(1)))
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            return text, result, True
        # بدون دیگه ولی با عدد معقول (جلوگیری از تداخل با ساعت خاص)
        m = re.search(r"(?<![:\d])(\d+)\s*دقیقه(?!\s*(?:دیگه|دیگر|بعد))", text)
        if m:
            mins = int(m.group(1))
            if 1 <= mins <= 999:  # مقدار معقول
                dt = now + timedelta(minutes=mins)
                result.remind_at = self._to_utc(dt)
                result.time_found = True
                text = (text[:m.start()] + text[m.end():]).strip()
                return text, result, True
        return text, result, False

    def _rule_relative_minutes_word(self, text, result, now, tz):
        """نیم ساعت / ربع ساعت / یه ربع / چند دقیقه / دو و نیم ساعت دیگه"""
        # چند دقیقه دیگه → ۵ دقیقه
        m = re.search(r"چند\s*دقیقه(?:\s*(?:دیگه|دیگر|بعد|دیگ))?", text)
        if m:
            dt = now + timedelta(minutes=5)
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            return text, result, True

        # یه ربع / یه ربع دیگه / ربع ساعت (با یا بدون دیگه)
        m = re.search(r"(?:یه|یک|ی)\s*ربع(?:\s*(?:ساعت)?)?(?:\s*(?:دیگه|دیگر|بعد|دیگ))?", text)
        if m:
            dt = now + timedelta(minutes=15)
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            return text, result, True

        m = re.search(r"ربع\s*ساعت(?:\s*(?:دیگه|دیگر|بعد|دیگ))?", text)
        if m:
            dt = now + timedelta(minutes=15)
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            return text, result, True

        # نیم ساعت (با یا بدون دیگه)
        m = re.search(r"نیم\s*ساعت(?:\s*(?:دیگه|دیگر|بعد|دیگ))?", text)
        if m:
            dt = now + timedelta(minutes=30)
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            return text, result, True

        # دو و نیم ساعت / X و نیم ساعت دیگه
        m = re.search(rf"({_WORD_NUM_PATTERN})\s*و\s*نیم\s*ساعت(?:\s*(?:دیگه|دیگر|بعد|دیگ))?", text)
        if m:
            val = _word_to_int(m.group(1))
            if val:
                dt = now + timedelta(minutes=val * 60 + 30)
                result.remind_at = self._to_utc(dt)
                result.time_found = True
                text = (text[:m.start()] + text[m.end():]).strip()
                return text, result, True

        # WORD دقیقه (با یا بدون دیگه)
        m = re.search(rf"({_WORD_NUM_PATTERN})\s*دقیقه(?:\s*(?:دیگه|دیگر|بعد|دیگ))?", text)
        if m:
            val = _word_to_int(m.group(1))
            if val:
                dt = now + timedelta(minutes=val)
                result.remind_at = self._to_utc(dt)
                result.time_found = True
                text = (text[:m.start()] + text[m.end():]).strip()
                return text, result, True

        return text, result, False

    # ── relative hours ────────────────────────────────────────────────────

    def _rule_relative_hours(self, text, result, now, tz):
        """۲ ساعت دیگه — یا فقط ۲ ساعت (بدون دیگه، با lookbehind)"""
        # با دیگه/بعد
        m = re.search(r"(\d+)\s*ساعت\s*(?:دیگه|دیگر|بعد|دیگ)", text)
        if m:
            dt = now + timedelta(hours=int(m.group(1)))
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            return text, result, True
        # بدون دیگه، فقط وقتی "هر" قبلش نباشد
        m = re.search(r"(?<!هر\s)(?<!هر)(\d+)\s*ساعت(?!\s*(?:دیگه|دیگر|بعد))", text)
        if m and not re.search(r"هر\s*" + re.escape(m.group(0)), text):
            n = int(m.group(1))
            if 1 <= n <= 48:
                dt = now + timedelta(hours=n)
                result.remind_at = self._to_utc(dt)
                result.time_found = True
                text = (text[:m.start()] + text[m.end():]).strip()
                return text, result, True
        return text, result, False

    def _rule_relative_hours_word(self, text, result, now, tz):
        """دو ساعت دیگه / سه ساعت بعد / یه ساعت (بدون دیگه)"""
        # با دیگه/بعد
        pat = rf"({_WORD_NUM_PATTERN})\s*ساعت\s*(?:دیگه|دیگر|بعد|دیگ)"
        m = re.search(pat, text)
        if m:
            val = _word_to_int(m.group(1))
            if val:
                dt = now + timedelta(hours=val)
                result.remind_at = self._to_utc(dt)
                result.time_found = True
                text = (text[:m.start()] + text[m.end():]).strip()
                return text, result, True
        # بدون دیگه (یه ساعت / دو ساعت / سه ساعت) — فقط وقتی "هر" قبلش نباشد
        pat2 = rf"(?<!هر\s)(?<!هر)({_WORD_NUM_PATTERN})\s*ساعت(?!\s*(?:دیگه|دیگر|بعد))"
        m = re.search(pat2, text)
        if m:
            # اطمینان از اینکه "هر" مستقیماً قبل از این match نباشد
            start = m.start()
            prefix = text[:start]
            if not re.search(r"هر\s*$", prefix):
                val = _word_to_int(m.group(1))
                if val and 1 <= val <= 48:
                    dt = now + timedelta(hours=val)
                    result.remind_at = self._to_utc(dt)
                    result.time_found = True
                    text = (text[:m.start()] + text[m.end():]).strip()
                    return text, result, True
        return text, result, False

    # ── relative days ─────────────────────────────────────────────────────

    def _rule_relative_days(self, text, result, now, tz):
        """۳ روز دیگه"""
        m = re.search(r"(\d+)\s*روز\s*(?:دیگه|دیگر|بعد|دیگ)", text)
        if m:
            days = int(m.group(1))
            dt = (now + timedelta(days=days)).replace(
                hour=config.TIME_MORNING[0], minute=config.TIME_MORNING[1],
                second=0, microsecond=0
            )
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            text, result = self._apply_time_of_day(text, result, dt, tz)
            return text, result, True
        return text, result, False

    def _rule_relative_days_word(self, text, result, now, tz):
        """دو روز دیگه / سه روز بعد"""
        pat = rf"({_WORD_NUM_PATTERN})\s*روز\s*(?:دیگه|دیگر|بعد|دیگ)"
        m = re.search(pat, text)
        if m:
            val = _word_to_int(m.group(1))
            if val:
                dt = (now + timedelta(days=val)).replace(
                    hour=config.TIME_MORNING[0], minute=config.TIME_MORNING[1],
                    second=0, microsecond=0
                )
                result.remind_at = self._to_utc(dt)
                result.time_found = True
                text = (text[:m.start()] + text[m.end():]).strip()
                text, result = self._apply_time_of_day(text, result, dt, tz)
                return text, result, True
        return text, result, False

    # ── relative weeks ────────────────────────────────────────────────────

    def _rule_relative_weeks(self, text, result, now, tz):
        """۲ هفته دیگه"""
        m = re.search(r"(\d+)\s*هفته\s*(?:دیگه|دیگر|بعد|دیگ)", text)
        if m:
            dt = (now + timedelta(weeks=int(m.group(1)))).replace(
                hour=config.TIME_MORNING[0], minute=config.TIME_MORNING[1],
                second=0, microsecond=0
            )
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            text, result = self._apply_time_of_day(text, result, dt, tz)
            return text, result, True
        return text, result, False

    def _rule_relative_weeks_word(self, text, result, now, tz):
        """دو هفته دیگه / سه هفته بعد"""
        pat = rf"({_WORD_NUM_PATTERN})\s*هفته\s*(?:دیگه|دیگر|بعد|دیگ)"
        m = re.search(pat, text)
        if m:
            val = _word_to_int(m.group(1))
            if val:
                dt = (now + timedelta(weeks=val)).replace(
                    hour=config.TIME_MORNING[0], minute=config.TIME_MORNING[1],
                    second=0, microsecond=0
                )
                result.remind_at = self._to_utc(dt)
                result.time_found = True
                text = (text[:m.start()] + text[m.end():]).strip()
                text, result = self._apply_time_of_day(text, result, dt, tz)
                return text, result, True
        return text, result, False

    # ── relative months ───────────────────────────────────────────────────

    def _rule_relative_months(self, text, result, now, tz):
        """۲ ماه دیگه"""
        m = re.search(r"(\d+)\s*ماه\s*(?:دیگه|دیگر|بعد|دیگ)", text)
        if m:
            dt = (now + timedelta(days=30 * int(m.group(1)))).replace(
                hour=config.TIME_MORNING[0], minute=config.TIME_MORNING[1],
                second=0, microsecond=0
            )
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            text, result = self._apply_time_of_day(text, result, dt, tz)
            return text, result, True
        return text, result, False

    def _rule_relative_months_word(self, text, result, now, tz):
        """یک ماه دیگه / دو ماه بعد"""
        pat = rf"({_WORD_NUM_PATTERN})\s*ماه\s*(?:دیگه|دیگر|بعد|دیگ)"
        m = re.search(pat, text)
        if m:
            val = _word_to_int(m.group(1))
            if val:
                dt = (now + timedelta(days=30 * val)).replace(
                    hour=config.TIME_MORNING[0], minute=config.TIME_MORNING[1],
                    second=0, microsecond=0
                )
                result.remind_at = self._to_utc(dt)
                result.time_found = True
                text = (text[:m.start()] + text[m.end():]).strip()
                text, result = self._apply_time_of_day(text, result, dt, tz)
                return text, result, True
        return text, result, False

    # ── calendar anchors ──────────────────────────────────────────────────

    def _rule_next_week(self, text, result, now, tz):
        m = re.search(r"هفته\s*(?:آینده|بعد|دیگه|دیگر)", text)
        if m:
            dt = (now + timedelta(weeks=1)).replace(
                hour=config.TIME_MORNING[0], minute=config.TIME_MORNING[1],
                second=0, microsecond=0
            )
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            text, result = self._apply_time_of_day(text, result, dt, tz)
            return text, result, True
        return text, result, False

    def _rule_next_month(self, text, result, now, tz):
        m = re.search(r"ماه\s*(?:آینده|بعد|دیگه|دیگر)", text)
        if m:
            dt = (now + timedelta(days=30)).replace(
                hour=config.TIME_MORNING[0], minute=config.TIME_MORNING[1],
                second=0, microsecond=0
            )
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            text, result = self._apply_time_of_day(text, result, dt, tz)
            return text, result, True
        return text, result, False

    def _rule_next_year(self, text, result, now, tz):
        m = re.search(r"سال\s*(?:آینده|بعد|دیگه|دیگر)", text)
        if m:
            dt = now.replace(year=now.year + 1, hour=config.TIME_MORNING[0],
                             minute=config.TIME_MORNING[1], second=0, microsecond=0)
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            text, result = self._apply_time_of_day(text, result, dt, tz)
            return text, result, True
        return text, result, False

    def _rule_start_of_month(self, text, result, now, tz):
        m = re.search(r"اول\s*ماه|ابتدای\s*ماه", text)
        if m:
            if now.month == 12:
                next_month = now.replace(year=now.year + 1, month=1, day=1,
                                         hour=config.TIME_MORNING[0], minute=0, second=0, microsecond=0)
            else:
                next_month = now.replace(month=now.month + 1, day=1,
                                         hour=config.TIME_MORNING[0], minute=0, second=0, microsecond=0)
            result.remind_at = self._to_utc(next_month)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            text, result = self._apply_time_of_day(text, result, next_month, tz)
            return text, result, True
        return text, result, False

    def _rule_end_of_month(self, text, result, now, tz):
        m = re.search(r"آخر\s*ماه|انتهای\s*ماه", text)
        if m:
            import calendar
            last_day = calendar.monthrange(now.year, now.month)[1]
            dt = now.replace(day=last_day, hour=config.TIME_MORNING[0], minute=0,
                             second=0, microsecond=0)
            if dt < now:
                if now.month == 12:
                    dt = dt.replace(year=now.year + 1, month=1)
                else:
                    dt = dt.replace(month=now.month + 1)
                last_day = calendar.monthrange(dt.year, dt.month)[1]
                dt = dt.replace(day=last_day)
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            text, result = self._apply_time_of_day(text, result, dt, tz)
            return text, result, True
        return text, result, False

    def _rule_end_of_week(self, text, result, now, tz):
        """آخر هفته → next جمعه (Friday, weekday=4)."""
        m = re.search(r"آخر\s*هفته|آخرِ\s*هفته", text)
        if m:
            dt = _next_weekday(4, now)
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            text, result = self._apply_time_of_day(text, result, dt, tz)
            return text, result, True
        return text, result, False

    def _rule_psfarda(self, text, result, now, tz):
        m = re.search(r"پس\s*فردا|پس‌فردا", text)
        if m:
            dt = (now + timedelta(days=2)).replace(
                hour=config.TIME_MORNING[0], minute=config.TIME_MORNING[1],
                second=0, microsecond=0
            )
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            text, result = self._apply_time_of_day(text, result, dt, tz)
            return text, result, True
        return text, result, False

    def _rule_farda(self, text, result, now, tz):
        m = re.search(r"فردا", text)
        if m:
            dt = (now + timedelta(days=1)).replace(
                hour=config.TIME_MORNING[0], minute=config.TIME_MORNING[1],
                second=0, microsecond=0
            )
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            # ساعت قبل از apply_time_of_day را برای مقایسه ذخیره می‌کنیم
            hour_before_tod = dt.astimezone(self._tz(tz)).hour
            text, result = self._apply_time_of_day(text, result, dt, tz)
            # اگر بعد از حذف فردا یک عدد ساده باقی مانده (فردا ۸ / فردا ۸ شب)
            # آن را به عنوان ساعت، با توجه به context AM/PM فعلی، اعمال کن
            m_digit = re.search(r"(?<![:\d])(\d{1,2})(?![:\d])", text)
            if m_digit:
                h = int(m_digit.group(1))
                if 0 <= h <= 23:
                    local_dt = result.remind_at.astimezone(self._tz(tz))
                    # آیا _apply_time_of_day یک TOD شبانه تنظیم کرد؟
                    is_pm_context = local_dt.hour >= 12
                    if is_pm_context and 1 <= h <= 12:
                        new_hour = h + 12  # «فردا ۸ شب» → ۲۰:۰۰
                    else:
                        new_hour = h       # «فردا ۸ صبح» / «فردا ۸» / «فردا ۲۲» → as-is
                    if new_hour <= 23:
                        new_local = local_dt.replace(hour=new_hour, minute=0, second=0, microsecond=0)
                        result.remind_at = self._to_utc(new_local)
                        text = (text[:m_digit.start()] + text[m_digit.end():]).strip()
            return text, result, True
        return text, result, False

    def _rule_emshab(self, text, result, now, tz):
        """
        امشب — tonight at TIME_NIGHT, OR امشب H → tonight at hour H.
        Supports: امشب ۱۰  امشب ۲۲  امشب ۱۰:۳۰
        """
        m = re.search(r"امشب", text)
        if m:
            # First set base to tonight at TIME_NIGHT
            h_base, mn_base = config.TIME_NIGHT
            dt = now.replace(hour=h_base, minute=mn_base, second=0, microsecond=0)
            if dt < now:
                dt += timedelta(days=1)
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()

            # Try to find explicit clock after removing "امشب"
            # HH:MM pattern
            m2 = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
            if m2:
                hour, minute = int(m2.group(1)), int(m2.group(2))
                local = dt.astimezone(self._tz(tz)).replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
                result.remind_at = self._to_utc(local)
                text = (text[:m2.start()] + text[m2.end():]).strip()
                return text, result, True

            # Standalone digit hour (e.g., امشب ۱۰ یا امشب ۲۲)
            m3 = re.search(r"(?<![:\d])(\d{1,2})(?![:\d])", text)
            if m3:
                hour = int(m3.group(1))
                if 0 <= hour <= 23:
                    # در context امشب، اگر hour ≤ 12 باشد، PM فرض می‌شود
                    # مگر اینکه به وضوح ساعت بزرگ (≥ 13) باشد
                    if 1 <= hour <= 12:
                        hour += 12  # امشب ۱۰ → ۲۲:۰۰ (۱۰ شب)
                    if hour > 23:
                        hour = 23
                    local = dt.astimezone(self._tz(tz)).replace(
                        hour=hour, minute=0, second=0, microsecond=0
                    )
                    result.remind_at = self._to_utc(local)
                    text = (text[:m3.start()] + text[m3.end():]).strip()
                    return text, result, True

            return text, result, True
        return text, result, False

    def _rule_emrooz(self, text, result, now, tz):
        m = re.search(r"امروز", text)
        if m:
            dt = now.replace(hour=config.TIME_MORNING[0], minute=config.TIME_MORNING[1],
                             second=0, microsecond=0)
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            text, result = self._apply_time_of_day(text, result, dt, tz)
            return text, result, True
        return text, result, False

    def _rule_weekday_with_tod(self, text, result, now, tz):
        """شنبه صبح / جمعه شب / دوشنبه عصر — weekday + time-of-day together."""
        tod_map = {
            "اول صبح":  (7, 0),
            "صبح زود":  (7, 0),
            "بامداد":   (4, 0),
            "صبح":      config.TIME_MORNING,
            "ظهر":      config.TIME_NOON,
            "بعدازظهر": config.TIME_AFTERNOON,
            "عصر":      config.TIME_EVENING,
            "غروب":     (18, 0),
            "شب":       config.TIME_NIGHT,
            "امشب":     config.TIME_NIGHT,
            "نیمه شب":  (0, 0),
            "نصف شب":   (0, 0),
        }
        tod_keys = "|".join(re.escape(k) for k in sorted(tod_map, key=len, reverse=True))
        pat = rf"({_WEEKDAY_PATTERN})\s*({tod_keys})"
        m = re.search(pat, text)
        if not m:
            pat2 = rf"({tod_keys})\s*({_WEEKDAY_PATTERN})"
            m2 = re.search(pat2, text)
            if m2:
                tod_key = m2.group(1)
                day_name = m2.group(2)
                target = _WEEKDAYS.get(day_name)
                if target is not None:
                    h, mn = tod_map[tod_key]
                    days_ahead = (target - now.weekday()) % 7 or 7
                    dt = (now + timedelta(days=days_ahead)).replace(
                        hour=h, minute=mn, second=0, microsecond=0
                    )
                    result.remind_at = self._to_utc(dt)
                    result.time_found = True
                    text = (text[:m2.start()] + text[m2.end():]).strip()
                    return text, result, True
            return text, result, False

        day_name = m.group(1)
        tod_key = m.group(2)
        target = _WEEKDAYS.get(day_name)
        if target is None:
            return text, result, False

        h, mn = tod_map[tod_key]
        days_ahead = (target - now.weekday()) % 7 or 7
        dt = (now + timedelta(days=days_ahead)).replace(
            hour=h, minute=mn, second=0, microsecond=0
        )
        result.remind_at = self._to_utc(dt)
        result.time_found = True
        text = (text[:m.start()] + text[m.end():]).strip()
        return text, result, True

    def _rule_weekday(self, text, result, now, tz):
        """Plain weekday name without time-of-day."""
        m = re.search(rf"({_WEEKDAY_PATTERN})", text)
        if m:
            day_name = m.group(1)
            target = _WEEKDAYS.get(day_name)
            if target is None:
                return text, result, False
            days_ahead = (target - now.weekday()) % 7 or 7
            dt = (now + timedelta(days=days_ahead)).replace(
                hour=config.TIME_MORNING[0], minute=config.TIME_MORNING[1],
                second=0, microsecond=0
            )
            result.remind_at = self._to_utc(dt)
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            text, result = self._apply_time_of_day(text, result, dt, tz)
            return text, result, True
        return text, result, False

    # ── Jalali explicit dates ─────────────────────────────────────────────

    def _rule_jalali_full(self, text, result, now, tz):
        """۱۴۰۳/۴/۱۵ or ۱۴۰۳-۴-۱۵ or ۱۴۰۳.۴.۱۵"""
        m = re.search(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", text)
        if m:
            jy, jmo, jd = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                dt = _jalali_to_gregorian(jy, jmo, jd, self._tz(tz))
                if dt <= self._to_utc(now):
                    return text, result, False
                result.remind_at = dt
                result.time_found = True
                text = (text[:m.start()] + text[m.end():]).strip()
                local_dt = dt.astimezone(self._tz(tz))
                text, result = self._apply_time_of_day(text, result, local_dt, tz)
                return text, result, True
            except Exception:
                pass
        return text, result, False

    def _rule_jalali_day_month_digit(self, text, result, now, tz):
        """۱۵ تیر  or  تیر ۱۵  (optionally followed by year)."""
        month_pat = _MONTH_PATTERN
        m = re.search(rf"(\d{{1,2}})\s*({month_pat})(?:\s*(\d{{4}}))?", text)
        if not m:
            m = re.search(rf"({month_pat})\s*(\d{{1,2}})(?:\s*(\d{{4}}))?", text)
            if m:
                jmonth_name = m.group(1)
                jday = int(m.group(2))
                jyear_str = m.group(3)
                jmonth = _JALALI_MONTHS[jmonth_name]
            else:
                return text, result, False
        else:
            jday = int(m.group(1))
            jmonth_name = m.group(2)
            jmonth = _JALALI_MONTHS[jmonth_name]
            jyear_str = m.group(3)

        now_j = _current_jalali(now)
        if jyear_str:
            jyear = int(jyear_str)
        else:
            jyear = now_j.year
            if jmonth < now_j.month or (jmonth == now_j.month and jday < now_j.day):
                jyear += 1

        try:
            dt = _jalali_to_gregorian(jyear, jmonth, jday, self._tz(tz))
            result.remind_at = dt
            result.time_found = True
            text = (text[:m.start()] + text[m.end():]).strip()
            local_dt = dt.astimezone(self._tz(tz))
            text, result = self._apply_time_of_day(text, result, local_dt, tz)
            return text, result, True
        except Exception:
            pass
        return text, result, False

    def _rule_jalali_ordinal_month(self, text, result, now, tz):
        """پانزدهم مهر / اول تیر / سوم اردیبهشت"""
        ord_pat = _ORDINAL_PATTERN
        month_pat = _MONTH_PATTERN
        m = re.search(rf"({ord_pat})\s*({month_pat})(?:\s*(\d{{4}}))?", text)
        if m:
            ord_word = m.group(1)
            jmonth_name = m.group(2)
            jyear_str = m.group(3)
            jday = _ORDINALS.get(ord_word)
            jmonth = _JALALI_MONTHS.get(jmonth_name)
            if jday and jmonth:
                now_j = _current_jalali(now)
                jyear = int(jyear_str) if jyear_str else now_j.year
                if not jyear_str:
                    if jmonth < now_j.month or (jmonth == now_j.month and jday < now_j.day):
                        jyear += 1
                try:
                    dt = _jalali_to_gregorian(jyear, jmonth, jday, self._tz(tz))
                    result.remind_at = dt
                    result.time_found = True
                    text = (text[:m.start()] + text[m.end():]).strip()
                    local_dt = dt.astimezone(self._tz(tz))
                    text, result = self._apply_time_of_day(text, result, local_dt, tz)
                    return text, result, True
                except Exception:
                    pass
        return text, result, False

    # ── explicit clock time ───────────────────────────────────────────────

    def _rule_standalone_hour(self, text, result, now, tz):
        """
        Stage 4 only: pick up a bare digit (1-23) as an explicit hour when
        the day has already been anchored by a weekday/farda/etc. rule AND the
        time is still at the morning default (meaning no TOD keyword has adjusted
        it yet).  E.g. "شنبه ۱۰ جلسه" or "چهارشنبه ۱۴ جلسه با تیم".
        """
        if result.remind_at is None:
            return text, result
        # Only fire when the time is still at the morning default.
        # If a TOD keyword (عصر, شب, ظهر…) already adjusted the hour we must not
        # override it with a stray digit from the body text.
        local = result.remind_at.astimezone(self._tz(tz))
        morning_h, morning_mn = config.TIME_MORNING
        if local.hour != morning_h or local.minute != morning_mn:
            return text, result
        m = re.search(r"(?<![:\d])(\d{1,2})(?![:\d])", text)
        if m:
            h = int(m.group(1))
            if 0 <= h <= 23:
                new_local = local.replace(hour=h, minute=0, second=0, microsecond=0)
                result.remind_at = self._to_utc(new_local)
                text = (text[:m.start()] + text[m.end():]).strip()
        return text, result

    def _apply_ampm_adjust(self, text, result, tz):
        """
        Stage 4 only: if remaining text contains a bare AM/PM keyword (صبح/شب/…)
        and the already-set time has hour 1-12, adjust the hour to AM or PM.
        This handles cases like "نه و نیم شب" where the TOD follows a precise time.
        Unlike the full explicit-time rule this PRESERVES the existing minutes.
        """
        if result.remind_at is None:
            return text, result
        local = result.remind_at.astimezone(self._tz(tz))
        # Only adjust when hour is ambiguous (1-12)
        if not (1 <= local.hour <= 12):
            return text, result

        pm_keywords = {"شب", "بامداد", "بعدازظهر", "عصر", "غروب"}
        am_keywords = {"صبح"}
        noon_keywords = {"ظهر"}

        for kw in sorted(pm_keywords | am_keywords | noon_keywords, key=len, reverse=True):
            m = re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", text)
            if m:
                h = local.hour
                mn = local.minute
                if kw in pm_keywords:
                    if kw == "بامداد":
                        new_h = h  # borrow as early morning (1-6 range)
                    else:
                        new_h = h + 12 if h < 12 else h
                elif kw in noon_keywords:
                    new_h = 12
                else:  # صبح
                    new_h = h  # keep AM
                if new_h <= 23:
                    new_local = local.replace(hour=new_h, minute=mn, second=0, microsecond=0)
                    result.remind_at = self._to_utc(new_local)
                text = (text[:m.start()] + text[m.end():]).strip()
                break
        return text, result

    def _rule_explicit_time(self, text, result, now, tz, strict: bool = False):
        """
        Parse all clock-time patterns. Priority order:
          1. نیمه شب / نصف شب → midnight
          2. اول صبح / صبح زود → 07:00
          3. ساعت H و نیم → H:30
          4. ساعت WORD → word-number hour (ساعت هفت, ساعت ده)
          5. ساعت H:MM or ساعت H
          6. H:MM (without ساعت keyword)
          7. WORD + period (ده شب, هشت صبح) — word-number + am/pm keyword
          8. H + period (۸ صبح, ۹ شب) — digit + am/pm keyword
          9. Standalone period-of-day (صبح, عصر, غروب, بامداد …)
             [skipped when strict=True to avoid overriding an already-set clock]
        """
        # 1. نیمه شب / نصف شب → midnight
        m = re.search(r"نیمه\s*شب|نصف\s*شب|نیمه‌شب", text)
        if m:
            text, result = self._apply_clock_time(0, 0, text, m, result, now, tz)
            return text.strip(), result, True

        # 2. اول صبح / صبح زود → 07:00
        m = re.search(r"اول\s*صبح|صبح\s*زود", text)
        if m:
            text, result = self._apply_clock_time(7, 0, text, m, result, now, tz)
            return text.strip(), result, True

        # 3. ساعت H و نیم → H:30  یا  ساعت H و ربع → H:15
        m = re.search(r"ساعت\s*(\d{1,2})\s*و\s*نیم", text)
        if m:
            hour = int(m.group(1))
            text, result = self._apply_clock_time(hour, 30, text, m, result, now, tz)
            return text.strip(), result, True
        m = re.search(r"ساعت\s*(\d{1,2})\s*و\s*ربع", text)
        if m:
            hour = int(m.group(1))
            text, result = self._apply_clock_time(hour, 15, text, m, result, now, tz)
            return text.strip(), result, True

        # 3b. WORD و نیم / WORD و ربع (بدون ساعت) — مثل «هفت و نیم»، «هشت و ربع»
        m = re.search(rf"({_WORD_NUM_PATTERN})\s*و\s*نیم", text)
        if m:
            val = _word_to_int(m.group(1))
            if val is not None and 0 <= val <= 23:
                text, result = self._apply_clock_time(val, 30, text, m, result, now, tz)
                return text.strip(), result, True
        m = re.search(rf"({_WORD_NUM_PATTERN})\s*و\s*ربع", text)
        if m:
            val = _word_to_int(m.group(1))
            if val is not None and 0 <= val <= 23:
                text, result = self._apply_clock_time(val, 15, text, m, result, now, tz)
                return text.strip(), result, True

        # 3c. H و نیم / H و ربع (بدون ساعت) — مثل «7 و نیم»، «8 و ربع»
        m = re.search(r"(\d{1,2})\s*و\s*نیم", text)
        if m:
            hour = int(m.group(1))
            if 0 <= hour <= 23:
                text, result = self._apply_clock_time(hour, 30, text, m, result, now, tz)
                return text.strip(), result, True
        m = re.search(r"(\d{1,2})\s*و\s*ربع", text)
        if m:
            hour = int(m.group(1))
            if 0 <= hour <= 23:
                text, result = self._apply_clock_time(hour, 15, text, m, result, now, tz)
                return text.strip(), result, True

        # 4. ساعت + word number (ساعت هفت, ساعت ده, ساعت یازده)
        wn_pat = rf"ساعت\s*({_WORD_NUM_PATTERN})"
        m = re.search(wn_pat, text)
        if m:
            val = _word_to_int(m.group(1))
            if val is not None and 0 <= val <= 23:
                text, result = self._apply_clock_time(val, 0, text, m, result, now, tz)
                return text.strip(), result, True

        # 5. ساعت H:MM or ساعت H
        m = re.search(r"ساعت\s*(\d{1,2})(?::(\d{2}))?", text)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2)) if m.group(2) else 0
            text, result = self._apply_clock_time(hour, minute, text, m, result, now, tz)
            return text.strip(), result, True

        # 6. H:MM (without ساعت keyword)
        m = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2))
            text, result = self._apply_clock_time(hour, minute, text, m, result, now, tz)
            return text.strip(), result, True

        # 7. Word number + period keyword (ده شب, هشت صبح, ده بعدازظهر)
        ampm_map = {
            "صبح":       ("am", 12),
            "ظهر":       ("noon", 13),
            "بعدازظهر":  ("pm", 20),
            "عصر":       ("pm_ev", 20),
            "غروب":      ("pm_ev", 20),
            "شب":        ("pm_night", 24),
            "بامداد":    ("am_early", 6),
        }
        for keyword, (mode, boundary) in ampm_map.items():
            wn_m = re.search(rf"({_WORD_NUM_PATTERN})\s*{re.escape(keyword)}", text)
            if wn_m:
                val = _word_to_int(wn_m.group(1))
                if val is not None:
                    hour = val
                    if mode == "am" and hour == 12:
                        hour = 0
                    elif mode in ("pm", "pm_ev") and hour < boundary and hour < 12:
                        hour += 12
                    elif mode == "pm_night" and hour < 12:
                        hour += 12
                    elif mode == "noon":
                        hour = 12
                    elif mode == "am_early":
                        pass  # borrow as-is (4 AM range)
                    text, result = self._apply_clock_time(hour, 0, text, wn_m, result, now, tz)
                    return text.strip(), result, True

        # 8. Digit + period keyword (۸ صبح, ۹ شب, ۸ بعدازظهر)
        for keyword, (mode, boundary) in ampm_map.items():
            m = re.search(rf"(\d{{1,2}})\s*{re.escape(keyword)}", text)
            if m:
                hour = int(m.group(1))
                minute = 0
                if mode == "am" and hour == 12:
                    hour = 0
                elif mode in ("pm", "pm_ev") and hour < boundary and hour < 12:
                    hour += 12
                elif mode == "pm_night" and hour < 12:
                    hour += 12
                elif mode == "noon" and hour != 12:
                    hour = 12
                elif mode == "am_early":
                    pass
                text, result = self._apply_clock_time(hour, minute, text, m, result, now, tz)
                return text.strip(), result, True

        # 9. Standalone period-of-day (no number)
        # In strict mode (stage 4), skip this so a bare TOD keyword cannot
        # silently override an already-precise explicit clock time.
        if not strict:
            tod_standalone = {
                "بامداد":   (4, 0),
                "اول صبح":  (7, 0),
                "صبح زود":  (7, 0),
                "صبح":      config.TIME_MORNING,
                "ظهر":      config.TIME_NOON,
                "بعدازظهر": config.TIME_AFTERNOON,
                "عصر":      config.TIME_EVENING,
                "غروب":     (18, 0),
                "شب":       config.TIME_NIGHT,
                "نیمه شب":  (0, 0),
                "نصف شب":   (0, 0),
            }
            for keyword, (h, mn) in tod_standalone.items():
                m = re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text)
                if m:
                    text2 = (text[:m.start()] + text[m.end():]).strip()
                    text2, result2 = self._apply_clock_time(h, mn, text2, None, result, now, tz)
                    return text2.strip(), result2, True

        return text, result, False

    # ------------------------------------------------------------------
    # Stage 4 — Conflict Resolution helper: apply clock time
    # ------------------------------------------------------------------

    def _apply_clock_time(
        self, hour: int, minute: int, text: str, m, result: ParseResult, now: datetime, tz: str
    ) -> tuple[str, ParseResult]:
        """
        Overlay (hour, minute) onto result.remind_at if already set,
        or compute a fresh datetime (today or tomorrow if past).
        Removes the matched span from text if m is provided.
        """
        if m is not None:
            removed = (text[:m.start()] + text[m.end():]).strip()
        else:
            removed = text

        if result.remind_at is not None:
            local = result.remind_at.astimezone(self._tz(tz))
            new_local = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            result.remind_at = self._to_utc(new_local)
        else:
            dt_local = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if dt_local <= now:
                dt_local += timedelta(days=1)
            result.remind_at = self._to_utc(dt_local)

        result.time_found = True
        return removed, result

    # ------------------------------------------------------------------
    # Time-of-day keyword helper (used after day rules)
    # ------------------------------------------------------------------

    def _apply_time_of_day(self, text, result, base_dt, tz):
        """
        Check for time-of-day keywords in remaining text and update
        the time portion of result.remind_at accordingly.
        """
        tod_map = {
            "بامداد":   (4, 0),
            "اول صبح":  (7, 0),
            "صبح زود":  (7, 0),
            "صبح":      config.TIME_MORNING,
            "ظهر":      config.TIME_NOON,
            "بعدازظهر": config.TIME_AFTERNOON,
            "عصر":      config.TIME_EVENING,
            "غروب":     (18, 0),
            "شب":       config.TIME_NIGHT,
            "امشب":     config.TIME_NIGHT,
            "نیمه شب":  (0, 0),
            "نصف شب":   (0, 0),
        }
        for keyword, (h, mn) in tod_map.items():
            m = re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text)
            if m:
                local = base_dt.replace(hour=h, minute=mn, second=0, microsecond=0)
                result.remind_at = self._to_utc(local)
                text = (text[:m.start()] + text[m.end():]).strip()
                text = re.sub(r"\s+", " ", text).strip()
                break
        return text, result

    # ------------------------------------------------------------------
    # Stage 5 — Body cleanup
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_body(text: str) -> str:
        """Strip leftover connector words and return clean reminder body."""
        text = re.sub(r"^\s*ماه\s*", "", text).strip()
        text = re.sub(r"\s*ماه\s*$", "", text).strip()

        stopwords = [
            r"^یادم\s*بنداز\s*",
            r"^یادم\s*بینداز\s*",
            r"^یادم\s*بده\s*",
            r"^یادآوری\s*کن\s*",
            r"^برام\s*یادآوری\s*کن\s*",
            r"^یادآور(?:م|ی)?\s*کن\s*",
            r"^ثبت\s*کن\s*",
            r"^باید\s*",
            r"^که\s*",
            r"^تا\s*",
            r"^برو\s*",
            r"^بپرداز(?:م|یم)?\s*",
            r"^می\s*خوام\s*",
            r"^می‌خوام\s*",
            r"^لطفا\s*",
            r"^لطفاً\s*",
        ]
        for pat in stopwords:
            text = re.sub(pat, "", text, flags=re.IGNORECASE).strip()

        text = re.sub(r"^[،,:\-–]\s*", "", text).strip()
        text = re.sub(r"\s*[،,:\-–]$", "", text).strip()

        return text


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

parser = PersianTimeParser()


def parse_message(text: str, tz: str = "Asia/Tehran") -> ParseResult:
    """Convenience function — parse a user message and return ParseResult."""
    return parser.parse(text, tz)


# ---------------------------------------------------------------------------
# Multi-reminder parsing
# ---------------------------------------------------------------------------

# Keywords that indicate a date anchor is present on a line
_DATE_KEYWORDS = (
    "فردا", "امروز", "پس‌فردا", "پس فردا",
    "شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "سه شنبه",
    "چهارشنبه", "پنجشنبه", "جمعه",
    "هفته", "ماه", "سال",
    "دیروز", "پریروز",
    "ساعت", "دقیقه",
)

_TIME_OF_DAY_WORDS = (
    "صبح", "ظهر", "عصر", "شب", "بامداد", "امشب", "امروز",
    "بعدازظهر", "غروب", "نیمه شب", "نصف شب",
)


def _has_date_keyword(line: str) -> bool:
    """Return True if *line* contains any word/phrase that anchors a date or time."""
    line_lower = line.strip()
    for kw in _DATE_KEYWORDS:
        if kw in line_lower:
            return True
    for kw in _TIME_OF_DAY_WORDS:
        if kw in line_lower:
            return True
    # Numeric time: digits followed by colon (e.g. "۱۲:۳۰" or "12:30")
    if re.search(r"[\d۰-۹]{1,2}[:：][\d۰-۹]{2}", line):
        return True
    # Plain digit that could be an hour (standalone 1-2 digit number before whitespace/end)
    if re.search(r"(?<!\w)[\d۰-۹]{1,2}(?!\w)", line):
        return True
    return False


def _extract_date_anchor(line: str) -> str | None:
    """
    Extract just the date/time portion from a line to use as an anchor
    for the next lines that have no date keyword.

    Returns a string (the date anchor phrase) or None if none found.
    """
    # Try to pick up multi-word date phrases first
    patterns = [
        r"پس‌فردا|پس فردا",
        r"فردا",
        r"امروز",
        r"یکشنبه|دوشنبه|سه‌شنبه|سه شنبه|چهارشنبه|پنجشنبه|جمعه|شنبه",
        r"این هفته|هفته دیگه|هفته‌ی دیگه|هفته ی دیگه|هفته آینده",
        r"ماه دیگه|ماه آینده",
        r"[\d۰-۹]{1,2}[:：][\d۰-۹]{2}",
    ]
    for pat in patterns:
        m = re.search(pat, line)
        if m:
            return m.group(0)

    # Time of day words
    for kw in _TIME_OF_DAY_WORDS:
        if kw in line:
            return kw

    return None


def parse_multi(raw: str, tz: str = "Asia/Tehran") -> list[ParseResult]:
    """
    Parse multiple reminders from a single multi-line message.

    Strategy
    --------
    • Split on newlines.
    • Track the *date anchor* from the last line that contained a date keyword.
    • For each line that has no date keyword, prepend the last anchor so the
      parser can resolve the time correctly.
    • Partial failures (lines that parse to incomplete results) are included as-is
      so the caller can skip them or handle them.
    • Returns a list of ParseResult objects, one per meaningful line.

    Example::

        فردا ساعت ۸ باشگاه      → anchor="فردا"
        ساعت ۱۲ جلسه            → prepend "فردا", parse "فردا ساعت ۱۲ جلسه"
        شنبه ساعت ۳ خرید        → anchor="شنبه"

    Another example::

        شنبه:                   → anchor only, no reminder body → skip
        ۹ صبح دکتر              → "شنبه ۹ صبح دکتر"
        ۱۲ بانک                 → "شنبه ۱۲ بانک"
    """
    results: list[ParseResult] = []
    last_anchor: str | None = None

    lines = [ln.strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln]  # drop empty lines

    for line in lines:
        # Strip trailing colon (often used as a section header: "شنبه:")
        clean = line.rstrip(":：").strip()
        if not clean:
            # Pure header line — extract anchor, skip
            last_anchor = _extract_date_anchor(line) or last_anchor
            continue

        if _has_date_keyword(clean):
            # This line has its own date context
            result = parser.parse(clean, tz)
            # Update the anchor for subsequent lines
            new_anchor = _extract_date_anchor(clean)
            if new_anchor:
                last_anchor = new_anchor

            if result.is_complete():
                results.append(result)
            elif result.time_found and not result.text_found:
                # It's only a time/anchor header (e.g. "فردا صبح:" — no task body)
                last_anchor = _extract_date_anchor(clean) or last_anchor
                # Don't add to results — it's just an anchor
            else:
                # Has some content but might be incomplete — include anyway
                results.append(result)
        else:
            # No date keyword — prepend the last known anchor
            if last_anchor:
                augmented = f"{last_anchor} {clean}"
            else:
                augmented = clean

            result = parser.parse(augmented, tz)
            results.append(result)

    return results
