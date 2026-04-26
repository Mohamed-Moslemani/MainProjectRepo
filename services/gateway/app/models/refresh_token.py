"""Refresh-token ledger for rotation + reuse detection.

Industry standard auth: every refresh token gets a unique jti (JWT
ID). On `/auth/refresh`, the gateway looks the jti up here:

  - jti not found    → forged or already-rotated → 401, log nothing
                       (don't help an attacker confirm a guess).
  - used_at not null → REUSE: the legitimate user has rotated past
                       this token, so seeing it again means
                       somebody (us or them) leaked it. Revoke all
                       active sessions for the user
                       (tokens_valid_after = now), 401.
  - else             → rotate: mark this row used, issue a new
                       (access, refresh) pair with a fresh jti,
                       persist the new row.

This guarantees a refresh token can be used at most once. Compare
to the previous design where a single refresh token worked for the
full 15-day expiry — a stolen refresh token would have given the
attacker 15 days of access without rotation forcing them to fight
the legitimate user for the next pair.
"""

from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    # The jti claim baked into the JWT — primary key here gives us
    # atomic rotation.
    jti: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    # NULL until consumed by /auth/refresh; non-NULL means rotated.
    # Re-presenting a token whose used_at is set is a reuse signal.
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
