"""Redis-backed sliding-window rate limiter.

Keys by both client IP (prevents brute force from one source) and
account email (prevents password spraying across IPs).
Works correctly across multiple workers/containers via shared Redis.
"""

import time
import logging
import math

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from ..config import get_settings
from ..metrics import RATE_LIMIT_HITS, AUTH_LOGINS

logger = logging.getLogger(__name__)

_redis: Redis | None = None


async def init_redis():
    global _redis
    settings = get_settings()
    _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    await _redis.ping()
    logger.info("Redis rate limiter connected")


async def close_redis():
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def _get_client_ip(request: Request) -> str:
    """Extract real client IP, handling X-Forwarded-For from reverse proxies.

    Only trusts the last entry in X-Forwarded-For (set by the nearest
    trusted proxy). Falls back to direct connection IP.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Last IP is the one added by our trusted reverse proxy
        ips = [ip.strip() for ip in forwarded.split(",")]
        return ips[-1]
    return request.client.host if request.client else "unknown"


async def _check_rate_limit(key: str, max_requests: int, window: int = 60) -> tuple[bool, int]:
    """Sliding window rate limit check using Redis sorted sets.

    Returns (allowed: bool, retry_after_seconds: int).
    """
    if not _redis:
        logger.warning("Redis not available, skipping rate limit")
        return True, 0

    now = time.time()
    window_start = now - window

    pipe = _redis.pipeline()
    # Remove entries older than the window
    pipe.zremrangebyscore(key, 0, window_start)
    # Count current entries in window
    pipe.zcard(key)
    # Add current request
    pipe.zadd(key, {f"{now}": now})
    # Set TTL so keys auto-expire
    pipe.expire(key, window + 1)
    results = await pipe.execute()

    current_count = results[1]

    if current_count >= max_requests:
        # Find the oldest entry to calculate retry-after
        oldest = await _redis.zrange(key, 0, 0, withscores=True)
        if oldest:
            retry_after = math.ceil(window - (now - oldest[0][1]))
            retry_after = max(retry_after, 1)
        else:
            retry_after = window
        return False, retry_after

    return True, 0


async def rate_limit_login(request: Request):
    """Rate limit by IP for login/refresh endpoints.

    Applied as a FastAPI dependency. Email-based limiting is handled
    separately via check_email_rate_limit() after parsing the body.
    """
    settings = get_settings()
    ip = _get_client_ip(request)
    key = f"rl:login:ip:{ip}"

    allowed, retry_after = await _check_rate_limit(
        key, settings.rate_limit_login_per_minute
    )
    if not allowed:
        RATE_LIMIT_HITS.labels(endpoint="login").inc()
        AUTH_LOGINS.labels(status="rate_limited").inc()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts from this IP. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


async def check_email_rate_limit(email: str):
    """Rate limit by email to prevent password spraying across IPs."""
    settings = get_settings()
    key = f"rl:login:email:{email.lower()}"

    allowed, retry_after = await _check_rate_limit(
        key, settings.rate_limit_login_per_email_per_minute
    )
    if not allowed:
        RATE_LIMIT_HITS.labels(endpoint="login_email").inc()
        AUTH_LOGINS.labels(status="rate_limited").inc()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts for this account. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


async def rate_limit_reset(request: Request):
    """Rate limit password reset requests by IP (hourly window)."""
    settings = get_settings()
    ip = _get_client_ip(request)
    key = f"rl:reset:ip:{ip}"

    allowed, retry_after = await _check_rate_limit(
        key, settings.rate_limit_reset_per_ip_per_hour, window=3600
    )
    if not allowed:
        RATE_LIMIT_HITS.labels(endpoint="reset").inc()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password reset requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


async def rate_limit_verification(request: Request):
    """Rate limit email verification/resend requests by IP (hourly window)."""
    settings = get_settings()
    ip = _get_client_ip(request)
    key = f"rl:verify:ip:{ip}"

    allowed, retry_after = await _check_rate_limit(
        key, settings.rate_limit_verification_per_ip_per_hour, window=3600
    )
    if not allowed:
        RATE_LIMIT_HITS.labels(endpoint="verification").inc()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many verification requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )
