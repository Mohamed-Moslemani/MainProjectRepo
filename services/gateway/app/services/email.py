"""Async SMTP email service — all emails use a unified DocFlow Lebanon template."""

import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib

from ..config import get_settings
from ..metrics import EMAILS_SENT, EMAILS_FAILED

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base template
# ---------------------------------------------------------------------------

def _wrap_email(content_html: str, footer_note: str = "") -> str:
    """Wrap content in the unified DocFlow Lebanon email template."""
    return f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head><meta charset="utf-8"></head>
    <body style="margin: 0; padding: 0; background: #fafbfc; font-family: 'Segoe UI', Tahoma, Arial, sans-serif;">
      <div style="max-width: 600px; margin: 0 auto; background: #ffffff;">

        <!-- Header -->
        <div style="background: linear-gradient(135deg, #006633 0%, #00a651 60%, #00c261 100%);
                    padding: 28px 32px; text-align: center;">
          <div style="display: inline-block; background: rgba(255,255,255,0.15);
                      border-radius: 12px; padding: 8px 20px; margin-bottom: 8px;">
            <span style="font-size: 28px; font-weight: 800; color: #ffffff;
                         letter-spacing: -0.5px;">
              Doc<span style="color: #dcfce7;">Flow</span>
            </span>
          </div>
          <p style="margin: 4px 0 0; color: #dcfce7; font-size: 13px;
                    letter-spacing: 1px; text-transform: uppercase;">
            Lebanon &middot; لبنان
          </p>
        </div>

        <!-- Green accent bar -->
        <div style="height: 4px; background: linear-gradient(90deg, #ed1c24 33%, #00a651 33%, #00a651 67%, #ed1c24 67%);"></div>

        <!-- Body -->
        <div style="padding: 32px 32px 24px;">
          {content_html}
        </div>

        <!-- Footer -->
        <div style="background: #f4f5f7; padding: 20px 32px; border-top: 1px solid #e8eaed; text-align: center;">
          {f'<p style="margin: 0 0 8px; color: #6b7280; font-size: 12px;">{footer_note}</p>' if footer_note else ''}
          <p style="margin: 0; color: #9ca3af; font-size: 11px;">
            DocFlow Lebanon &middot; منصة الوثائق الرسمية اللبنانية
          </p>
          <p style="margin: 4px 0 0; color: #d1d5db; font-size: 10px;">
            &copy; 2026 DocFlow. All rights reserved.
          </p>
        </div>

      </div>
    </body>
    </html>
    """


async def _send_email(to: str, subject: str, html_body: str, email_type: str = "other"):
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
        # 10s cap so a blocked egress (DigitalOcean blocks outbound SMTP
        # by default on new droplets — 25/465/587/2525 all rejected at
        # the network edge) fails fast instead of hanging until nginx's
        # 60s upstream timeout kills the whole HTTP request and returns
        # a 504. Caller already swallows the exception, so the user
        # record + verification token still land in the DB; the citizen
        # can be re-emailed via /auth/resend-verification once SMTP is
        # unblocked or swapped for a transactional API (Resend / SendGrid).
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            start_tls=settings.smtp_use_tls,
            timeout=10,
        )
        EMAILS_SENT.labels(type=email_type).inc()
        logger.info(f"Email sent to {to}: {subject}")
    except Exception:
        EMAILS_FAILED.labels(type=email_type).inc()
        logger.exception(f"Failed to send email to {to}: {subject}")


# ---------------------------------------------------------------------------
# Verification email
# ---------------------------------------------------------------------------

async def send_verification_email(to: str, code: str):
    """Send 6-digit email verification code."""
    settings = get_settings()
    spaced_code = " ".join(code)

    content = f"""
    <h2 style="margin: 0 0 8px; color: #1f2937; font-size: 20px; font-weight: 700;">
      <span style="display: block;">تفعيل حسابك</span>
      <span style="display: block; font-size: 13px; color: #9ca3af; font-weight: 400;">Verify Your Email</span>
    </h2>

    <p style="color: #4b5563; margin: 16px 0 8px; line-height: 1.6;">
      شكراً لتسجيلك في DocFlow Lebanon. استخدم الرمز أدناه لتفعيل بريدك الإلكتروني.
    </p>
    <p style="color: #9ca3af; font-size: 13px; margin: 0 0 24px;">
      Thank you for registering. Use the code below to verify your email address.
    </p>

    <div style="text-align: center; margin: 28px 0;">
      <div style="display: inline-block; background: #f0fdf4; border: 2px dashed #00a651;
                  border-radius: 12px; padding: 20px 40px;">
        <span style="font-size: 36px; font-weight: 800; letter-spacing: 10px;
                     color: #006633; font-family: 'Courier New', monospace;">
          {spaced_code}
        </span>
      </div>
    </div>

    <p style="color: #6b7280; font-size: 13px; text-align: center;">
      ⏱ صالح لمدة {settings.verification_token_expiry_hours} ساعة &middot;
      Valid for {settings.verification_token_expiry_hours} hours
    </p>
    """

    html = _wrap_email(content, "إذا لم تقم بإنشاء حساب، يمكنك تجاهل هذا البريد. / If you didn't create an account, ignore this email.")
    await _send_email(to, "رمز التحقق - DocFlow Lebanon", html, email_type="verification")


# ---------------------------------------------------------------------------
# Password reset email
# ---------------------------------------------------------------------------

async def send_password_reset_email(to: str, token: str):
    """Send password reset link."""
    settings = get_settings()
    frontend_url = settings.cors_allowed_origins.split(",")[0].strip()
    reset_url = f"{frontend_url}/reset-password?token={token}"

    content = f"""
    <h2 style="margin: 0 0 8px; color: #1f2937; font-size: 20px; font-weight: 700;">
      <span style="display: block;">إعادة تعيين كلمة المرور</span>
      <span style="display: block; font-size: 13px; color: #9ca3af; font-weight: 400;">Reset Your Password</span>
    </h2>

    <p style="color: #4b5563; margin: 16px 0 8px; line-height: 1.6;">
      تلقينا طلباً لإعادة تعيين كلمة المرور الخاصة بك. اضغط الزر أدناه لتعيين كلمة مرور جديدة.
    </p>
    <p style="color: #9ca3af; font-size: 13px; margin: 0 0 24px;">
      We received a request to reset your password. Click the button below to set a new one.
    </p>

    <div style="text-align: center; margin: 28px 0;">
      <a href="{reset_url}"
         style="display: inline-block; background: #00a651; color: #ffffff;
                padding: 14px 36px; border-radius: 8px; text-decoration: none;
                font-weight: 700; font-size: 15px; letter-spacing: 0.3px;">
        إعادة تعيين كلمة المرور &middot; Reset Password
      </a>
    </div>

    <p style="color: #9ca3af; font-size: 12px; text-align: center; word-break: break-all;">
      أو انسخ الرابط: <a href="{reset_url}" style="color: #00a651;">{reset_url}</a>
    </p>

    <p style="color: #6b7280; font-size: 13px; text-align: center; margin-top: 16px;">
      ⏱ صالح لمدة {settings.reset_token_expiry_minutes} دقيقة &middot;
      Valid for {settings.reset_token_expiry_minutes} minutes
    </p>
    """

    html = _wrap_email(content, "إذا لم تطلب إعادة تعيين كلمة المرور، تجاهل هذا البريد. / If you didn't request a reset, ignore this email.")
    await _send_email(to, "إعادة تعيين كلمة المرور - DocFlow Lebanon", html, email_type="password_reset")


# ---------------------------------------------------------------------------
# Case status notification emails
# ---------------------------------------------------------------------------

_STATUS_LABELS = {
    "submitted": ("تم تقديم طلبك", "Application Submitted"),
    "approved": ("تمت الموافقة على طلبك", "Application Approved"),
    "payment_pending": ("بانتظار الدفع", "Payment Required"),
    "payment_failed": ("فشل الدفع", "Payment Failed"),
    "rejected": ("تم رفض طلبك", "Application Rejected"),
    "need_info": ("مطلوب معلومات إضافية", "Additional Information Required"),
    "biometric_appointment_required": (
        "حجز موعد البصمات", "Book Biometric Appointment"),
    "in_production": ("طلبك قيد الإنتاج", "Document In Production"),
    "ready_for_pickup": ("مستندك جاهز للاستلام", "Ready for Pickup"),
    "closed": ("تم إغلاق الطلب", "Application Closed"),
}

_STATUS_COLORS = {
    "submitted": "#2563eb",
    "approved": "#00a651",
    "payment_pending": "#f59e0b",
    "payment_failed": "#dc2626",
    "rejected": "#dc2626",
    "need_info": "#f59e0b",
    "biometric_appointment_required": "#f59e0b",
    "in_production": "#2563eb",
    "ready_for_pickup": "#00a651",
    "closed": "#6b7280",
}

_SERVICE_LABELS = {
    "id_new": ("هوية جديدة", "New National ID"),
    "id_renewal": ("تجديد هوية", "ID Renewal"),
    "passport_new": ("جواز سفر جديد", "New Passport"),
    "passport_renewal": ("تجديد جواز سفر", "Passport Renewal"),
}


async def send_case_status_email(
    to: str,
    full_name: str,
    tracking_id: str,
    service_type: str,
    new_status: str,
    notes: str | None = None,
    rejection_reasons: list[str] | None = None,
    *,
    db=None,
):
    """Send an email notification when a case status changes.

    If `db` is supplied, the message is persisted to the durable
    outbox and delivered by the Arq worker (survives gateway crash,
    retries on SMTP failure, exponential backoff). Without `db`,
    falls back to in-process synchronous SMTP — kept for back-compat
    so older call sites don't have to thread the session in
    immediately, but new callers should always pass `db`.
    """
    status_ar, status_en = _STATUS_LABELS.get(new_status, (new_status, new_status))
    service_ar, service_en = _SERVICE_LABELS.get(service_type, (service_type, service_type))
    status_color = _STATUS_COLORS.get(new_status, "#00a651")

    settings = get_settings()
    frontend_url = settings.cors_allowed_origins.split(",")[0].strip()

    # Status badge
    status_badge = f"""
    <div style="text-align: center; margin: 20px 0;">
      <span style="display: inline-block; background: {status_color}; color: #ffffff;
                   padding: 8px 24px; border-radius: 20px; font-weight: 700; font-size: 14px;">
        {status_ar} &middot; {status_en}
      </span>
    </div>
    """

    # Details section (context-specific)
    details_html = ""
    if new_status == "payment_pending":
        details_html = """
        <div style="background: #fffbeb; border-right: 4px solid #f59e0b; padding: 16px 20px;
                    margin: 20px 0; border-radius: 0 8px 8px 0;">
          <p style="margin: 0; color: #92400e; font-weight: 600;">يرجى إتمام الدفع للمتابعة في معالجة طلبك.</p>
          <p style="margin: 6px 0 0; color: #a16207; font-size: 13px;">Please complete your payment to proceed with your application.</p>
        </div>
        """
    elif new_status == "rejected" and rejection_reasons:
        reasons_list = "".join(f'<li style="padding: 4px 0; color: #991b1b;">{r}</li>' for r in rejection_reasons)
        details_html = f"""
        <div style="background: #fef2f2; border-right: 4px solid #dc2626; padding: 16px 20px;
                    margin: 20px 0; border-radius: 0 8px 8px 0;">
          <p style="margin: 0 0 8px; color: #991b1b; font-weight: 600;">أسباب الرفض / Rejection Reasons:</p>
          <ul style="margin: 0; padding-right: 20px; padding-left: 0;">{reasons_list}</ul>
        </div>
        """
    elif new_status == "need_info" and notes:
        details_html = f"""
        <div style="background: #fffbeb; border-right: 4px solid #f59e0b; padding: 16px 20px;
                    margin: 20px 0; border-radius: 0 8px 8px 0;">
          <p style="margin: 0 0 8px; color: #92400e; font-weight: 600;">ملاحظات / Notes:</p>
          <p style="margin: 0; color: #a16207;">{notes}</p>
        </div>
        """
    elif new_status == "ready_for_pickup":
        details_html = """
        <div style="background: #f0fdf4; border-right: 4px solid #00a651; padding: 16px 20px;
                    margin: 20px 0; border-radius: 0 8px 8px 0;">
          <p style="margin: 0; color: #006633; font-weight: 600;">يرجى زيارة المركز المحدد لاستلام مستندك مع بطاقة هوية سارية.</p>
          <p style="margin: 6px 0 0; color: #007a3d; font-size: 13px;">Please visit the designated center to collect your document with a valid ID.</p>
        </div>
        """
    elif new_status == "in_production":
        details_html = """
        <div style="background: #eff6ff; border-right: 4px solid #2563eb; padding: 16px 20px;
                    margin: 20px 0; border-radius: 0 8px 8px 0;">
          <p style="margin: 0; color: #1e40af; font-weight: 600;">تم استلام الدفع. مستندك قيد التحضير.</p>
          <p style="margin: 6px 0 0; color: #1d4ed8; font-size: 13px;">Payment received. Your document is being prepared.</p>
        </div>
        """
    elif new_status == "payment_failed":
        details_html = f"""
        <div style="background: #fef2f2; border-right: 4px solid #dc2626; padding: 16px 20px;
                    margin: 20px 0; border-radius: 0 8px 8px 0;">
          <p style="margin: 0 0 8px; color: #991b1b; font-weight: 600;">لم تكتمل عملية الدفع.</p>
          <p style="margin: 0 0 8px; color: #b91c1c;">يرجى إعادة المحاولة من لوحة التحكم. لن يتم خصم أي مبلغ حتى نجاح الدفع.</p>
          <p style="margin: 6px 0 0; color: #7f1d1d; font-size: 13px;">
            Your payment didn't go through. Retry from your dashboard — nothing is charged until the payment succeeds.
          </p>
        </div>
        """
    elif new_status == "biometric_appointment_required":
        details_html = f"""
        <div style="background: #fffbeb; border-right: 4px solid #f59e0b; padding: 16px 20px;
                    margin: 20px 0; border-radius: 0 8px 8px 0;">
          <p style="margin: 0 0 8px; color: #92400e; font-weight: 600;">
            يرجى حجز موعد لزيارة أحد مراكز الأمن العام لأخذ البصمات والتوقيع.
          </p>
          <p style="margin: 6px 0 0; color: #a16207; font-size: 13px;">
            Please book a slot at a GDGS centre for fingerprint + signature capture. Available 09:00–15:00, Mon–Fri.
          </p>
        </div>
        """
    elif new_status == "closed":
        details_html = """
        <div style="background: #f9fafb; border-right: 4px solid #6b7280; padding: 16px 20px;
                    margin: 20px 0; border-radius: 0 8px 8px 0;">
          <p style="margin: 0; color: #374151;">تم إغلاق طلبك. شكراً لاستخدامك DocFlow.</p>
          <p style="margin: 6px 0 0; color: #6b7280; font-size: 13px;">Your application is closed. Thanks for using DocFlow.</p>
        </div>
        """

    content = f"""
    <p style="color: #4b5563; margin: 0 0 4px; font-size: 16px; line-height: 1.6;">
      مرحباً <strong style="color: #1f2937;">{full_name}</strong>,
    </p>
    <p style="color: #9ca3af; font-size: 13px; margin: 0 0 20px;">
      Here's an update on your application.
    </p>

    {status_badge}

    <!-- Case info card -->
    <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 10px;
                padding: 20px 24px; margin: 20px 0;">
      <table style="width: 100%; border-collapse: collapse;">
        <tr>
          <td style="padding: 8px 0; color: #6b7280; font-size: 13px; width: 45%;">
            رقم التتبع<br><span style="font-size: 11px; color: #9ca3af;">Tracking ID</span>
          </td>
          <td style="padding: 8px 0; font-weight: 700; color: #006633; font-size: 15px; font-family: monospace;">
            #{tracking_id}
          </td>
        </tr>
        <tr>
          <td style="padding: 8px 0; color: #6b7280; font-size: 13px; border-top: 1px solid #dcfce7;">
            نوع الخدمة<br><span style="font-size: 11px; color: #9ca3af;">Service Type</span>
          </td>
          <td style="padding: 8px 0; color: #1f2937; border-top: 1px solid #dcfce7;">
            {service_ar}<br><span style="font-size: 12px; color: #9ca3af;">{service_en}</span>
          </td>
        </tr>
      </table>
    </div>

    {details_html}

    <!-- CTA Button -->
    <div style="text-align: center; margin: 28px 0 8px;">
      <a href="{frontend_url}/dashboard"
         style="display: inline-block; background: #00a651; color: #ffffff;
                padding: 14px 36px; border-radius: 8px; text-decoration: none;
                font-weight: 700; font-size: 15px;">
        عرض طلبك &middot; View Application
      </a>
    </div>
    """

    html = _wrap_email(content)
    subject = f"{status_ar} - #{tracking_id} | DocFlow Lebanon"

    if db is not None:
        from .email_outbox import enqueue
        await enqueue(
            db,
            to_email=to,
            subject=subject,
            html_body=html,
            email_type="status_notification",
            metadata={
                "tracking_id": tracking_id,
                "new_status": new_status,
                "service_type": service_type,
            },
        )
    else:
        await _send_email(to, subject, html, email_type="status_notification")