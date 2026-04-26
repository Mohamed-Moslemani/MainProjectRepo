"""Stripe event ledger — webhook idempotency + replay protection.

Stripe retries webhook delivery on any non-2xx response, and even
on 2xx if it doesn't see the response in time. Without a record of
which event IDs we've already handled, a redelivered
`checkout.session.completed` would mark a payment completed twice
and potentially issue duplicate audit / state-machine actions.

Every webhook handler MUST first attempt to insert the Stripe event
ID here. The (`event_id`, primary key) uniqueness gives us atomic
"first delivery wins" — duplicate deliveries get a UniqueViolation
and short-circuit out before re-running the handler.

We also keep `event_type` and the raw payload (for debugging) plus
the case_id we resolved it to, so investigators can pivot from a
duplicate to the original handling.
"""

from datetime import datetime, timezone

from sqlalchemy import String, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class StripeEvent(Base):
    __tablename__ = "stripe_events"

    # Stripe's own event ID (evt_XXXX). Primary key gives us the
    # idempotency guarantee on insert.
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    case_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
