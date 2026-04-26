"""Mukhtar SLA sweep — cron entry point.

Runs the gateway's sweep_mukhtar_sla() inside a fresh DB session and
exits. Designed to be invoked by a Kubernetes CronJob, host crontab,
or `docker compose run --rm gateway python scripts/sweep_mukhtar_sla.py`.

Recommended cadence: hourly. The function is idempotent so spurious
extra runs are harmless.

Optional: when --pushgateway URL is supplied, the summary is pushed
as Prometheus metrics so a Grafana panel can chart escalations over
time.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from app.db import async_session
from app.services.mukhtar_sla import sweep_mukhtar_sla


async def _run(pushgateway: str | None) -> int:
    async with async_session() as db:
        summary = await sweep_mukhtar_sla(db)

    print(f"sweep summary: {summary}")

    if pushgateway:
        body = (
            f"# TYPE docflow_mukhtar_sla_scanned gauge\n"
            f'docflow_mukhtar_sla_scanned {summary["scanned"]}\n'
            f"# TYPE docflow_mukhtar_sla_reassigned gauge\n"
            f'docflow_mukhtar_sla_reassigned {summary["reassigned"]}\n'
            f"# TYPE docflow_mukhtar_sla_escalated gauge\n"
            f'docflow_mukhtar_sla_escalated {summary["escalated"]}\n'
        )
        import urllib.request
        url = f"{pushgateway.rstrip('/')}/metrics/job/docflow-mukhtar-sla"
        req = urllib.request.Request(
            url, data=body.encode(), method="PUT",
            headers={"Content-Type": "text/plain"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"pushgateway: {resp.status}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pushgateway", default="")
    args = ap.parse_args()
    sys.exit(asyncio.run(_run(args.pushgateway or None)))
