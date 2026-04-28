"""Durable email outbox — transactional outbox pattern for SMTP.

Problem we're solving: today, send_verification_email() runs inline
during /auth/register. If SMTP times out (Gmail rate-limit, network
blip, or a misconfigured prod relay), the citizen finishes
registration but never gets the verification mail — and there's no
record we tried.

Outbox pattern:
  1. Inside the same DB transaction that creates a User /
     PasswordResetToken / Case status change, we INSERT a row here
     with the email payload and `status='pending'`.
  2. A separate sweep (cron or Arq scheduled job) picks pending rows
     and enqueues `send_email_outbox_job` for each.
  3. The worker actually attempts SMTP. On success → status='sent'.
     On failure → bumped attempt_count + last_error; max 5 attempts
     with exponential backoff before status='failed' (alerted on).

Critical property: the user's data + the intent-to-email both commit
atomically. Email delivery is then asynchronous and can be retried
indefinitely without losing the original intent. If SMTP is down for
2 hours we'll catch up the moment it's back.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class EmailOutbox(Base):
    __tablename__ = "email_outbox"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    to_email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    html_body: Mapped[str] = mapped_column(Text, nullable=False)
    email_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # Free-form context for filtering / analytics — case_id when the
    # email belongs to a case, user_id otherwise. Kept as JSON so the
    # column doesn't need a schema change every time we add a field.
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", index=True,
    )  # pending | sent | failed
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )
