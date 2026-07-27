"""
User model - stores Telegram user info and personal settings.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Timezone
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Tehran", nullable=False)

    # Default reminder time (HH:MM format, e.g. "09:00")
    default_reminder_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    default_time_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Forward behavior: "ask" (always ask) or "use_default" (use default time)
    forward_behavior: Mapped[str] = mapped_column(String(16), default="ask", nullable=False)

    # Daily agenda (خلاصه برنامه روز)
    daily_agenda_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    daily_agenda_time: Mapped[str] = mapped_column(String(5), default="08:00", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    reminders: Mapped[list["Reminder"]] = relationship(  # noqa: F821
        "Reminder", back_populates="user", lazy="select"
    )
    tags: Mapped[list["Tag"]] = relationship(  # noqa: F821
        "Tag", back_populates="user", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} telegram_id={self.telegram_id} name={self.first_name}>"
