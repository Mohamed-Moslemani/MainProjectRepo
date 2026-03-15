"""Email verification service - 6-digit code generation, validation, and email confirmation."""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.email_verification import EmailVerificationToken
from ..models.user import User

logger = logging.getLogger(__name__)


def _hash_token(token: str) -> str:
    """SHA-256 hash of the raw token. Never store raw tokens."""
    return hashlib.sha256(token.encode()).hexdigest()


def _generate_code() -> str:
    """Generate a cryptographically secure 6-digit numeric code."""
    return f"{secrets.randbelow(1_000_000):06d}"


async def create_verification_token(db: AsyncSession, user: User) -> str:
    """Generate a 6-digit verification code.

    Invalidates any existing unused tokens for this user.
    Returns the raw code (to be sent to user via email).
    """
    settings = get_settings()

    # Invalidate existing unused tokens for this user
    await db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.used == False,
        )
        .values(used=True)
    )

    raw_code = _generate_code()
    token_hash = _hash_token(raw_code)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.verification_token_expiry_hours)

    entry = EmailVerificationToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(entry)
    await db.commit()

    return raw_code


async def verify_email_token(db: AsyncSession, raw_token: str) -> bool:
    """Validate a verification code and mark the user's email as verified.

    Uses constant-time comparison for the token hash.
    Single-use: token is invalidated after successful verification.
    Returns True on success, False if token is invalid/expired/used.
    """
    token_hash = _hash_token(raw_token)

    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash
        )
    )
    entry = result.scalar_one_or_none()

    if not entry:
        return False

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(entry.token_hash, token_hash):
        return False

    if entry.used:
        return False

    if datetime.now(timezone.utc) > entry.expires_at:
        return False

    # Mark token as used
    entry.used = True

    # Mark user's email as verified
    await db.execute(
        update(User)
        .where(User.id == entry.user_id)
        .values(email_verified=True)
    )

    await db.commit()

    logger.info(f"Email verified for user {entry.user_id}")
    return True