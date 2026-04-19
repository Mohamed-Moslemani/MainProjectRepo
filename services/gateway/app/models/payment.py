import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..db import Base


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String, ForeignKey("cases.id"), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # in cents
    currency: Mapped[str] = mapped_column(String, nullable=False, default="USD")
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    case = relationship("Case", back_populates="payments")