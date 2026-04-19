from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
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
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    if case_id:
        query = query.where(AuditLog.case_id == case_id)
    if action:
        query = query.where(AuditLog.action == action)
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
