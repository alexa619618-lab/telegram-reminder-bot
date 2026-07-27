"""
Reminder model with status and repeat type enums.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, DateTime, Enum, ForeignKey, Integer,
    String, Text, func, Boolean,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class ReminderStatus(str, enum.Enum):
    PENDING = "pending"
    DONE = "done"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SNOOZED = "snoozed"


class RepeatType(str, enum.Enum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    EVERY_N_MINUTES = "every_n_minutes"   # repeat_interval = minutes
    EVERY_N_HOURS = "every_n_hours"       # repeat_interval = hours
    EVERY_N_DAYS = "every_n_days"         # repeat_interval = days
    EVERY_N_WEEKS = "every_n_weeks"       # repeat_interval = weeks
    EVERY_N_MONTHS = "every_n_months"     # repeat_interval = months
    WEEKDAY = "weekday"                   # repeat_interval = 0–6 (Mon–Sun)


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    # Reminder text
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # When to fire
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    # Repeat settings
    repeat_type: Mapped[RepeatType] = mapped_column(
        Enum(RepeatType), default=RepeatType.NONE, nullable=False
    )
    # For EVERY_N_HOURS: interval in hours; EVERY_N_WEEKS: interval in weeks; WEEKDAY: 0=Mon..6=Sun
    repeat_interval: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Status
    status: Mapped[ReminderStatus] = mapped_column(
        Enum(ReminderStatus), default=ReminderStatus.PENDING, nullable=False
    )

    # APScheduler job id so we can cancel/reschedule
    scheduler_job_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Original forwarded message id (if from a forward)
    original_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    original_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Whether this was created via inline mode
    via_inline: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="reminders")  # noqa: F821
    attachments: Mapped[list["Attachment"]] = relationship(  # noqa: F821
        "Attachment", back_populates="reminder", cascade="all, delete-orphan"
    )
    tags: Mapped[list["Tag"]] = relationship(  # noqa: F821
        "Tag", secondary="reminder_tags", back_populates="reminders"
    )
    history: Mapped[list["ReminderHistory"]] = relationship(  # noqa: F821
        "ReminderHistory", back_populates="reminder", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Reminder id={self.id} text={self.text!r} "
            f"at={self.remind_at} status={self.status}>"
        )
