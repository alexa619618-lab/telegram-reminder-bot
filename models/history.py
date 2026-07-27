"""
ReminderHistory model - records every time a reminder fires.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class ReminderHistory(Base):
    __tablename__ = "reminder_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    reminder_id: Mapped[int] = mapped_column(
        ForeignKey("reminders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Status at the time the history entry was created
    action: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # "sent", "snoozed", "done", "cancelled"
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    note: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # Relationship
    reminder: Mapped["Reminder"] = relationship(  # noqa: F821
        "Reminder", back_populates="history"
    )

    def __repr__(self) -> str:
        return f"<ReminderHistory id={self.id} reminder_id={self.reminder_id} action={self.action}>"
