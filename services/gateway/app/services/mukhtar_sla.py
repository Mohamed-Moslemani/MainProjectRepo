"""Mukhtar SLA enforcement.

A passport application that lands in PENDING_MUKHTAR will sit there
until the assigned mukhtar acts. In real life mukhtars are
part-time and citizens chase them in person; for an online-first
system we need a watchdog so cases don't hang forever silently.

Policy (configurable via env):
  - DOCFLOW_MUKHTAR_SLA_HOURS (default 72): a case in
    PENDING_MUKHTAR that hasn't been decided within this window is
    considered overdue.
  - On overdue: unassign the current mukhtar and re-route via
    _assign_mukhtar (the original auto-assignment logic), so a
    *different* mukhtar in the same district picks it up. If
    re-assignment also can't find anyone, mark the case for
    supervisor escalation by writing a `mukhtar_sla_escalated`
    audit log + leaving status_history breadcrumbs — the admin
    review queue will surface it.

This module exposes a single coroutine `sweep_mukhtar_sla(db)`. It's
designed to be cron-triggered (Kubernetes CronJob, host crontab,
or a simple asyncio.create_task loop in dev). Idempotent: a case
already escalated within the last hour is skipped so repeated cron
ticks don't spam re-assignments.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.case import Case
from .audit import log_action

logger = logging.getLogger(__name__)


def _sla_hours() -> int:
    raw = os.environ.get("DOCFLOW_MUKHTAR_SLA_HOURS", "72")
    try:
        return max(1, int(raw))
    except ValueError:
        return 72


def _last_pending_mukhtar_transition(case: Case) -> datetime | None:
    """Latest timestamp the case entered PENDING_MUKHTAR. We compare
    *that* against now, not created_at — a case that bounced through
    NEED_INFO and back shouldn't get punished for the original entry."""
    history = case.status_history or []
    for event in reversed(history):
        if event.get("status") == "pending_mukhtar":
            ts = event.get("timestamp")
            if not ts:
                continue
            try:
                # status_history timestamps are ISO-8601 with tz suffix;
                # tolerate the legacy 'Z' form too.
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
    return None


async def sweep_mukhtar_sla(db: AsyncSession) -> dict:
    """Find PENDING_MUKHTAR cases past the SLA, re-route or escalate.

    Returns a summary dict suitable for logging / Prometheus push:
      { "scanned": int, "reassigned": int, "escalated": int }
    """
    sla_hours = _sla_hours()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=sla_hours)

    result = await db.execute(
        select(Case).where(Case.status == "pending_mukhtar")
    )
    pending = list(result.scalars().all())

    summary = {"scanned": len(pending), "reassigned": 0, "escalated": 0}

    # Imported here to break the orchestrator <-> mukhtar_sla cycle
    # that would otherwise form at import time.
    from .orchestrator import _assign_mukhtar

    for case in pending:
        entered_at = _last_pending_mukhtar_transition(case)
        if entered_at is None or entered_at > cutoff:
            continue   # not overdue (yet)

        prior_mukhtar = case.mukhtar_id
        case.mukhtar_id = None
        reassigned = await _assign_mukhtar(db, case)
        now = datetime.now(timezone.utc)

        if reassigned and case.mukhtar_id and case.mukhtar_id != prior_mukhtar:
            summary["reassigned"] += 1
            case.status_history = case.status_history + [{
                "status": "pending_mukhtar",
                "message": (
                    f"SLA overdue ({sla_hours}h) — reassigned from "
                    f"mukhtar {prior_mukhtar[:8] if prior_mukhtar else '?'}"
                    f" to {case.mukhtar_id[:8]}"
                ),
                "timestamp": now.isoformat(),
                "actor": "system:mukhtar-sla-sweep",
            }]
            await db.commit()
            await log_action(
                db, "mukhtar_sla_reassigned", case_id=case.id,
                details={
                    "previous_mukhtar_id": prior_mukhtar,
                    "new_mukhtar_id": case.mukhtar_id,
                    "sla_hours": sla_hours,
                    "entered_pending_at": entered_at.isoformat(),
                },
            )
        else:
            # Couldn't find another mukhtar — restore the original
            # assignment + escalate to supervisor for manual handling.
            case.mukhtar_id = prior_mukhtar
            summary["escalated"] += 1
            case.status_history = case.status_history + [{
                "status": "pending_mukhtar",
                "message": (
                    f"SLA overdue ({sla_hours}h) — no alternate mukhtar "
                    "available in jurisdiction; escalated to supervisor."
                ),
                "timestamp": now.isoformat(),
                "actor": "system:mukhtar-sla-sweep",
            }]
            await db.commit()
            await log_action(
                db, "mukhtar_sla_escalated", case_id=case.id,
                details={
                    "mukhtar_id": prior_mukhtar,
                    "sla_hours": sla_hours,
                    "entered_pending_at": entered_at.isoformat(),
                },
            )

    logger.info("mukhtar SLA sweep complete: %s", summary)
    return summary
