from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..db import get_db
from ..models.user import User
from ..models.case import Case
from ..models.audit_log import AuditLog
from ..middleware.auth import require_role

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/cases")
async def list_all_cases(
    status: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("clerk", "admin")),
):
    query = select(Case).order_by(Case.created_at.desc())
    if status:
        query = query.where(Case.status == status)
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    cases = list(result.scalars().all())

    count_query = select(func.count(Case.id))
    if status:
        count_query = count_query.where(Case.status == status)
    total = (await db.execute(count_query)).scalar()

    return {"cases": cases, "total": total, "limit": limit, "offset": offset}


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
    by_status = {}
    result = await db.execute(
        select(Case.status, func.count(Case.id)).group_by(Case.status)
    )
    for row in result.all():
        by_status[row[0]] = row[1]

    return {"total_cases": total_cases, "by_status": by_status}
