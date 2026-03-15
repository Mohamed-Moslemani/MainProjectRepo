from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db import get_db
import logging

from ..schemas.auth import (
    RegisterRequest, LoginRequest, TokenResponse, UserResponse,
    RefreshRequest, ForgotPasswordRequest, ResetPasswordRequest,
    VerifyEmailRequest, ResendVerificationRequest,
)
from ..services.auth import register_user, authenticate_user, create_access_token, create_refresh_token, decode_token
from ..services.audit import log_action
from ..services.password_reset import create_reset_token, validate_and_reset_password
from ..services.email_verification import create_verification_token, verify_email_token
from ..services.email import send_verification_email, send_password_reset_email
from ..models.user import User
from ..middleware.rate_limit import rate_limit_login, check_email_rate_limit, rate_limit_reset, rate_limit_verification

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = await register_user(db, req)

    raw_token = await create_verification_token(db, user)
    await send_verification_email(user.email, raw_token)

    await log_action(db, "user_registered", user_id=user.id)
    return user


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit_login)])
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    await check_email_rate_limit(req.email)
    user = await authenticate_user(db, req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.email_verified:
        raise HTTPException(
            status_code=403,
            detail="Email not verified. Please check your email for the verification link.",
        )

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
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired verification token.",
        )

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
