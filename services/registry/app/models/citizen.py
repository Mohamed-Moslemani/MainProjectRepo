import uuid
from datetime import datetime, date, timezone

from sqlalchemy import String, Date, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Citizen(Base):
    """A record in the (simulated) Lebanese civil registry.

    Mirrors the fields the Ministry of Interior's Directorate General of
    Civil Status tracks — the shape a real integration would return.
    """

    __tablename__ = "citizens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    full_name_en: Mapped[str] = mapped_column(String, nullable=False, index=True)
    full_name_ar: Mapped[str | None] = mapped_column(String, nullable=True)
    father_name: Mapped[str | None] = mapped_column(String, nullable=True)
    mother_name: Mapped[str | None] = mapped_column(String, nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    place_of_birth: Mapped[str | None] = mapped_column(String, nullable=True)
    gender: Mapped[str | None] = mapped_column(String, nullable=True)

    # Civil registry identifiers
    registry_number: Mapped[str] = mapped_column(String, nullable=False, index=True)
    registry_place: Mapped[str] = mapped_column(String, nullable=False, index=True)
    municipality: Mapped[str | None] = mapped_column(String, nullable=True)

    # Real registries track death + nationality — both are material to
    # whether a document can be issued.
    deceased: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    nationality: Mapped[str] = mapped_column(String, nullable=False, default="Lebanese")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
