"""
Tag model for categorizing reminders.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Table, Column, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

# Association table
reminder_tags = Table(
    "reminder_tags",
    Base.metadata,
    Column("reminder_id", Integer, ForeignKey("reminders.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="tags")  # noqa: F821
    reminders: Mapped[list["Reminder"]] = relationship(  # noqa: F821
        "Reminder", secondary="reminder_tags", back_populates="tags"
    )

    def __repr__(self) -> str:
        return f"<Tag id={self.id} name={self.name!r}>"


# Alias for __init__.py import
ReminderTag = reminder_tags
