"""Durable background jobs via Arq (Redis-backed asyncio worker).

Why this exists: FastAPI's `BackgroundTasks` runs in-process. If the
gateway crashes mid-pipeline (uvicorn worker OOM, deploy rollover,
container restart), every case currently being processed is lost
without anybody noticing — the case stays at SUBMITTED forever and
the citizen has no signal anything went wrong.

Arq is the lightweight async equivalent of Celery for asyncio
codebases. It pushes job specs to Redis, a separate worker process
picks them up, retries on failure with exponential backoff, and
reports outcome back to a Redis result key. If the worker dies
mid-job the spec is still in Redis and another worker picks it up
within seconds.

Architecture:

  FastAPI route (uvicorn)              Arq worker (separate container)
  ─────────────────────                ──────────────────────────────
       enqueue_job ───── Redis ─────►  process_case_job(...)
                                       │
                                       ├─ runs orchestrator.process_case
                                       ├─ retries on transient failure
                                       └─ logs + audit trail

Job functions live below. The gateway routes use `enqueue_job` from
this module; the worker entry point is `WorkerSettings` (consumed by
`arq services.gateway.app.queue:WorkerSettings`).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from arq.connections import RedisSettings, create_pool
from sqlalchemy import select

from .config import get_settings as get_app_settings

logger = logging.getLogger(__name__)


def _redis_settings() -> RedisSettings:
    """Parse the redis_url out of app config into Arq's RedisSettings.

    The gateway already uses redis db=0 for rate limiting; queue jobs
    go on db=2 so they never collide with rate-limit keys or the
    glitchtip celery queue (which is on db=1).
    """
    url = get_app_settings().redis_url  # e.g. redis://redis:6379/0
    # Carve out a dedicated DB number for queue traffic.
    if url.endswith("/0"):
        url = url[:-2] + "/2"
    elif "/" in url.split("://", 1)[1]:
        # Different db already — leave it alone.
        pass
    else:
        url = url.rstrip("/") + "/2"
    return RedisSettings.from_dsn(url)


# ── Job functions ─────────────────────────────────────────────────
#
# Every Arq job takes a `ctx` (worker context) as the first positional
# arg. ctx['redis'] is the live pool, ctx['job_try'] is the retry
# counter (1-indexed).

async def process_case_job(ctx: dict[str, Any], case_id: str) -> dict[str, Any]:
    """Run the orchestrator pipeline against a single case.

    Retried automatically by Arq on uncaught exception (max_tries set
    in WorkerSettings below). Each retry gets a fresh DB session so a
    half-committed transaction from the previous attempt doesn't bleed
    over.

    On terminal failure the orchestrator's own try/except already
    bounces the case to NEED_INFO with a "_pipeline" retake reason —
    Arq will surface the traceback to logs + Sentry/GlitchTip but the
    citizen-facing state is already correct.
    """
    from .db import async_session
    from .models.case import Case
    from .services.orchestrator import process_case

    job_try = ctx.get("job_try", 1)
    logger.info(
        "process_case_job start",
        extra={"case_id": case_id, "job_try": job_try},
    )

    async with async_session() as db:
        result = await db.execute(select(Case).where(Case.id == case_id))
        case = result.scalar_one_or_none()
        if not case:
            logger.warning("process_case_job: case not found", extra={"case_id": case_id})
            return {"status": "not_found", "case_id": case_id}
        outcome = await process_case(db, case)

    return {
        "status": "ok",
        "case_id": case_id,
        "routing": outcome.get("routing"),
        "job_try": job_try,
    }


async def send_email_outbox_job(ctx: dict[str, Any], outbox_id: str) -> dict[str, Any]:
    """Drain a single email_outbox row.

    The email-outbox pattern (see services/gateway/app/services/email_outbox.py)
    writes the email payload into Postgres in the *same transaction*
    that produced it (e.g. user_registered). A separate sweep enqueues
    one of these jobs per pending row, which actually attempts the
    SMTP delivery + marks the row sent / failed. Decouples "the user
    finished registration" from "we managed to talk to Gmail right now".
    """
    from .db import async_session
    from .services.email_outbox import deliver_outbox_entry

    async with async_session() as db:
        delivered = await deliver_outbox_entry(db, outbox_id)
    return {"status": "delivered" if delivered else "skipped", "outbox_id": outbox_id}


# ── Pool + enqueue helpers used by route handlers ─────────────────

_pool = None  # populated lazily in get_pool


async def get_pool():
    """Lazy-initialised Arq Redis pool, shared across requests.

    Created on first enqueue rather than at FastAPI startup so the
    gateway can boot even if Redis is briefly unreachable; tasks
    will start succeeding the moment Redis comes back.
    """
    global _pool
    if _pool is None:
        _pool = await create_pool(_redis_settings())
    return _pool


async def enqueue_process_case(case_id: str) -> str:
    """Enqueue a process_case_job for a freshly-submitted case.

    Returns the Arq job_id so the caller can persist it on the case
    row if it wants traceability.
    """
    pool = await get_pool()
    job = await pool.enqueue_job("process_case_job", case_id)
    return job.job_id if job else ""


async def enqueue_email_outbox(outbox_id: str) -> str:
    pool = await get_pool()
    job = await pool.enqueue_job("send_email_outbox_job", outbox_id)
    return job.job_id if job else ""


# ── Worker entry point ────────────────────────────────────────────
#
# `arq services.gateway.app.queue:WorkerSettings` runs the worker.
# In docker-compose this gets its own container; in K8s it's a
# separate Deployment (see k8s/base/gateway-worker/).

class WorkerSettings:
    """Arq worker configuration."""

    functions = [process_case_job, send_email_outbox_job]
    redis_settings = _redis_settings()

    # Retry behaviour: 4 tries with exponential backoff. Pipeline
    # transient failures (Google Vision blip, AWS rate limit) heal on
    # their own within a minute or two; persistent failures bubble up
    # as Sentry events after the final retry.
    max_tries = 4
    retry_jobs = True
    job_timeout = 180  # seconds — pipeline budget is 120s, headroom for face/registry.

    # Concurrency knob. With single-tenant Lebanese-citizen volume the
    # default of 10 simultaneous jobs is plenty; tune up via env if the
    # GDGS load profile changes.
    max_jobs = int(os.environ.get("ARQ_MAX_JOBS", "10"))

    @staticmethod
    async def on_startup(ctx: dict[str, Any]) -> None:
        # Install the same logging filter + telemetry the FastAPI
        # process uses so worker log lines carry request_ids and
        # land in Jaeger / GlitchTip with the right service tag.
        from shared.request_id import install_logging_filter
        from shared.telemetry import install_telemetry

        install_logging_filter()
        install_telemetry(service_name="docflow-gateway-worker")
        logger.info("Arq worker started")

    @staticmethod
    async def on_shutdown(ctx: dict[str, Any]) -> None:
        logger.info("Arq worker shutting down")
