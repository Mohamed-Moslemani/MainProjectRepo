"""Per-user idempotency keys for state-changing POST endpoints.

Citizens on flaky 3G submit a case, lose connectivity mid-request,
and the SPA retries. Without a key, that's two pipeline runs on the
same case. Same risk on /payments — two Stripe checkout sessions
for one application.

The contract:
  - Client sends `Idempotency-Key: <client-generated-uuid>` on
    state-changing POSTs that opt in (the cases.submit /
    payments.create endpoints).
  - Gateway looks up (user_id, key, route). If a row exists, replay
    the cached response_json verbatim.
  - Otherwise, run the handler, then atomically insert (key,
    response_json) so a concurrent retry sees the cached result.

Keys are scoped per-user so two citizens picking the same UUID
(astronomically unlikely) wouldn't collide; (user_id, key, route)
is the natural primary key.

Keys older than 24h are cleaned up by a background sweep — by then
the client has either succeeded or given up.
"""

from datetime import datetime, timezone

from sqlalchemy import String, DateTime, JSON, ForeignKey, Integer, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    # The route is part of the composite key so the same client UUID
    # can be (legitimately) reused across endpoints — submit + payment
    # commonly share a "transaction id" client-side.
    route: Mapped[str] = mapped_column(String, nullable=False)

    # Cached response body so the replay returns *exactly* what the
    # original successful call returned.
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    response_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    __table_args__ = (
        PrimaryKeyConstraint("user_id", "key", "route", name="pk_idempotency_keys"),
    )
