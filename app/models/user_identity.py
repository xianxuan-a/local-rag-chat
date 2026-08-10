"""Globally unique login identities mapped to application users."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime, utc_now

if TYPE_CHECKING:
    from app.models.user import User


class UserIdentity(Base):
    """One normalized username or email value in the shared login namespace."""

    __tablename__ = "user_identities"
    __table_args__ = (Index("ix_user_identities_user_id", "user_id"),)

    normalized_value: Mapped[str] = mapped_column(
        String(640), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="identities")
