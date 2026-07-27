"""
تست جامع ربات یادآوری — سناریوهای واقعی کاربران
شامل: لحن‌های مختلف، غلط‌های املایی، ترکیب‌های پیچیده، edge case ها
اجرا: python tests/test_comprehensive.py
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parser import parse_message, parse_multi
from datetime import datetime, timedelta
import pytz

TZ = "Asia/Tehran"
_tz = pytz.timezone(TZ)

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "

total = 0
passed = 0
failed_cases = []


def _now():
    return datetime.now(_tz)


def check(label: str, text: str,
          expect_time: bool = True,
          expect_text: bool = None,
          hour: int = None,
          minute: int = None,
          future: bool = True,
          day_offset: int = None,
          repeat: bool = False):
    """بررسی یک مورد تست."""
    global total, passed
    total += 1

    result = parse_message(text, TZ)

    issues = []

    # بررسی time_found
    if result.time_found != expect_time:
        issues.append(f"time_found={result.time_found} انتظار={expect_time}")

    # بررسی ساعت
    if hour is not None and result.time_found and result.remind_at:
        local = result.remind_at.astimezone(_tz)
        if local.hour != hour:
            issues.append(f"ساعت={local.hour} انتظار={hour}")

    # بررسی دقیقه
    if minute is not None and result.time_found and result.remind_at:
        local = result.remind_at.astimezone(_tz)
        if local.minute != minute:
            issues.append(f"دقیقه={local.minute} انتظار={minute}")

    # بررسی آینده بودن
    if future and result.time_found and result.remind_at:
        now_utc = _now().astimezone(pytz.utc)
        if result.remind_at <= now_utc:
            issues.append("زمان در گذشته است!")

    # بررسی اختلاف روز
    if day_offset is not None and result.time_found and result.remind_at:
        local = result.remind_at.astimezone(_tz)
        expected_date = (_now() + timedelta(days=day_offset)).date()
        if local.date() != expected_date:
            issues.append(f"روز={local.date()} انتظار={expected_date}")

    # بررسی repeat
    if repeat and not result.is_repeat:
        issues.append("repeat تشخیص داده نشد")

    # نمایش نتیجه
    time_str = ""
    if result.remind_at:
        local = result.remind_at.astimezone(_tz)
        time_str = f" → {local.strftime('%H:%M')} {local.strftime('%d/%m')}"
    text_str = f" | «{result.text}»" if result.text else ""
    repeat_str = " 🔁" if result.is_repeat else ""

    if issues:
        status = FAIL
        failed_cases.append((label, text, issues))
    else:
        status = PASS
        passed += 1

    print(f"  {status}  {label:40s}{time_str}{text_str}{repeat_str}")
    if issues:
        for iss in issues:
            print(f"        ⚡ {iss}")


def section(title: str):
    print(f"\n{'─'*65}")
    print(f"  📂 {title}")
    print('─'*65)


# ============================================================
# اجرای تست‌ها
# ============================================================

print("\n" + "="*65)
print("  🧪 تست جامع پارسر فارسی — سناریوهای واقعی")
print("="*65)


# ────────────────────────────────────────────────────────────
section("۱. لحن رسمی و مودبانه")
# ────────────────────────────────────────────────────────────
check("ساعت ۱۵ جلسه دارم",          "لطفاً ساعت ۱۵ جلسه رو یادم بنداز",       hour=15)
check("فردا ظهر دندانپزشکی",         "فردا ظهر دندانپزشکی دارم، یادآوری کن",    hour=12, day_offset=1)
check("جمعه صبح ورزش",               "جمعه صبح ورزش دارم",                      hour=9)
check("هفته آینده جلسه",             "هفته آینده جلسه با مدیر دارم",             expect_time=True)
check("ماه آینده سالگرد",            "ماه آینده سالگرد ازدواجمونه",              expect_time=True)


# ────────────────────────────────────────────────────────────
section("۲. لحن محاوره‌ای و عامیانه")
# ────────────────────────────────────────────────────────────
check("یه ربع دیگه یادم بنداز",      "یه ربع دیگه یادم بنداز آب بخورم",         expect_time=True, expect_text=True)
check("یه ساعته یادم بنداز",         "یه ساعته یادم بنداز",                      expect_time=True)
check("نیم ساعت دیگه",               "نیم ساعت دیگه داروم",                      expect_time=True)
check("چند دقیقه دیگه",              "چند دقیقه دیگه زنگ بزن",                   expect_time=True)
check("امشب ۱۱",                     "امشب ۱۱ فیلم داره",                        hour=23)
check("امشب ساعت ۹",                 "امشب ساعت ۹ زنگ بزنم به مامان",           hour=21)
check("فردا صبح زود",                "فردا صبح زود پرواز دارم",                   hour=7, day_offset=1)
check("شب یادم بنداز",               "شب یادم بنداز قرص بخورم",                  hour=21)


# ────────────────────────────────────────────────────────────
section("۳. لحن تلگرامی / کوتاه")
# ────────────────────────────────────────────────────────────
check("فردا ۸",                       "فردا ۸ بازار",                             hour=8, day_offset=1)
check("فردا ۸ شب",                    "فردا ۸ شب",                                hour=20, day_offset=1)
check("شنبه ۱۰",                      "شنبه ۱۰ جلسه",                             hour=10)
check("۳۰ دقیقه",                     "۳۰ دقیقه داروهام",                         expect_time=True)
check("۲ ساعت دیگه",                  "۲ ساعت دیگه",                              expect_time=True)
check("پنجشنبه عصر",                  "پنجشنبه عصر کتابخونه",                    hour=17)
check("ساعت ۱۴",                      "ساعت ۱۴ تماس با مشتری",                   hour=14)


# ────────────────────────────────────────────────────────────
section("۴. غلط‌های املایی رایج")
# ────────────────────────────────────────────────────────────
check("یادم بنداز غلط",              "یه ربع ياادم بنداز",                        expect_time=True)
check("فردا با نیم‌فاصله بد",        "فرد ا ساعت ۹",                             expect_time=True, hour=9)   # فردا غلطه ولی ساعت ۹ درسته
check("ساعت با فاصله",               "ساعت  ۱۰  جلسه",                           hour=10)
check("دیگه بدون ه",                 "۱۵ دقیقه دیگ زنگ بزن",                     expect_time=True)
check("دیگر به جای دیگه",            "یک ساعت دیگر بهم یادآوری کن",              expect_time=True)
check("بعد به جای دیگه",             "۲۰ دقیقه بعد زنگ بزنم",                    expect_time=True)
check("ي عربی در یادم",              "يادم بنداز ساعت ۱۰",                       hour=10)
check("ك عربی",                      "ساعت ۸ صبح كلاس دارم",                     hour=8)


# ────────────────────────────────────────────────────────────
section("۵. اعداد فارسی و انگلیسی")
# ────────────────────────────────────────────────────────────
check("اعداد فارسی",                 "ساعت ۱۴:۳۰ جلسه",                         hour=14, minute=30)
check("اعداد انگلیسی",              "ساعت 14:30 جلسه",                          hour=14, minute=30)
check("ترکیب",                       "فردا ساعت ۸:30 دندانپزشکی",               hour=8, minute=30, day_offset=1)
check("۱۵ تیر",                      "۱۵ تیر کنکور دارم",                        expect_time=True)
check("پانزدهم مهر",                 "پانزدهم مهر جشن تولدمه",                   expect_time=True)
check("تاریخ کامل جلالی",            "۱۴۰۵/۵/۱ ثبت‌نام مدرسه",                  expect_time=True)


# ────────────────────────────────────────────────────────────
section("۶. اعداد حرفی فارسی")
# ────────────────────────────────────────────────────────────
check("هشت صبح",                     "هشت صبح باشگاه",                           hour=8)
check("ده شب",                       "ده شب فیلم",                               hour=22)
check("یازده صبح",                   "یازده صبح جلسه آنلاین",                    hour=11)
check("دوازده ظهر",                  "دوازده ظهر ناهار با دوستام",               hour=12)
check("سه بعدازظهر",                 "سه بعدازظهر کلاس",                         hour=15)
check("هفت و نیم",                   "هفت و نیم صبحانه بخور",                    hour=7, minute=30)
check("هشت و ربع",                   "هشت و ربع مدرسه",                          hour=8, minute=15)
check("نه و نیم شب",                 "نه و نیم شب سریال",                        hour=21, minute=30)
check("ساعت هفت",                    "ساعت هفت بیدار شو",                        hour=7)
check("ساعت ده",                     "ساعت ده جلسه داری",                        hour=10)


# ────────────────────────────────────────────────────────────
section("۷. زمان نسبی با فاصله زمانی")
# ────────────────────────────────────────────────────────────
check("۵ دقیقه",                     "۵ دقیقه دیگه داروهام",                     expect_time=True)
check("۴۵ دقیقه",                    "۴۵ دقیقه دیگه جلسه شروع میشه",            expect_time=True)
check("سه ساعت دیگه",                "سه ساعت دیگه بهم زنگ بزن",                expect_time=True)
check("چهار ساعت بعد",               "چهار ساعت بعد قرار دارم",                  expect_time=True)
check("دو روز دیگه",                 "دو روز دیگه دارو تموم میشه",               expect_time=True, day_offset=2)
check("سه روز بعد",                  "سه روز بعد مهمانی",                        expect_time=True)
check("یک هفته دیگه",                "یک هفته دیگه امتحان دارم",                 expect_time=True)
check("دو هفته بعد",                 "دو هفته بعد کنفرانس",                      expect_time=True)
check("یک ماه دیگه",                 "یک ماه دیگه بیمه تموم میشه",               expect_time=True)
check("پس فردا",                     "پس فردا دندانپزشکی",                       expect_time=True, day_offset=2)
check("پس‌فردا",                     "پس‌فردا ساعت ۱۰ آزمایشگاه",               expect_time=True, day_offset=2)


# ────────────────────────────────────────────────────────────
section("۸. تکرار (Repeat)")
# ────────────────────────────────────────────────────────────
check("هرروز صبح",                   "هرروز صبح ورزش",                           repeat=True, hour=9)
check("هر روز ساعت ۷",               "هر روز ساعت ۷ صبح آب بخور",               repeat=True, hour=7)
check("هر شب ساعت ۱۰",               "هر شب ساعت ۱۰ قرص بخور",                  repeat=True, hour=22)
check("هرشب",                        "هرشب ساعت ۱۱ مسواک",                      repeat=True, hour=23)
check("هر صبح",                      "هر صبح چک کن ایمیلتو",                    repeat=True)
check("هفتگی",                       "هفتگی یادم بنداز ویتامین",                 repeat=True)
check("ماهانه",                      "ماهانه قبض برق رو چک کن",                  repeat=True)
check("هر دوشنبه",                   "هر دوشنبه جلسه تیم داریم",                 repeat=True)
check("هر جمعه",                     "هر جمعه ۸ صبح ورزش",                       repeat=True, hour=8)
check("هر ۳ روز",                    "هر ۳ روز چک کن",                           repeat=True)
check("هر ۲ ساعت",                   "هر ۲ ساعت آب بخور",                        repeat=True)
check("هر ربع ساعت",                 "هر ربع ساعت نفس عمیق بکش",                repeat=True)
check("هر نیم ساعت",                 "هر نیم ساعت قدم بزن",                      repeat=True)
check("سالانه",                      "سالانه تمدید بیمه",                         repeat=True)
check("یک روز در میان",              "یک روز در میان داروهام",                    repeat=True)


# ────────────────────────────────────────────────────────────
section("۹. روزهای هفته با فرمت‌های مختلف")
# ────────────────────────────────────────────────────────────
check("شنبه",                        "شنبه بانک برم",                            expect_time=True)
check("یکشنبه",                      "یکشنبه صبح دکتر دارم",                    hour=9)
check("دوشنبه",                      "دوشنبه جلسه مهم دارم",                    expect_time=True)
check("سه شنبه",                     "سه شنبه کلاس انگلیسی",                    expect_time=True)
check("چهارشنبه",                    "چهارشنبه شب مهمانی",                      hour=21)
check("پنجشنبه",                     "پنجشنبه آخر هفته خرید",                   expect_time=True)
check("جمعه",                        "جمعه صبح زود پیاده‌روی",                  hour=7)
check("یک شنبه (با فاصله)",          "یک شنبه عصر فوتبال",                      hour=17)
check("آخر هفته",                    "آخر هفته کمپ میریم",                       expect_time=True)


# ────────────────────────────────────────────────────────────
section("۱۰. عبارات مبهم و edge case")
# ────────────────────────────────────────────────────────────
check("فقط متن، بدون زمان",          "برم بانک کارتم رو تمدید کنم",             expect_time=False)
check("فقط زمان",                    "فردا ساعت ۱۰",                             expect_time=True)
check("نیمه شب",                     "نیمه شب بیدارم میکنه",                    hour=0)
check("نصف شب",                      "نصف شب داروهام رو بخورم",                 hour=0)
check("صبح زود",                     "صبح زود پرواز دارم",                       hour=7)
check("اول صبح",                     "اول صبح چک کن",                           hour=7)
check("غروب",                        "غروب قدم بزن",                             hour=18)
check("بامداد",                      "بامداد نماز صبح",                          hour=4)
check("اول ماه",                     "اول ماه قبض بده",                          expect_time=True)
check("آخر ماه",                     "آخر ماه حقوق",                             expect_time=True)
check("سال آینده",                   "سال آینده کنکور دارم",                     expect_time=True)


# ────────────────────────────────────────────────────────────
section("۱۱. ساعت‌های آشکار بدون کلمه ساعت")
# ────────────────────────────────────────────────────────────
check("۱۴:۳۰",                       "۱۴:۳۰ جلسه آنلاین",                       hour=14, minute=30)
check("9:00",                        "9:00 صبحانه",                              hour=9, minute=0)
check("21:45",                       "21:45 خواب",                               hour=21, minute=45)
check("ساعت ۷:۳۰",                   "ساعت ۷:۳۰ صبح",                            hour=7, minute=30)
check("ساعت ۱۳",                     "ساعت ۱۳ ناهار",                            hour=13)
check("ساعت ۱۸:۳۰",                  "ساعت ۱۸:۳۰ ورزش",                         hour=18, minute=30)


# ────────────────────────────────────────────────────────────
section("۱۲. ترکیب‌های پیچیده (تاریخ + ساعت + متن)")
# ────────────────────────────────────────────────────────────
check("فردا ۱۰ صبح دکتر",            "فردا ۱۰ صبح دکتر دارم",                   hour=10, day_offset=1)
check("شنبه ساعت ۹:۳۰ جلسه",        "شنبه ساعت ۹:۳۰ جلسه",                    hour=9, minute=30)
check("پس‌فردا عصر خرید",           "پس‌فردا عصر خرید از بازار",               hour=17, day_offset=2)
check("فردا شب ۲۲ فیلم",             "فردا شب ۲۲ فیلم میبینیم",                 hour=22, day_offset=1)
check("دوشنبه ظهر",                  "دوشنبه ظهر غذا سفارش بده",               hour=12)
check("چهارشنبه ۱۴",                 "چهارشنبه ۱۴ جلسه با تیم",                hour=14)


# ────────────────────────────────────────────────────────────
section("۱۳. پیام‌های چندخطی (parse_multi)")
# ────────────────────────────────────────────────────────────
print("\n  --- چند یادآور یکجا ---")

msg1 = "فردا ساعت ۸ باشگاه\nساعت ۱۲ ناهار با مامان\nساعت ۷ عصر داروهام"
results1 = parse_multi(msg1, TZ)
complete1 = [r for r in results1 if r.is_complete()]
status1 = PASS if len(complete1) >= 2 else FAIL
if len(complete1) >= 2:
    passed += 1
else:
    failed_cases.append(("چند یادآور — تعداد", msg1, [f"فقط {len(complete1)} تا کامل تشخیص داده شد"]))
total += 1
print(f"  {status1}  {'چند یادآور — تعداد':40s} → {len(complete1)} از {len(results1)} کامل")

msg2 = "شنبه:\n۹ صبح دکتر\n۱۲ بانک\n۵ عصر خرید"
results2 = parse_multi(msg2, TZ)
complete2 = [r for r in results2 if r.is_complete()]
status2 = PASS if len(complete2) >= 1 else FAIL
if len(complete2) >= 1:
    passed += 1
else:
    failed_cases.append(("anchor date شنبه", msg2, ["هیچ نتیجه کاملی نداشت"]))
total += 1
print(f"  {status2}  {'anchor date شنبه':40s} → {len(complete2)} از {len(results2)} کامل")


# ────────────────────────────────────────────────────────────
section("۱۴. غلط‌های رایج تایپی (Typos in Time Words)")
# ────────────────────────────────────────────────────────────
check("فردا با غلط نداریم",          "فردا ساعت ۱۰ یادم بنداز",                 expect_time=True, day_offset=1)
check("ساعت با فاصله اضافه",         "ساعت   ۱۰   جلسه",                        hour=10)
check("عدد با نیم‌فاصله",            "ساعت ۱۰\u200cجلسه",                       hour=10)
check("صبح زود مودبانه",             "فردا اول صبح پرواز دارم",                  hour=7, day_offset=1)
check("نيم (ی ناقص)",                "نيم ساعت دیگه داروهام",                    expect_time=True)  # normalize نیم


# ────────────────────────────────────────────────────────────
section("۱۵. لحن‌های عاطفی و غیررسمی")
# ────────────────────────────────────────────────────────────
check("پیام عاطفی با زمان",          "خواهش میکنم فردا ۹ صبح بهم یادم بنداز که زنگ بزنم مامانم", hour=9, day_offset=1)
check("پیام کوتاه تلگرامی",          "فردا ۳",                                   expect_time=True, day_offset=1)
check("پیام با ایموجی",              "فردا ۱۰ 😊 دندانپزشکی",                    hour=10, day_offset=1)
check("پیام با علامت‌گذاری",        "فردا، ساعت ۹! جلسه مهم",                   hour=9, day_offset=1)
check("پیام با ... ",                "امشب ساعت ۱۱... سریال داریم",             hour=23)
check("نگران‌وار",                  "یادم نره! فردا صبح ۸ دارو بخورم",          hour=8, day_offset=1)


# ────────────────────────────────────────────────────────────
# نتیجه نهایی
# ────────────────────────────────────────────────────────────
print("\n" + "="*65)
print(f"  📊 نتیجه کلی: {passed}/{total} موفق  ({100*passed//total}%)")

if failed_cases:
    print(f"\n  ❌ موارد شکست‌خورده ({len(failed_cases)}):")
    for lbl, txt, issues in failed_cases:
        print(f"    • {lbl}: «{txt[:50]}»")
        for iss in issues:
            print(f"       ↳ {iss}")

print("="*65 + "\n")

sys.exit(0 if passed == total else 1)
