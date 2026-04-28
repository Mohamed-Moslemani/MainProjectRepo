"""Biometric appointment booking for passport_new cases.

Lebanese law requires fingerprints captured on GDGS hardware for
every new passport. After approval + payment the citizen books an
appointment at a GDGS centre; an officer confirms the capture
during/after the visit.

Centres are static for now (the eight regional GDGS branches);
future iterations can pull from a real GDGS scheduling API. Slots
are 30-minute blocks, capacity 1 per slot per centre — a real
deployment would expose this through GDGS's own scheduler.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class BiometricAppointment(Base):
    __tablename__ = "biometric_appointments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(
        String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, unique=True,
    )

    # GDGS branch identifier — see lebanese_gdgs_centres.py for the
    # canonical list. Stored as the slug ("gdgs-beirut-mathaf",
    # "gdgs-tripoli", ...) so the SPA can resolve to the bilingual name.
    centre_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Citizen-chosen 30-minute slot start (timezone-aware UTC).
    slot_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )

    # booked | rescheduled | completed | no_show | cancelled
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="booked", index=True,
    )

    # Officer who confirmed capture (for audit). NULL until the visit
    # actually happens.
    confirmed_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
