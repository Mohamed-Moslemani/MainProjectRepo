"""Email outbox sweep — cron entry point.

Picks pending email_outbox rows whose next_attempt_at has passed and
enqueues an Arq delivery job for each. Recommended cadence: every
60s. Idempotent: each row's next_attempt_at advances on each attempt
so a sweep that fires twice in the same minute won't double-enqueue.
"""
from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("docflow.sweep_email_outbox")


async def _run() -> int:
    from app.db import async_session
    from app.queue import enqueue_email_outbox
    from app.services.email_outbox import sweep_pending

    async with async_session() as db:
        ids = await sweep_pending(db, limit=200)
    if not ids:
        logger.info("no pending outbox rows ready")
        return 0

    for outbox_id in ids:
        try:
            await enqueue_email_outbox(outbox_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("failed to enqueue outbox %s: %s", outbox_id, exc)

    logger.info("enqueued %d outbox deliveries", len(ids))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
