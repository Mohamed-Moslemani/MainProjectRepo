from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case as sql_case, extract

from ..db import get_db
from ..models.user import User
from ..models.case import Case
from ..models.audit_log import AuditLog
from ..models.payment import Payment
from ..middleware.auth import require_role

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
