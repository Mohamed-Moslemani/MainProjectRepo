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

    # Liveness session (from AWS Rekognition Face Liveness)
    liveness_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    liveness_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Mukhtar approval (passport services)
    mukhtar_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    mukhtar_approval: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generated_form_path: Mapped[str | None] = mapped_column(String, nullable=True)

    # Processing results
    reconciliation_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    registry_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Provenance: { "ocr": {...}, "face": {...}, "registry": {...},
    # "risk": {...} } captured from each AI service's model_info dict
    # on every pipeline run. Lets us replay a decision against the
    # exact same model versions + thresholds that produced it.
    model_versions: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Tracking
    status_history: Mapped[list] = mapped_column(JSON, default=list)
    rejection_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Set when the pipeline rejects an upload for quality reasons (blur,
    # glare, low-res, skew). Drives the citizen-facing "retake" UX. Cleared
    # when the case is re-submitted.
    retake_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
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

    user = relationship("User", back_populates="cases", foreign_keys=[user_id])
    documents = relationship("Document", back_populates="case", lazy="selectin")
    payments = relationship("Payment", back_populates="case", lazy="selectin")
    face_results = relationship("FaceResult", back_populates="case", lazy="selectin")
