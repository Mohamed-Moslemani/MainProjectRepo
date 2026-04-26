"""Stripe payment service."""

import logging
import stripe
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..config import get_settings
from ..models.payment import Payment
from ..models.case import Case
from ..models.user import User
from .case_machine import get_fee, can_transition
from .audit import log_action
from .email import send_case_status_email
from ..metrics import PAYMENTS_CREATED, PAYMENTS_COMPLETED, PAYMENTS_FAILED, PAYMENT_AMOUNT

logger = logging.getLogger(__name__)


def _get_stripe():
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    return stripe


async def create_checkout_session(db: AsyncSession, case: Case, user_id: str) -> dict:
    """Create a Stripe Checkout Session for a case.

    Returns: {"payment": Payment, "checkout_url": str}
    """
    settings = get_settings()
    _get_stripe()

    amount = get_fee(case.service_type, declared_fields=case.declared_fields)
    if amount == 0:
        raise ValueError(f"No fee defined for service type: {case.service_type}")

    # Service type labels for the checkout page
    service_labels = {
        "id_new": "New National ID",
        "id_renewal": "National ID Renewal",
        "passport_new": "New Passport",
        "passport_renewal": "Passport Renewal",
    }
    label = service_labels.get(case.service_type, case.service_type)

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "usd",
                "unit_amount": amount,
                "product_data": {
                    "name": f"DocFlow Lebanon - {label}",
                    "description": f"Application #{case.tracking_id}",
                },
            },
            "quantity": 1,
        }],
        metadata={
            "case_id": case.id,
            "tracking_id": case.tracking_id,
            "service_type": case.service_type,
        },
        success_url=f"{settings.frontend_base_url}/payment/success?case_id={case.id}&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.frontend_base_url}/payment/cancelled?case_id={case.id}",
    )

    payment = Payment(
        case_id=case.id,
        amount=amount,
        currency="usd",
        stripe_checkout_session_id=session.id,
        status="pending",
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    PAYMENTS_CREATED.inc()
    PAYMENT_AMOUNT.observe(amount)
    await log_action(
        db, "payment_checkout_created", user_id=user_id, case_id=case.id,
        details={"amount": amount, "stripe_session_id": session.id},
    )

    return {"payment": payment, "checkout_url": session.url}


async def handle_checkout_completed(db: AsyncSession, session: dict) -> str:
    """Handle Stripe checkout.session.completed webhook event.

    Returns payment status string.
    """
    session_id = session.get("id", "")
    payment_intent_id = session.get("payment_intent", "")

    stmt = select(Payment).where(Payment.stripe_checkout_session_id == session_id)
    row = await db.execute(stmt)
    payment = row.scalar_one_or_none()
    if not payment:
        return "not_found"

    # Already processed (idempotency)
    if payment.status == "completed":
        return "completed"

    payment.status = "completed"
    payment.stripe_payment_intent_id = payment_intent_id
    PAYMENTS_COMPLETED.inc()

    # Transition case: payment_pending → in_production
    case_result = await db.execute(select(Case).where(Case.id == payment.case_id))
    case = case_result.scalar_one_or_none()
    if case and can_transition(case.status, "in_production"):
        case.status = "in_production"
        case.status_history = case.status_history + [{
            "status": "in_production",
            "message": "Payment received. Document is being produced.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]

    await db.commit()

    await log_action(
        db, "payment_succeeded", case_id=payment.case_id,
        details={
            "stripe_session_id": session_id,
            "stripe_payment_intent_id": payment_intent_id,
            "amount": payment.amount,
        },
    )

    # Send email notification
    if case:
        try:
            user_result = await db.execute(select(User).where(User.id == case.user_id))
            user = user_result.scalar_one_or_none()
            if user:
                await send_case_status_email(
                    to=user.email,
                    full_name=user.full_name,
                    tracking_id=case.tracking_id,
                    service_type=case.service_type,
                    new_status="in_production",
                )
        except Exception:
            logger.exception(f"Failed to send payment email for case {payment.case_id}")

    return "completed"


async def handle_payment_failed(db: AsyncSession, session: dict) -> str:
    """Handle Stripe checkout.session.expired or payment_intent.payment_failed."""
    session_id = session.get("id", "")

    stmt = select(Payment).where(Payment.stripe_checkout_session_id == session_id)
    row = await db.execute(stmt)
    payment = row.scalar_one_or_none()
    if not payment:
        return "not_found"

    payment.status = "failed"
    PAYMENTS_FAILED.inc()

    # Move the parent case to PAYMENT_FAILED so the citizen sees a
    # clear "retry" state in the UI. can_transition guards against
    # double-fires (a redelivered webhook for an already-failed case
    # silently no-ops).
    from sqlalchemy import select as _select
    from ..models.case import Case
    case_row = await db.execute(_select(Case).where(Case.id == payment.case_id))
    case = case_row.scalar_one_or_none()
    if case and can_transition(case.status, "payment_failed"):
        from datetime import datetime, timezone
        case.status = "payment_failed"
        case.status_history = case.status_history + [{
            "status": "payment_failed",
            "message": "Payment failed — citizen can retry from /case detail",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]

    await db.commit()

    await log_action(
        db, "payment_failed", case_id=payment.case_id,
        details={"stripe_session_id": session_id},
    )
    return "failed"