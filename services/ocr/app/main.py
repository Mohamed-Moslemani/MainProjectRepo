import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from shared.request_id import RequestIDMiddleware, install_logging_filter
from shared.telemetry import install_telemetry

from .config import get_settings
from .routers import ocr
from . import metrics  # noqa: F401 — registers Prometheus collectors
from .services import langfuse_client

logging.basicConfig(level=logging.INFO)
install_logging_filter()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.mock_mode:
        logger.info("OCR_MOCK_MODE is ON — returning fixtures, no Google Vision calls")
    else:
        if not os.path.exists(settings.google_credentials_path):
            logger.warning(
                "Google Vision credentials NOT found at %s — /process will 500 on first call",
                settings.google_credentials_path,
            )
        else:
            logger.info("Google Vision credentials detected at %s", settings.google_credentials_path)
    # Eagerly init Langfuse so the first /process request doesn't pay
    # the SDK handshake. No-op when LANGFUSE_PUBLIC_KEY isn't set.
    langfuse_client.get_client()
    yield
    # Flush any pending Langfuse events on shutdown so we don't drop
    # the last few traces when the container is rolled.
    langfuse_client.shutdown()


app = FastAPI(title="DocFlow - OCR Service", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)
install_telemetry(service_name="docflow-ocr", app=app)

Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=["/health", "/health/ready", "/metrics"],
).instrument(app).expose(app, endpoint="/metrics")

app.include_router(ocr.router)


@app.get("/health")
async def health():
    """Liveness — the process is running."""
    return {"status": "healthy", "service": "ocr"}


@app.get("/health/ready")
async def ready():
    """Readiness — the service can actually serve OCR requests.

    In mock mode, short-circuits to ready (no upstream to check).
    In live mode, verifies the Google Vision service-account JSON loads.
    """
    settings = get_settings()

    if settings.mock_mode:
        return {"status": "ready", "mode": "mock", "checks": {"mock_mode": True}}

    checks: dict = {}
    if not os.path.exists(settings.google_credentials_path):
        checks["google_credentials"] = {
            "ok": False,
            "error": f"credentials file not found at {settings.google_credentials_path}",
        }
        return JSONResponse(status_code=503, content={"status": "not_ready", "mode": "live", "checks": checks})

    try:
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(settings.google_credentials_path)
        checks["google_credentials"] = {
            "ok": True,
            "project_id": getattr(creds, "project_id", None),
            "client_email": getattr(creds, "service_account_email", None),
        }
    except Exception as e:
        checks["google_credentials"] = {"ok": False, "error": str(e)[:200]}
        return JSONResponse(status_code=503, content={"status": "not_ready", "mode": "live", "checks": checks})

    return {"status": "ready", "mode": "live", "checks": checks}
