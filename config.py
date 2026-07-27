"""
Bot configuration - all settings loaded from environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Bot
    BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # Database
    # Railway Volume should be mounted at /data
    # Example:
    # sqlite+aiosqlite:////data/reminders.db
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL_SQLITE",
        "sqlite+aiosqlite:////data/reminders.db"
    )

    # Timezone
    TIMEZONE: str = os.getenv("BOT_TIMEZONE", "Asia/Tehran")

    # Default times for time-of-day keywords
    TIME_MORNING: tuple[int, int] = (9, 0)
    TIME_NOON: tuple[int, int] = (12, 0)
    TIME_AFTERNOON: tuple[int, int] = (14, 0)
    TIME_EVENING: tuple[int, int] = (17, 0)
    TIME_NIGHT: tuple[int, int] = (21, 0)

    # Scheduler
    SCHEDULER_TIMEZONE: str = os.getenv(
        "BOT_TIMEZONE",
        "Asia/Tehran"
    )

    # Logging
    LOG_LEVEL: str = os.getenv(
        "LOG_LEVEL",
        "INFO"
    )


config = Config()
