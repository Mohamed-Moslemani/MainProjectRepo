import logging
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db import get_db
from ..config import get_settings
from ..models.user import User
from ..models.case import Case
from ..schemas.payment import PaymentCreate, PaymentResponse
from ..middleware.auth import get_current_user
from ..services.payment import create_checkout_session, handle_checkout_completed, handle_payment_failed

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


@router.post("", response_model=PaymentResponse)
async def create_payment(
    req: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a Stripe Checkout Session for a case."""
    result = await db.execute(select(Case).where(Case.id == req.case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if case.status != "payment_pending":
        raise HTTPException(status_code=400, detail="Case is not in payment_pending status")

    try:
        data = await create_checkout_session(db, case, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Stripe checkout creation failed: {e}")
        raise HTTPException(status_code=502, detail="Payment service error")

    payment = data["payment"]
    return PaymentResponse(
        id=payment.id,
        case_id=payment.case_id,
        amount=payment.amount,
        currency=payment.currency,
        status=payment.status,
        checkout_url=data["checkout_url"],
        created_at=payment.created_at,
    )


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Stripe webhook events with signature verification."""
    settings = get_settings()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    session = event["data"]["object"]

    if event_type == "checkout.session.completed":
        await handle_checkout_completed(db, session)
    elif event_type in ("checkout.session.expired", "payment_intent.payment_failed"):
        await handle_payment_failed(db, session)
    else:
        logger.info(f"Unhandled Stripe event: {event_type}")

    return {"status": "ok"}