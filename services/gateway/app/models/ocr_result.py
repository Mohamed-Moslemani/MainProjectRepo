import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..db import Base


class OCRResult(Base):
    __tablename__ = "ocr_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(
        String, ForeignKey("documents.id"), nullable=False, unique=True
    )
    extracted_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    quality_assessment: Mapped[dict] = mapped_column(JSON, default=dict)
    retake_required: Mapped[bool] = mapped_column(Boolean, default=False)
    retake_reasons: Mapped[list] = mapped_column(JSON, default=list)
    processing_time_ms: Mapped[int | None] = mapped_column(nullable=True)
    # SHA-256 of the input file at the time OCR ran, captured by the
    # OCR service. Pairs with model_info on the parent case to make
    # this decision fully reproducible.
    input_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    document = relationship("Document", back_populates="ocr_result")
