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


@router.delete("/cases/{case_id}", status_code=204)
async def admin_delete_case(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    """Hard-delete a case and all its dependent data.

    Admin-only and audit-logged. Use only for testing fixtures or
    explicit citizen "right to erasure" requests. Cascades through
    documents → ocr_results, face_results, payments, biometric
    appointments, audit logs scoped to the case, and the case row
    itself. Files on disk are best-effort cleanup; orphans don't
    break anything.
    """
    from sqlalchemy import delete as sa_delete
    from ..models.document import Document
    from ..models.payment import Payment
    from ..models.face_result import FaceResult
    from ..models.ocr_result import OCRResult
    from ..models.biometric_appointment import BiometricAppointment
    import os

    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    docs_result = await db.execute(select(Document).where(Document.case_id == case_id))
    for doc in docs_result.scalars().all():
        try:
            if doc.file_path and os.path.exists(doc.file_path):
                os.remove(doc.file_path)
        except Exception:  # noqa: BLE001
            pass

    await db.execute(sa_delete(OCRResult).where(
        OCRResult.document_id.in_(
            select(Document.id).where(Document.case_id == case_id)
        )
    ))
    await db.execute(sa_delete(FaceResult).where(FaceResult.case_id == case_id))
    await db.execute(sa_delete(Payment).where(Payment.case_id == case_id))
    await db.execute(sa_delete(BiometricAppointment).where(
        BiometricAppointment.case_id == case_id
    ))
    await db.execute(sa_delete(Document).where(Document.case_id == case_id))
    await db.execute(sa_delete(AuditLog).where(AuditLog.case_id == case_id))
    await db.delete(case)
    await db.commit()

    await log_action(
        db, "admin_case_deleted", user_id=user.id,
        details={
            "deleted_case_id": case_id,
            "service_type": case.service_type,
            "tracking_id": case.tracking_id,
            "from_status": case.status,
        },
    )
    await db.commit()
    return None


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


# ─── Staff user management ─────────────────────────────────────────
# Admin-only. Replaces the `scripts/promote_user.py` SSH workflow with
# a panel an authorised admin can use from the browser. Every change
# is captured in audit_logs (action: admin_user_*).
#
# Roles in this system:
#   citizen — default, owns cases (created via /auth/register)
#   clerk   — reviews queued cases, runs reconciliation overrides
#   mukhtar — district-level attestation; auto-assigned to passport
#             cases by registry_place match (so registry_place +
#             municipality MUST be set when creating one)
#   admin   — everything; only admins can create or change other staff


VALID_ROLES = {"citizen", "clerk", "mukhtar", "admin"}


def _serialize_user(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role,
        "email_verified": u.email_verified,
        "registry_place": u.registry_place,
        "municipality": u.municipality,
        "phone": u.phone,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


@router.get("/users")
async def list_users(
    role: str | None = Query(None),
    q: str | None = Query(None, description="case-insensitive substring on email or full_name"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    """List users with optional role filter and email/name search.
    Pagination via limit + offset; total count returned for the UI.
    """
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)
    if role:
        if role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail=f"role must be one of {sorted(VALID_ROLES)}")
        stmt = stmt.where(User.role == role)
        count_stmt = count_stmt.where(User.role == role)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            (func.lower(User.email).like(like)) | (func.lower(User.full_name).like(like))
        )
        count_stmt = count_stmt.where(
            (func.lower(User.email).like(like)) | (func.lower(User.full_name).like(like))
        )
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        await db.execute(stmt.order_by(User.created_at.desc()).offset(offset).limit(limit))
    ).scalars().all()
    return {
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "users": [_serialize_user(u) for u in rows],
    }


@router.post("/users", status_code=201)
async def create_staff_user(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    """Create a new staff (or citizen) account directly. Bypasses the
    citizen verification flow — admin vouches for the email. The
    account is created with email_verified=True so the new user can
    sign in immediately. Mukhtar role REQUIRES registry_place +
    municipality (case routing matches on those).
    """
    from ..services.auth import hash_password

    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    full_name = (payload.get("full_name") or "").strip()
    role = (payload.get("role") or "citizen").strip().lower()
    registry_place = (payload.get("registry_place") or "").strip() or None
    municipality = (payload.get("municipality") or "").strip() or None
    phone = (payload.get("phone") or "").strip() or None

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not full_name:
        raise HTTPException(status_code=400, detail="full_name required")
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {sorted(VALID_ROLES)}")
    if role == "mukhtar" and (not registry_place or not municipality):
        raise HTTPException(
            status_code=400,
            detail="mukhtar requires both registry_place and municipality",
        )

    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=role,
        registry_place=registry_place,
        municipality=municipality,
        phone=phone,
        email_verified=True,  # admin vouches for the address
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    await log_action(
        db, "admin_user_created", user_id=user.id,
        details={
            "created_user_id": new_user.id,
            "created_user_email": new_user.email,
            "role": new_user.role,
            "registry_place": new_user.registry_place,
            "municipality": new_user.municipality,
        },
    )
    return _serialize_user(new_user)


@router.patch("/users/{user_id}")
async def update_staff_user(
    user_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    """Patch role / location / phone on an existing user. Email and
    password rotation go through dedicated endpoints (auth flow handles
    those securely). Self-demotion is blocked so an admin doesn't
    accidentally lock themselves out — the only way to remove the last
    admin is via DB shell, by design.
    """
    target = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    changes: dict = {}
    new_role = payload.get("role")
    if new_role is not None:
        new_role = new_role.strip().lower()
        if new_role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail=f"role must be one of {sorted(VALID_ROLES)}")
        if target.id == user.id and new_role != "admin":
            raise HTTPException(
                status_code=400,
                detail="Cannot demote yourself — ask another admin",
            )
        if new_role != target.role:
            changes["role"] = {"from": target.role, "to": new_role}
            target.role = new_role

    for field in ("registry_place", "municipality", "phone", "full_name"):
        if field in payload:
            new_val = (payload.get(field) or "").strip() or None
            old_val = getattr(target, field)
            if new_val != old_val:
                changes[field] = {"from": old_val, "to": new_val}
                setattr(target, field, new_val)

    if target.role == "mukhtar" and (not target.registry_place or not target.municipality):
        raise HTTPException(
            status_code=400,
            detail="mukhtar requires both registry_place and municipality",
        )

    if not changes:
        return _serialize_user(target)

    await db.commit()
    await db.refresh(target)

    await log_action(
        db, "admin_user_updated", user_id=user.id,
        details={"target_user_id": target.id, "target_email": target.email, "changes": changes},
    )
    return _serialize_user(target)
