import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Float, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..db import Base


class FaceResult(Base):
    __tablename__ = "face_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String, ForeignKey("cases.id"), nullable=False, index=True)
    selfie_document_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id"), nullable=False)
    reference_document_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id"), nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    liveness_score: Mapped[float] = mapped_column(Float, nullable=False)
    liveness_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    processing_time_ms: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    case = relationship("Case", back_populates="face_results")
