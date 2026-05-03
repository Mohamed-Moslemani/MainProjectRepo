"""Sentry envelope tunnel.

Browser ad-blockers (uBlock Origin, Brave Shields, Privacy Badger,
DuckDuckGo, etc.) block any direct POST to `*.ingest.sentry.io`,
which silently drops error reports for ~30 % of real users.

This endpoint accepts a Sentry envelope from the SPA at a same-origin
URL and forwards it server-side to the real Sentry ingest. Same-origin
requests aren't on any blocklist, so reports get through reliably.

Reference: https://docs.sentry.io/platforms/javascript/troubleshooting/#dealing-with-ad-blockers

Security:
  - Only DSNs whose host matches one of our pre-approved Sentry ingest
    hosts (extracted from SENTRY_DSN / VITE_SENTRY_DSN env vars) are
    forwarded. Otherwise our backend would be a free open relay for
    spammers to dump events into arbitrary Sentry projects.
  - No request body parsing beyond the first line — we read the
    envelope header to extract the DSN and forward the rest as bytes.
  - No auth required: unauthenticated browsers (login screen, public
    landing) also need to report client errors.
"""
from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sentry-tunnel", tags=["sentry-tunnel"])


def _allowed_hosts_and_projects() -> set[tuple[str, str]]:
    """Return the {(host, project_id)} pairs we'll forward to.

    Built once per request from env so updates take effect without a
    restart. Both backend and frontend DSNs are allowed because the
    same tunnel may serve both (the SPA tunnels its own events, and
    server-side errors could in principle be tunneled too).
    """
    pairs: set[tuple[str, str]] = set()
    for name in ("VITE_SENTRY_DSN", "SENTRY_DSN"):
        dsn = os.environ.get(name, "").strip()
        if not dsn:
            continue
        try:
            parsed = urlparse(dsn)
            host = parsed.hostname or ""
            # DSN path is "/<project_id>" — strip the leading slash.
            project_id = parsed.path.lstrip("/").split("/")[0]
            if host and project_id:
                pairs.add((host.lower(), project_id))
        except Exception:
            logger.warning("Could not parse %s for tunnel allowlist", name)
    return pairs


@router.post("")
async def tunnel(request: Request) -> Response:
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty envelope")

    # The envelope is newline-delimited. The first line is a JSON
    # header that *may* contain a `dsn` field. We use it to verify the
    # request is destined for one of our own Sentry projects, not to
    # rewrite anything.
    first_newline = body.find(b"\n")
    if first_newline == -1:
        raise HTTPException(status_code=400, detail="malformed envelope")

    header_line = body[:first_newline]
    import json
    try:
        header = json.loads(header_line)
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid envelope header")

    dsn = header.get("dsn")
    if not dsn:
        raise HTTPException(status_code=400, detail="envelope header missing DSN")

    parsed = urlparse(dsn)
    host = (parsed.hostname or "").lower()
    project_id = parsed.path.lstrip("/").split("/")[0]
    if not host or not project_id:
        raise HTTPException(status_code=400, detail="malformed DSN")

    allowed = _allowed_hosts_and_projects()
    if (host, project_id) not in allowed:
        # Don't echo what was rejected — leak nothing about which DSNs
        # we accept. Logged at warning so abuse stands out.
        logger.warning(
            "Rejected sentry-tunnel envelope for unknown DSN host=%s project=%s",
            host, project_id,
        )
        raise HTTPException(status_code=403, detail="DSN not allowed")

    upstream = f"https://{host}/api/{project_id}/envelope/"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                upstream,
                content=body,
                headers={"Content-Type": "application/x-sentry-envelope"},
            )
        except httpx.HTTPError as exc:
            logger.warning("sentry-tunnel upstream POST failed: %s", exc)
            # 502 so the SDK retries with backoff rather than dropping.
            raise HTTPException(status_code=502, detail="sentry ingest unreachable")

    # Pass the upstream status code through so the SDK's retry logic
    # behaves the same as if it had talked to Sentry directly.
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )
