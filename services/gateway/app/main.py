import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from shared.request_id import RequestIDMiddleware, install_logging_filter
from shared.telemetry import install_telemetry

from .config import get_settings
from .db import init_db, async_session
from .middleware import rate_limit as rate_limit_mod
from .middleware.rate_limit import init_redis, close_redis
from .routers import auth, cases, payments, admin, liveness, mukhtar
from .routers import appointments as appointments_router
from .routers import reference as reference_router

logging.basicConfig(level=logging.INFO)
install_logging_filter()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting DocFlow Gateway...")
    await init_db()
    logger.info("Database initialized")
    await init_redis()
    logger.info("Redis connected")
    settings = get_settings()
    logger.info("OCR service URL: %s", settings.ocr_service_url)
    logger.info("Face service URL: %s", settings.face_service_url)
    yield
    await close_redis()
    logger.info("Shutting down DocFlow Gateway...")


app = FastAPI(
    title="DocFlow Lebanon - API Gateway",
    version="0.1.0",
    lifespan=lifespan,
)

# Prometheus auto-instrumentation (request count, latency, in-progress, response size)
Instrumentator(
    should_group_status_codes=False,
    should_group_untemplated=True,
    excluded_handlers=["/health", "/health/ready", "/metrics"],
).instrument(app).expose(app, endpoint="/metrics")

settings = get_settings()
app.add_middleware(RequestIDMiddleware)
install_telemetry(service_name="docflow-gateway", app=app)
# CORS: log resolved origins on startup so a misconfigured prod env
# (typo, missing scheme, accidental trailing-slash) shows up in logs
# instead of silently 503-ing every browser request. The previous
# behaviour ate the env var and produced an empty allow-list with no
# warning, which manifested as a fully working backend that the SPA
# couldn't talk to.
import logging as _log
_resolved_cors = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
if not _resolved_cors:
    _log.getLogger("app.main").warning(
        "CORS allow-list is EMPTY — every cross-origin browser request will be blocked. "
        "Check GATEWAY_CORS_ALLOWED_ORIGINS in the environment."
    )
else:
    _log.getLogger("app.main").info("CORS allow-list resolved to: %s", _resolved_cors)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_resolved_cors,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)

app.include_router(auth.router)
app.include_router(cases.router)
app.include_router(payments.router)
app.include_router(admin.router)
app.include_router(liveness.router)
app.include_router(mukhtar.router)
# Biometric-appointment booking + officer confirmation. Three
# routers since they live under three URL prefixes
# (/appointments, /admin/appointments, /cases/{id}/appointment).
app.include_router(appointments_router.router)
app.include_router(appointments_router.admin_router)
app.include_router(appointments_router.case_router)
# Static reference data (sects, centres, validity tiers, renewal
# reasons) so the React bundle doesn't have to redeclare them.
app.include_router(reference_router.router)


@app.get("/health")
async def health():
    """Liveness — the process is running."""
    return {"status": "healthy", "service": "gateway"}


@app.get("/health/ready")
async def ready():
    """Readiness — DB, Redis, and upstream AI services are all reachable."""
    settings = get_settings()
    checks: dict = {}
    overall_ok = True

    # Database
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        checks["db"] = {"ok": True}
    except Exception as e:
        checks["db"] = {"ok": False, "error": str(e)[:200]}
        overall_ok = False

    # Redis
    try:
        if rate_limit_mod._redis is None:
            raise RuntimeError("redis client not initialised")
        await rate_limit_mod._redis.ping()
        checks["redis"] = {"ok": True}
    except Exception as e:
        checks["redis"] = {"ok": False, "error": str(e)[:200]}
        overall_ok = False

    # Upstream AI services (liveness only — /health on each)
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, url in (("ocr", settings.ocr_service_url), ("face", settings.face_service_url)):
            try:
                r = await client.get(f"{url}/health")
                ok = r.status_code == 200
                checks[f"{name}_service"] = {"ok": ok, "status_code": r.status_code}
                if not ok:
                    overall_ok = False
            except Exception as e:
                checks[f"{name}_service"] = {"ok": False, "error": str(e)[:200]}
                overall_ok = False

    body = {"status": "ready" if overall_ok else "not_ready", "checks": checks}
    return JSONResponse(status_code=200 if overall_ok else 503, content=body)
