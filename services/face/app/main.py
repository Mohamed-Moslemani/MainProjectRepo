import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from shared.request_id import RequestIDMiddleware, install_logging_filter
from shared.telemetry import install_telemetry

from .config import get_settings
from .routers import face, liveness
from . import metrics  # noqa: F401 — registers Prometheus collectors

logging.basicConfig(level=logging.INFO)
install_logging_filter()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.mock_mode:
        logger.info("FACE_MOCK_MODE is ON — no AWS Rekognition calls")
    else:
        if not settings.aws_access_key_id or not settings.aws_secret_access_key:
            logger.warning(
                "AWS credentials NOT configured — face service will 500 on real calls "
                "(set FACE_AWS_ACCESS_KEY_ID / FACE_AWS_SECRET_ACCESS_KEY)"
            )
        else:
            logger.info("AWS credentials set, region=%s", settings.aws_region)
    yield


app = FastAPI(title="DocFlow - Face Verification Service", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)
install_telemetry(service_name="docflow-face", app=app)

Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=["/health", "/health/ready", "/metrics"],
).instrument(app).expose(app, endpoint="/metrics")

app.include_router(face.router)
app.include_router(liveness.router)


@app.get("/health")
async def health():
    """Liveness — the process is running."""
    return {"status": "healthy", "service": "face"}


@app.get("/health/ready")
async def ready():
    """Readiness — the service can actually reach AWS Rekognition.

    In mock mode, short-circuits to ready.
    In live mode, verifies AWS credentials are set AND Rekognition
    responds to a lightweight list_collections() call.
    """
    settings = get_settings()

    if settings.mock_mode:
        return {"status": "ready", "mode": "mock", "checks": {"mock_mode": True}}

    checks: dict = {}

    if not settings.aws_access_key_id or not settings.aws_secret_access_key:
        checks["aws_credentials"] = {"ok": False, "error": "access_key or secret_key not set"}
        return JSONResponse(status_code=503, content={"status": "not_ready", "mode": "live", "checks": checks})

    checks["aws_credentials"] = {"ok": True, "region": settings.aws_region}

    try:
        from .clients import get_rekognition_client
        client = get_rekognition_client()
        await asyncio.to_thread(client.list_collections, MaxResults=1)
        checks["rekognition"] = {"ok": True}
    except Exception as e:
        checks["rekognition"] = {"ok": False, "error": str(e)[:200]}
        return JSONResponse(status_code=503, content={"status": "not_ready", "mode": "live", "checks": checks})

    return {"status": "ready", "mode": "live", "checks": checks}
