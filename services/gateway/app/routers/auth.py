from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db import get_db
import logging

from ..schemas.auth import (
    RegisterRequest, LoginRequest, TokenResponse, UserResponse,
    RefreshRequest, ForgotPasswordRequest, ResetPasswordRequest,
    VerifyEmailRequest, ResendVerificationRequest,
    ProfileUpdateRequest, ChangePasswordRequest,
)
from ..services.auth import (
    register_user, authenticate_user, create_access_token, create_refresh_token,
    decode_token, hash_password, verify_password,
)
from ..middleware.auth import get_current_user
from datetime import datetime, timezone
from ..services.audit import log_action
from ..services.password_reset import create_reset_token, validate_and_reset_password
from ..services.email_verification import create_verification_token, verify_email_token
from ..services.email import send_verification_email, send_password_reset_email
from ..models.user import User
from ..middleware.rate_limit import rate_limit_login, check_email_rate_limit, rate_limit_reset, rate_limit_verification
from ..metrics import AUTH_REGISTRATIONS, AUTH_LOGINS, AUTH_PASSWORD_RESETS, AUTH_EMAIL_VERIFICATIONS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = await register_user(db, req)
    AUTH_REGISTRATIONS.inc()

    raw_token = await create_verification_token(db, user)
    await send_verification_email(user.email, raw_token)

    await log_action(db, "user_registered", user_id=user.id)
    return user


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit_login)])
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    await check_email_rate_limit(req.email)
    user = await authenticate_user(db, req.email, req.password)
    if not user:
        AUTH_LOGINS.labels(status="failed").inc()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.email_verified:
        AUTH_LOGINS.labels(status="unverified").inc()
        raise HTTPException(
            status_code=403,
            detail="Email not verified. Please check your email for the verification link.",
        )

    AUTH_LOGINS.labels(status="success").inc()
    access = create_access_token(user.id, user.role)
    refresh = create_refresh_token(user.id, user.role)
    await log_action(db, "user_login", user_id=user.id)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(rate_limit_login)])
async def refresh(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(req.refresh_token, expected_type="refresh")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user_id = payload.get("sub")
    user = await db.execute(select(User).where(User.id == user_id))
    user = user.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Reject refresh tokens issued before a password reset
    if user.tokens_valid_after:
        from datetime import datetime, timezone
        token_iat = payload.get("iat")
        if token_iat is not None:
            issued_at = datetime.fromtimestamp(token_iat, tz=timezone.utc)
            if issued_at < user.tokens_valid_after:
                raise HTTPException(
                    status_code=401,
                    detail="Token has been revoked. Please log in again.",
                )

    access = create_access_token(user.id, user.role)
    refresh = create_refresh_token(user.id, user.role)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/forgot-password", dependencies=[Depends(rate_limit_reset)])
async def forgot_password(req: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Request a password reset token.

    Always returns 200 regardless of whether the email exists,
    to prevent user enumeration.
    """
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    AUTH_PASSWORD_RESETS.inc()
    if user:
        raw_token = await create_reset_token(db, user)
        await send_password_reset_email(user.email, raw_token)
        await log_action(
            db, "password_reset_requested", user_id=user.id,
            details={"email": user.email},
        )

    return {"message": "If an account with that email exists, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Reset password using a valid reset token."""
    success = await validate_and_reset_password(db, req.token, req.new_password)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired reset token.",
        )

    await log_action(db, "password_reset_completed")
    return {"message": "Password has been reset successfully. Please log in with your new password."}


@router.post("/verify-email")
async def verify_email(req: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    """Verify a user's email using the token sent during registration."""
    success = await verify_email_token(db, req.token)

    if not success:
        AUTH_EMAIL_VERIFICATIONS.labels(status="failed").inc()
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired verification token.",
        )

    AUTH_EMAIL_VERIFICATIONS.labels(status="success").inc()
    await log_action(db, "email_verified")
    return {"message": "Email verified successfully. You can now log in."}


@router.post("/resend-verification", dependencies=[Depends(rate_limit_verification)])
async def resend_verification(req: ResendVerificationRequest, db: AsyncSession = Depends(get_db)):
    """Resend email verification token.

    Always returns 200 regardless of whether the email exists or is
    already verified, to prevent user enumeration.
    """
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if user and not user.email_verified:
        raw_token = await create_verification_token(db, user)
        await send_verification_email(user.email, raw_token)
        await log_action(
            db, "verification_resent", user_id=user.id,
            details={"email": user.email},
        )

    return {"message": "If an unverified account with that email exists, a verification link has been sent."}


# ---- Account self-service ----

@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    """Return the currently-logged-in user's profile."""
    return user


@router.patch("/me", response_model=UserResponse)
async def update_me(
    req: ProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update the editable subset of the user's profile.

    Identity fields (full_name, DOB, registry number) intentionally
    can't be patched here — they were declared at registration and
    cross-checked against the civil registry. A formal correction
    flow would handle those, not an in-app form.
    """
    payload = req.model_dump(exclude_unset=True)
    changed = []
    for field in ("phone", "address", "marital_status", "place_of_birth"):
        if field in payload and payload[field] != getattr(user, field):
            setattr(user, field, payload[field])
            changed.append(field)
    if changed:
        await db.commit()
        await db.refresh(user)
        await log_action(
            db, "profile_updated", user_id=user.id,
            details={"fields_changed": changed},
        )
    return user


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Change password for the logged-in user.

    Requires the current password (so a stolen access token alone
    can't pivot to permanent account takeover) and rotates
    tokens_valid_after to invalidate every other active session
    for this user — same revocation pattern as forgot-password reset.
    """
    if not verify_password(req.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    if req.new_password == req.current_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current one")

    user.password_hash = hash_password(req.new_password)
    user.tokens_valid_after = datetime.now(timezone.utc)
    await db.commit()

    await log_action(db, "password_changed", user_id=user.id)
    return {"message": "Password changed. All other sessions have been signed out."}
