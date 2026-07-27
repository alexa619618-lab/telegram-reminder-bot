"""
Repository pattern for User CRUD operations.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pytz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(
        self,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> User:
        """Return existing user or create a new one."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await self._session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
            )
            self._session.add(user)
            await self._session.flush()
            logger.info("Created new user telegram_id=%s", telegram_id)

        else:
            # Update metadata only when values actually changed
            changed = False

            if user.username != username:
                user.username = username
                changed = True

            if user.first_name != first_name:
                user.first_name = first_name
                changed = True

            if user.last_name != last_name:
                user.last_name = last_name
                changed = True

            now = datetime.now(pytz.utc)

            # SQLite may return naive datetime values.
            # Convert them to timezone-aware UTC before comparing.
            last_seen = user.last_seen_at

            if last_seen and last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=pytz.utc)

            if changed or (
                now
                - (last_seen or datetime.min.replace(tzinfo=pytz.utc))
            ).seconds > 300:
                user.last_seen_at = now

        return user

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_with_daily_agenda(self) -> list[User]:
        """Get all users who have daily agenda enabled."""
        stmt = select(User).where(User.daily_agenda_enabled == True)  # noqa: E712
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update_default_time(
        self, user: User, time_str: str | None, enabled: bool = True
    ) -> User:
        user.default_reminder_time = time_str
        user.default_time_enabled = enabled
        await self._session.flush()
        return user

    async def toggle_default_time(self, user: User) -> User:
        user.default_time_enabled = not user.default_time_enabled
        await self._session.flush()
        return user

    async def delete_default_time(self, user: User) -> User:
        user.default_reminder_time = None
        user.default_time_enabled = False
        user.forward_behavior = "ask"
        await self._session.flush()
        return user

    async def set_forward_behavior(self, user: User, behavior: str) -> User:
        user.forward_behavior = behavior
        await self._session.flush()
        return user

    async def update_daily_agenda(
        self, user: User, enabled: bool, agenda_time: str | None = None
    ) -> User:
        """Update daily agenda settings for a user."""
        user.daily_agenda_enabled = enabled

        if agenda_time is not None:
            user.daily_agenda_time = agenda_time

        await self._session.flush()

        logger.info(
            "Updated daily agenda for user telegram_id=%s: enabled=%s time=%s",
            user.telegram_id,
            enabled,
            agenda_time or user.daily_agenda_time,
        )

        return user
