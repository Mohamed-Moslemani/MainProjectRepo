import uuid
from datetime import datetime, date, timezone
from sqlalchemy import String, DateTime, Date, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)

    # Identity
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    father_name: Mapped[str | None] = mapped_column(String, nullable=True)
    mother_name: Mapped[str | None] = mapped_column(String, nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    place_of_birth: Mapped[str | None] = mapped_column(String, nullable=True)
    gender: Mapped[str | None] = mapped_column(String, nullable=True)

    # Civil registry
    registry_number: Mapped[str | None] = mapped_column(String, nullable=True)
    registry_place: Mapped[str | None] = mapped_column(String, nullable=True)
    municipality: Mapped[str | None] = mapped_column(String, nullable=True)
    # Religious sect (مذهب) — Lebanese civil records carry this. 18
    # officially recognised sects span Christian, Muslim, Druze, and
    # Jewish denominations. Stored as the canonical English token
    # ("maronite", "sunni", "druze", etc); citizen-facing UI maps to
    # Arabic. Optional because some citizens decline to disclose.
    religious_sect: Mapped[str | None] = mapped_column(String, nullable=True)

    # Contact & address
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    address: Mapped[str | None] = mapped_column(String, nullable=True)
    marital_status: Mapped[str | None] = mapped_column(String, nullable=True)

    # System
    role: Mapped[str] = mapped_column(String, nullable=False, default="citizen")
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    tokens_valid_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    cases = relationship(
        "Case",
        back_populates="user",
        lazy="selectin",
        foreign_keys="Case.user_id",
    )
