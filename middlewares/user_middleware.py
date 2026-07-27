"""
Middleware that ensures every incoming update has a User object in the data dict.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TelegramUser

from database import AsyncSessionFactory
from services.user_service import UserService

logger = logging.getLogger(__name__)


class UserMiddleware(BaseMiddleware):
    """
    Before each handler runs:
    1. Open a DB session
    2. Get-or-create the User row
    3. Inject ``session`` and ``db_user`` into handler data

    If the user cannot be resolved, ``db_user`` is set to ``None`` so handlers
    that declare it as a required parameter will be skipped automatically by
    aiogram's dependency injection — protecting them from NoneType errors.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Extract Telegram user from the event
        tg_user: TelegramUser | None = data.get("event_from_user")

        async with AsyncSessionFactory() as session:
            data["session"] = session

            if tg_user:
                svc = UserService(session)
                try:
                    db_user = await svc.get_or_create(
                        telegram_id=tg_user.id,
                        username=tg_user.username,
                        first_name=tg_user.first_name,
                        last_name=tg_user.last_name,
                    )
                    await session.commit()
                    data["db_user"] = db_user
                except Exception as exc:
                    logger.exception(
                        "UserMiddleware: failed to get/create user telegram_id=%s: %s",
                        tg_user.id, exc,
                    )
                    await session.rollback()
                    data["db_user"] = None
            else:
                data["db_user"] = None

            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
