"""Password reset service - token generation, validation, and password change."""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.password_reset import PasswordResetToken
from ..models.user import User
from .auth import hash_password

logger = logging.getLogger(__name__)


def _hash_token(token: str) -> str:
    """SHA-256 hash of the raw token. Never store raw tokens."""
    return hashlib.sha256(token.encode()).hexdigest()


async def create_reset_token(db: AsyncSession, user: User) -> str:
    """Generate a cryptographically secure reset token.

    Invalidates any existing unused tokens for this user.
    Returns the raw token (to be sent to user via email).
    """
    settings = get_settings()

    # Invalidate existing unused tokens for this user
    await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used == False,
        )
        .values(used=True)
    )

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.reset_token_expiry_minutes)

    reset_entry = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(reset_entry)
    await db.commit()

    return raw_token


async def validate_and_reset_password(
    db: AsyncSession, raw_token: str, new_password: str
) -> bool:
    """Validate the reset token and change the password.

    Uses constant-time comparison for the token hash.
    Invalidates the token after use and revokes all existing sessions.
    Returns True on success, False if token is invalid/expired/used.
    """
    token_hash = _hash_token(raw_token)

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash
        )
    )
    reset_entry = result.scalar_one_or_none()

    if not reset_entry:
        return False

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(reset_entry.token_hash, token_hash):
        return False

    if reset_entry.used:
        return False

    if datetime.now(timezone.utc) > reset_entry.expires_at:
        return False

    # Mark token as used
    reset_entry.used = True

    # Update password and revoke all existing tokens/sessions
    now = datetime.now(timezone.utc)
    await db.execute(
        update(User)
        .where(User.id == reset_entry.user_id)
        .values(
            password_hash=hash_password(new_password),
            tokens_valid_after=now,
        )
    )

    await db.commit()

    logger.info(f"Password reset completed for user {reset_entry.user_id}")
    return True
