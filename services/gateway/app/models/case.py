import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..db import Base


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    service_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    tracking_id: Mapped[str] = mapped_column(
        String, unique=True, nullable=False,
        default=lambda: f"DFL-{uuid.uuid4().hex[:8].upper()}"
    )

    # User-declared application data
    declared_fields: Mapped[dict] = mapped_column(JSON, default=dict)

    # Processing results
    reconciliation_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Tracking
    status_history: Mapped[list] = mapped_column(JSON, default=list)
    rejection_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    # Production
    production_tracking_number: Mapped[str | None] = mapped_column(String, nullable=True)
    pickup_center: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", back_populates="cases")
    documents = relationship("Document", back_populates="case", lazy="selectin")
    payments = relationship("Payment", back_populates="case", lazy="selectin")
    face_results = relationship("FaceResult", back_populates="case", lazy="selectin")
