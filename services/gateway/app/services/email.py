"""Async SMTP email service for verification and password reset emails."""

import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib

from ..config import get_settings

logger = logging.getLogger(__name__)


async def _send_email(to: str, subject: str, html_body: str):
    """Send an email via SMTP. Logs and swallows errors so callers don't fail."""
    settings = get_settings()

    if not settings.smtp_user:
        logger.warning(f"SMTP not configured. Would have sent to {to}: {subject}")
        return

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            start_tls=settings.smtp_use_tls,
        )
        logger.info(f"Email sent to {to}: {subject}")
    except Exception:
        logger.exception(f"Failed to send email to {to}: {subject}")


async def send_verification_email(to: str, code: str):
    """Send 6-digit email verification code."""
    settings = get_settings()

    spaced_code = " ".join(code)

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #00a651;">DocFlow Lebanon</h2>
        <p>Thank you for registering. Use the code below to verify your email address:</p>
        <div style="margin: 32px 0; text-align: center;">
            <div style="display: inline-block; background: #f4f5f7; border: 2px dashed #00a651;
                        border-radius: 12px; padding: 20px 40px;">
                <span style="font-size: 36px; font-weight: 800; letter-spacing: 8px;
                             color: #1f2937; font-family: monospace;">
                    {spaced_code}
                </span>
            </div>
        </div>
        <p style="color: #666; font-size: 14px;">
            This code expires in {settings.verification_token_expiry_hours} hours.
        </p>
        <p style="color: #666; font-size: 14px;">
            Enter this code on the verification page to activate your account.
        </p>
        <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
        <p style="color: #999; font-size: 12px;">
            If you did not create an account, you can safely ignore this email.
        </p>
    </div>
    """

    await _send_email(to, "Your verification code - DocFlow Lebanon", html)


async def send_password_reset_email(to: str, token: str):
    """Send password reset link."""
    settings = get_settings()
    frontend_url = settings.cors_allowed_origins.split(",")[0].strip()
    reset_url = f"{frontend_url}/reset-password?token={token}"

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2>Reset your password - DocFlow Lebanon</h2>
        <p>We received a request to reset your password. Click the link below to set a new password:</p>
        <p style="margin: 24px 0;">
            <a href="{reset_url}"
               style="background-color: #1a73e8; color: white; padding: 12px 24px;
                      text-decoration: none; border-radius: 4px; display: inline-block;">
                Reset Password
            </a>
        </p>
        <p style="color: #666; font-size: 14px;">
            Or copy this link: <code>{reset_url}</code>
        </p>
        <p style="color: #666; font-size: 14px;">
            This link expires in {settings.reset_token_expiry_minutes} minutes.
        </p>
        <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
        <p style="color: #999; font-size: 12px;">
            If you did not request a password reset, you can safely ignore this email.
        </p>
    </div>
    """

    await _send_email(to, "Reset your password - DocFlow Lebanon", html)
