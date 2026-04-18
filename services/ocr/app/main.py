import logging
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from .routers import ocr
from . import metrics  # noqa: F401 — registers Prometheus collectors

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="DocFlow - OCR Service", version="0.1.0")

Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=["/health", "/metrics"],
).instrument(app).expose(app, endpoint="/metrics")

app.include_router(ocr.router)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "ocr"}
