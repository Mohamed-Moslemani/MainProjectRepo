"""Outbox queue API + per-row delivery worker.

Two functions matter to callers:

  enqueue(db, to, subject, html, *, email_type, metadata)
      Inserts a pending row in the same db transaction the caller is
      building. The caller still calls db.commit() — the outbox row
      lands or rolls back atomically with the rest of the change.

  deliver_outbox_entry(db, outbox_id) -> bool
      Run by the Arq worker (queue.send_email_outbox_job). Looks up
      the row, attempts SMTP via the existing email service, marks
      sent / failed, schedules the next attempt with exponential
      backoff. Returns True on successful delivery.

A periodic sweep (scripts/sweep_email_outbox.py, cron-triggered)
picks up pending rows whose next_attempt_at has passed and enqueues
delivery jobs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.email_outbox import EmailOutbox

logger = logging.getLogger(__name__)


MAX_ATTEMPTS = 5
# Exponential: 1m, 5m, 15m, 1h, 4h. After that we mark failed.
_BACKOFF_MINUTES = [1, 5, 15, 60, 240]


async def enqueue(
    db: AsyncSession,
    *,
    to_email: str,
    subject: str,
    html_body: str,
    email_type: str = "other",
    metadata: dict[str, Any] | None = None,
) -> EmailOutbox:
    """Add a pending email to the outbox (atomic with caller's txn).

    Caller is responsible for calling db.commit() — that ensures the
    outbox row is only durable if the parent action (user_registered,
    password_reset_requested, etc.) also committed.
    """
    row = EmailOutbox(
        to_email=to_email,
        subject=subject,
        html_body=html_body,
        email_type=email_type,
        metadata_=metadata or {},
        status="pending",
        attempt_count=0,
        next_attempt_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()  # populate row.id without committing
    return row


async def deliver_outbox_entry(db: AsyncSession, outbox_id: str) -> bool:
    """Attempt to send a single outbox row. Returns True on success."""
    row_result = await db.execute(select(EmailOutbox).where(EmailOutbox.id == outbox_id))
    row = row_result.scalar_one_or_none()
    if row is None:
        logger.warning("deliver_outbox_entry: row not found", extra={"outbox_id": outbox_id})
        return False
    if row.status == "sent":
        return True   # idempotent — concurrent worker won the race

    # Reuse the existing low-level _send_email; it knows how to talk
    # SMTP with the right TLS / auth from settings.
    from .email import _send_email
    try:
        await _send_email(row.to_email, row.subject, row.html_body, row.email_type)
        row.status = "sent"
        row.sent_at = datetime.now(timezone.utc)
        row.last_error = None
        await db.commit()
        logger.info("outbox delivered", extra={"outbox_id": outbox_id, "email_type": row.email_type})
        return True
    except Exception as exc:  # noqa: BLE001
        row.attempt_count += 1
        row.last_error = str(exc)[:1000]
        if row.attempt_count >= MAX_ATTEMPTS:
            row.status = "failed"
            row.next_attempt_at = None
            logger.error(
                "outbox permanently failed after %d attempts",
                row.attempt_count,
                extra={"outbox_id": outbox_id, "error": str(exc)[:200]},
            )
        else:
            backoff_minutes = _BACKOFF_MINUTES[min(row.attempt_count, len(_BACKOFF_MINUTES) - 1)]
            row.next_attempt_at = datetime.now(timezone.utc) + timedelta(minutes=backoff_minutes)
            logger.warning(
                "outbox attempt %d failed; retry in %dm",
                row.attempt_count, backoff_minutes,
                extra={"outbox_id": outbox_id, "error": str(exc)[:200]},
            )
        await db.commit()
        return False


async def sweep_pending(db: AsyncSession, *, limit: int = 100) -> list[str]:
    """Find pending rows whose next_attempt_at has passed. Caller
    enqueues a delivery job per id and returns the count."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(EmailOutbox)
        .where(EmailOutbox.status == "pending")
        .where(EmailOutbox.next_attempt_at <= now)
        .limit(limit)
    )
    return [row.id for row in result.scalars().all()]
