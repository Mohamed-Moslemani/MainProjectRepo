import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..db import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String, ForeignKey("cases.id"), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String, nullable=False)
    # Local filesystem path (legacy; still used by OCR/Face which
    # share the uploads volume in single-node compose). Empty for
    # S3-only uploads in multi-node deployments.
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    # S3 object key (canonical durable copy). Coexists with file_path
    # during the transition; once OCR/Face fetch from S3, file_path
    # becomes optional.
    storage_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    case = relationship("Case", back_populates="documents")
    ocr_result = relationship("OCRResult", back_populates="document", uselist=False, lazy="selectin")
