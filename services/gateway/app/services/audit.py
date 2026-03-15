"""Audit logging service - records every automated decision and override."""

from sqlalchemy.ext.asyncio import AsyncSession
from ..models.audit_log import AuditLog


async def log_action(
    db: AsyncSession,
    action: str,
    user_id: str | None = None,
    case_id: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        case_id=case_id,
        action=action,
        details=details or {},
        ip_address=ip_address,
    )
    db.add(entry)
    await db.commit()
    return entry
