"""Shared request-ID middleware + outbound propagation.

A request enters the gateway, gets tagged with an `X-Request-ID`
header (preserved if the client supplied one, generated as a uuid4
otherwise), and that ID is written into a `ContextVar` so every log
record emitted during the request can carry it. Outbound calls to the
OCR, face, and registry services pass the same ID along in their own
`X-Request-ID` header — those services install the same middleware,
so a single ID threads end-to-end through gateway → ocr → face →
registry → back to gateway.

How to use in each service's main.py:

    from shared.request_id import RequestIDMiddleware, install_logging_filter

    install_logging_filter()
    app.add_middleware(RequestIDMiddleware)

How to use when calling other services (httpx):

    from shared.request_id import propagate_headers

    async with httpx.AsyncClient(headers=propagate_headers()) as client:
        await client.post(...)

The contextvar reads None when there's no active request (e.g. during
startup), so the helper falls back to a `-` placeholder rather than
raising. That keeps startup logs readable.
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


HEADER_NAME = "X-Request-ID"

# `default=None` lets us distinguish "no active request" from "request
# with empty ID" (which can't happen — the middleware always sets one).
_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str:
    """Current request's ID, or '-' if called outside a request scope."""
    return _request_id_var.get() or "-"


def set_request_id(value: str) -> None:
    _request_id_var.set(value)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Read or generate X-Request-ID; expose via contextvar; echo on response."""

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(HEADER_NAME)
        rid = incoming or uuid.uuid4().hex
        token = _request_id_var.set(rid)
        try:
            response: Response = await call_next(request)
        finally:
            _request_id_var.reset(token)
        response.headers[HEADER_NAME] = rid
        return response


class RequestIDLogFilter(logging.Filter):
    """Stamp every log record with the active request_id.

    Attached to handlers (not just to a logger) so records that flow
    through children of the root logger — such as alembic's loggers —
    still get the attribute before the formatter touches them.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()
        return True


def install_logging_filter(level: int = logging.INFO) -> None:
    """Wire the request-ID filter and a request-ID-aware formatter onto
    every handler attached to the root logger.

    Idempotent — safe to call from each service's startup hook. The
    filter is attached to handlers (not to the root logger itself)
    because handler-level filters run for *every* record that reaches
    a handler, including records emitted by third-party loggers like
    alembic's, which would otherwise hit a "%(request_id)s — no such
    attribute" formatting failure.
    """
    fmt = "%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s"
    formatter = logging.Formatter(fmt)
    root = logging.getLogger()
    root.setLevel(level)

    rid_filter = RequestIDLogFilter()
    for handler in root.handlers:
        handler.setFormatter(formatter)
        # Don't double-attach if install_logging_filter is called twice.
        if not any(isinstance(f, RequestIDLogFilter) for f in handler.filters):
            handler.addFilter(rid_filter)


def propagate_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Headers to attach to outbound httpx calls so the same request ID
    threads through downstream services."""
    headers = {HEADER_NAME: get_request_id()}
    if extra:
        headers.update(extra)
    return headers
