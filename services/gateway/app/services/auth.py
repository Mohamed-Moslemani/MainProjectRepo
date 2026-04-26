import uuid
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.user import User
from ..models.refresh_token import RefreshToken
from ..schemas.auth import RegisterRequest

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str, role: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_expiry_minutes)
    payload = {"sub": user_id, "role": role, "type": "access", "iat": now, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def issue_refresh_token(db: AsyncSession, user_id: str, role: str) -> str:
    """Mint a new refresh JWT and persist its jti so we can enforce
    single-use rotation on /auth/refresh. The persisted row is what
    distinguishes a forged token (no row) from a reused token (row
    with used_at set).
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.jwt_refresh_expiry_days)
    jti = uuid.uuid4().hex
    payload = {
        "sub": user_id, "role": role, "type": "refresh",
        "iat": now, "exp": expire, "jti": jti,
    }
    db.add(RefreshToken(jti=jti, user_id=user_id, issued_at=now, expires_at=expire))
    await db.commit()
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def rotate_refresh_token(db: AsyncSession, user: User, jti: str) -> str | None:
    """Single-use rotation. Returns the new refresh JWT, or None if
    the presented jti is forged / reused / expired (caller should
    401 in either case).

    On reuse (jti row already has used_at set), revoke every active
    session for this user as a defensive blast — the only ways that
    branch fires are (a) we accidentally accepted a refresh twice
    [bug] or (b) the token leaked. Revoking on (b) protects the
    legitimate user.
    """
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.jti == jti)
    )
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if row is None:
        return None
    if row.user_id != user.id:
        return None  # token belongs to a different user — forged
    if row.expires_at < now:
        return None
    if user.tokens_valid_after and row.issued_at < user.tokens_valid_after:
        # Token issued before a password reset / change — revoked.
        return None
    if row.used_at is not None:
        # Reuse detection: revoke all active sessions for this user.
        user.tokens_valid_after = now
        await db.commit()
        return None

    row.used_at = now
    await db.commit()
    return await issue_refresh_token(db, user.id, user.role)


# Backwards-compat sync helper: still used by `/login` where we want
# the value before committing the parent transaction. Internally just
# wraps issue_refresh_token's flow without persistence — but every
# *production* caller should be on the async helper above.
def create_refresh_token(user_id: str, role: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.jwt_refresh_expiry_days)
    payload = {
        "sub": user_id, "role": role, "type": "refresh",
        "iat": now, "exp": expire, "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str = "access") -> dict:
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"Expected {expected_type} token")
    return payload


async def register_user(db: AsyncSession, req: RegisterRequest) -> User:
    user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        full_name=req.full_name,
        father_name=req.father_name,
        mother_name=req.mother_name,
        date_of_birth=req.date_of_birth,
        place_of_birth=req.place_of_birth,
        gender=req.gender,
        registry_number=req.registry_number,
        registry_place=req.registry_place,
        phone=req.phone,
        address=req.address,
        marital_status=req.marital_status,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user and verify_password(password, user.password_hash):
        return user
    return None


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
