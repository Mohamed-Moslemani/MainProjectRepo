"""Idempotency helper for state-changing POST endpoints.

Wraps the (user_id, key, route) lookup-and-cache pattern in one
async helper so route handlers stay readable.

Usage:
    from .services.idempotency import idempotent_response

    cached = await idempotent_response(db, user.id, request, route='cases.submit')
    if cached:
        return cached  # FastAPI serialises the JSONResponse as-is

    # ... do the actual work ...

    return await store_idempotent_response(
        db, user.id, key, route='cases.submit', body={'message': '...'}
    )

The key is read from the `Idempotency-Key` request header (industry
convention; matches Stripe's own SDK).
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.idempotency import IdempotencyKey


HEADER = "Idempotency-Key"


def get_key(request: Request) -> str | None:
    return request.headers.get(HEADER)


async def idempotent_response(
    db: AsyncSession,
    user_id: str,
    request: Request,
    *,
    route: str,
) -> JSONResponse | None:
    """Look up a cached response. Returns None if no key or no match."""
    key = get_key(request)
    if not key:
        return None
    result = await db.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.key == key,
            IdempotencyKey.route == route,
        ),
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return JSONResponse(content=row.response_json, status_code=row.status_code)


async def store_idempotent_response(
    db: AsyncSession,
    user_id: str,
    request: Request,
    *,
    route: str,
    body: Any,
    status_code: int = 200,
) -> JSONResponse:
    """Persist the response so a retry returns the same payload.

    Returns a JSONResponse the caller can return directly. If two
    concurrent requests race the insert, the loser swallows the
    IntegrityError and reads the winner's row instead — same
    contract from the client's perspective.
    """
    key = get_key(request)
    response = JSONResponse(content=body, status_code=status_code)
    if not key:
        return response

    row = IdempotencyKey(
        user_id=user_id,
        key=key,
        route=route,
        status_code=status_code,
        response_json=body if isinstance(body, dict) else {"data": body},
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent retry won the race — read the winner's response.
        await db.rollback()
        cached = await db.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.user_id == user_id,
                IdempotencyKey.key == key,
                IdempotencyKey.route == route,
            ),
        )
        winner = cached.scalar_one_or_none()
        if winner:
            return JSONResponse(
                content=winner.response_json,
                status_code=winner.status_code,
            )
    return response
