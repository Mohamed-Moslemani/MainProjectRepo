from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case as sql_case, extract

from ..db import get_db
from ..models.user import User
from ..models.case import Case
from ..models.audit_log import AuditLog
from ..models.payment import Payment
from ..models.stripe_event import StripeEvent
from ..middleware.auth import require_role
from ..services.audit import log_action

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# Lebanese governorates for grouping by registry_place
GOVERNORATES = [
    "Beirut", "Mount Lebanon", "North Lebanon", "Akkar",
    "South Lebanon", "Nabatieh", "Beqaa", "Baalbek-Hermel",
]


@router.get("/cases")
async def list_all_cases(
    status: str | None = None,
    service_type: str | None = None,
    search: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("clerk", "admin")),
):
    query = select(Case).order_by(Case.created_at.desc())
    count_query = select(func.count(Case.id))

    if status:
        query = query.where(Case.status == status)
        count_query = count_query.where(Case.status == status)
    if service_type:
        query = query.where(Case.service_type == service_type)
        count_query = count_query.where(Case.service_type == service_type)
    if search:
        query = query.where(Case.tracking_id.ilike(f"%{search}%"))
        count_query = count_query.where(Case.tracking_id.ilike(f"%{search}%"))

    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    cases = list(result.scalars().all())
    total = (await db.execute(count_query)).scalar()

    return {"cases": cases, "total": total, "limit": limit, "offset": offset}


@router.get("/cases.csv")
async def export_cases_csv(
    status: str | None = None,
    service_type: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("clerk", "admin")),
):
    """Export the filtered case list as CSV.

    Same filter contract as /admin/cases (status, service_type,
    search by tracking_id). Streams the full filtered set (no
    pagination) so a clerk can pull a ministry-style report. The
    columns are intentionally a *non-PII* projection — tracking
    ID, service, status, age, risk score, routing — so the exported
    file can be passed around inside the admin team without
    leaking citizen names or registry numbers.
    """
    import csv
    import io
    from fastapi.responses import StreamingResponse

    query = select(Case).order_by(Case.created_at.desc())
    if status:
        query = query.where(Case.status == status)
    if service_type:
        query = query.where(Case.service_type == service_type)
    if search:
        query = query.where(Case.tracking_id.ilike(f"%{search}%"))

    result = await db.execute(query)
    cases = list(result.scalars().all())

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "tracking_id", "service_type", "status",
        "created_at", "updated_at",
        "risk_score", "routing",
        "mukhtar_assigned", "has_payment",
    ])
    for c in cases:
        risk = (c.risk_result or {}).get("risk_score")
        routing = (c.risk_result or {}).get("routing")
        writer.writerow([
            c.tracking_id,
            c.service_type,
            c.status,
            c.created_at.isoformat() if c.created_at else "",
            c.updated_at.isoformat() if c.updated_at else "",
            "" if risk is None else risk,
            routing or "",
            "yes" if c.mukhtar_id else "",
            "yes" if c.payments else "",
        ])

    buf.seek(0)
    filename = f"docflow-cases-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/cases/{case_id}/full")
async def get_case_full(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("clerk", "admin")),
):
    """Get full case details including owner info, for admin review."""
    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Case not found")

    # Get case owner
    owner_result = await db.execute(select(User).where(User.id == case.user_id))
    owner = owner_result.scalar_one_or_none()

    owner_info = None
    if owner:
        owner_info = {
            "id": owner.id,
            "email": owner.email,
            "full_name": owner.full_name,
            "father_name": owner.father_name,
            "mother_name": owner.mother_name,
            "date_of_birth": str(owner.date_of_birth) if owner.date_of_birth else None,
            "place_of_birth": owner.place_of_birth,
            "gender": owner.gender,
            "registry_number": owner.registry_number,
            "registry_place": owner.registry_place,
            "phone": owner.phone,
            "address": owner.address,
            "marital_status": owner.marital_status,
        }

    # Get payments
    pay_result = await db.execute(select(Payment).where(Payment.case_id == case_id))
    payments = [{
        "id": p.id, "amount": p.amount, "currency": p.currency,
        "status": p.status, "created_at": p.created_at.isoformat(),
    } for p in pay_result.scalars().all()]

    return {
        "case": case,
        "owner": owner_info,
        "payments": payments,
    }


@router.get("/audit-logs")
async def list_audit_logs(
    case_id: str | None = None,
    action: str | None = None,
    user_id: str | None = None,
    request_id: str | None = None,
    since: str | None = None,   # ISO-8601 inclusive lower bound
    until: str | None = None,   # ISO-8601 inclusive upper bound
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    """List audit log rows.

    All filter params combine with AND. The `since` / `until` bounds
    accept any ISO-8601 timestamp (with or without timezone — bare
    timestamps are interpreted as UTC). Used by the admin console
    to scope investigations to a date range / user / request.
    """
    from datetime import datetime, timezone

    def _parse_dt(raw: str) -> datetime:
        # Strip trailing Z so fromisoformat accepts it on Python <3.11
        cleaned = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    if case_id:
        query = query.where(AuditLog.case_id == case_id)
    if action:
        query = query.where(AuditLog.action == action)
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    if request_id:
        query = query.where(AuditLog.request_id == request_id)
    if since:
        try:
            query = query.where(AuditLog.created_at >= _parse_dt(since))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid 'since' timestamp: {since}")
    if until:
        try:
            query = query.where(AuditLog.created_at <= _parse_dt(until))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid 'until' timestamp: {until}")
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    logs = list(result.scalars().all())
    return {"logs": logs, "limit": limit, "offset": offset}


@router.get("/stats")
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("clerk", "admin")),
):
    total_cases = (await db.execute(select(func.count(Case.id)))).scalar()

    # By status
    by_status = {}
    result = await db.execute(
        select(Case.status, func.count(Case.id)).group_by(Case.status)
    )
    for row in result.all():
        by_status[row[0]] = row[1]

    # By service type
    by_service = {}
    result = await db.execute(
        select(Case.service_type, func.count(Case.id)).group_by(Case.service_type)
    )
    for row in result.all():
        by_service[row[0]] = row[1]

    # Manual review queue count (risk_evaluated = pending clerk decision)
    review_queue = by_status.get("risk_evaluated", 0)

    # Total users
    total_users = (await db.execute(select(func.count(User.id)))).scalar()

    # Revenue (completed payments)
    revenue_result = await db.execute(
        select(func.sum(Payment.amount)).where(Payment.status == "completed")
    )
    total_revenue = revenue_result.scalar() or 0

    # Cases created today
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = (await db.execute(
        select(func.count(Case.id)).where(Case.created_at >= today_start)
    )).scalar()

    return {
        "total_cases": total_cases,
        "by_status": by_status,
        "by_service": by_service,
        "review_queue": review_queue,
        "total_users": total_users,
        "total_revenue_cents": total_revenue,
        "cases_today": today_count,
    }


# ── Stripe webhook replay ─────────────────────────────────────────
#
# Stripe retries delivery on any non-2xx, but it stops once it sees
# a 200. If our handler later errors *after* persisting the
# StripeEvent row (DB blip, downstream service down, code bug), the
# event is recorded as "received" but its side-effects never ran —
# Stripe won't retry. The replay endpoint lets an admin re-invoke
# the handler against the stored payload, idempotent against the
# state machine (handlers are no-ops when the case is already in
# the target state).

@router.get("/stripe-events")
async def list_stripe_events(
    limit: int = Query(50, le=500),
    offset: int = 0,
    event_type: str | None = None,
    case_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    """Recent Stripe webhook deliveries, newest first."""
    q = select(StripeEvent).order_by(StripeEvent.received_at.desc())
    if event_type:
        q = q.where(StripeEvent.event_type == event_type)
    if case_id:
        q = q.where(StripeEvent.case_id == case_id)
    rows = (await db.execute(q.limit(limit).offset(offset))).scalars().all()
    return {
        "events": [
            {
                "event_id": r.event_id,
                "event_type": r.event_type,
                "case_id": r.case_id,
                "received_at": r.received_at.isoformat(),
                "payload_summary": {
                    "id": (r.payload or {}).get("id"),
                    "amount_total": (r.payload or {}).get("amount_total"),
                    "payment_status": (r.payload or {}).get("payment_status"),
                    "metadata": (r.payload or {}).get("metadata") or {},
                },
            }
            for r in rows
        ],
        "limit": limit,
        "offset": offset,
    }


@router.post("/stripe-events/{event_id}/replay")
async def replay_stripe_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    """Re-run the webhook handler against a stored event payload.

    Safe to call repeatedly: handlers short-circuit on idempotent
    state transitions (e.g. a checkout.session.completed against an
    already-paid case is a no-op). Audit-logged on every invocation.
    """
    from ..services.payment import handle_checkout_completed, handle_payment_failed

    row = (await db.execute(
        select(StripeEvent).where(StripeEvent.event_id == event_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Stripe event not found")

    payload = row.payload or {}
    if not payload:
        # Older rows (pre-replay-feature) only stored {id, type}.
        # We can't replay those — Stripe is the only source of the
        # full session object and we no longer have it.
        raise HTTPException(
            status_code=409,
            detail="This event predates payload retention; replay impossible. "
                   "Trigger a fresh webhook from the Stripe dashboard instead.",
        )

    try:
        if row.event_type == "checkout.session.completed":
            await handle_checkout_completed(db, payload)
        elif row.event_type in ("checkout.session.expired",
                                 "payment_intent.payment_failed"):
            await handle_payment_failed(db, payload)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Event type '{row.event_type}' has no replay handler",
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        await log_action(
            db, "stripe_event_replay_failed", user_id=user.id,
            case_id=row.case_id,
            details={"event_id": event_id, "error": str(exc)[:500]},
        )
        raise HTTPException(status_code=500, detail=f"Replay failed: {exc}")

    await log_action(
        db, "stripe_event_replayed", user_id=user.id,
        case_id=row.case_id,
        details={"event_id": event_id, "event_type": row.event_type},
    )
    return {"status": "ok", "event_id": event_id, "event_type": row.event_type}
