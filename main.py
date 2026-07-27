"""
Entry point for the Telegram Reminder Bot.

Usage:
    python main.py
"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import config
from database import close_db, init_db
from handlers import callback_router, inline_router, message_router
from middlewares.user_middleware import UserMiddleware
from scheduler import load_daily_agenda_jobs, load_pending_reminders, scheduler

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    if not config.BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Please configure it as an environment variable.")
        sys.exit(1)

    # Init DB
    await init_db()
    logger.info("Database initialised.")

    # Create bot and dispatcher
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Register middleware
    dp.message.middleware(UserMiddleware())
    dp.callback_query.middleware(UserMiddleware())
    dp.inline_query.middleware(UserMiddleware())
    dp.chosen_inline_result.middleware(UserMiddleware())

    # Register routers (order matters — specific routes first)
    dp.include_router(callback_router)
    dp.include_router(inline_router)
    dp.include_router(message_router)

    # Start scheduler
    scheduler.start()
    logger.info("APScheduler started.")

    # Load pending reminders from DB
    await load_pending_reminders(bot)

    # Load daily agenda jobs from DB
    await load_daily_agenda_jobs(bot)

    # Start polling
    logger.info("Bot is starting (long polling)...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await close_db()
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
