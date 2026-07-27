"""
Attachment model - stores file references for forwarded messages.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    reminder_id: Mapped[int] = mapped_column(
        ForeignKey("reminders.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Telegram file references
    file_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    file_unique_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    file_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="text"
    )  # text, photo, video, audio, document, voice, sticker

    # Original forwarded text (if type is text)
    content: Mapped[Optional[str]] = mapped_column(String(4096), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationship
    reminder: Mapped["Reminder"] = relationship(  # noqa: F821
        "Reminder", back_populates="attachments"
    )

    def __repr__(self) -> str:
        return f"<Attachment id={self.id} type={self.file_type} reminder_id={self.reminder_id}>"
