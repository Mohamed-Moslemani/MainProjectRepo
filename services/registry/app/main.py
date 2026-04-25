import json
import logging
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import select, func, text

from shared.request_id import RequestIDMiddleware, install_logging_filter

from .config import get_settings
from .db import init_db, async_session
from .routers import registry
from . import metrics  # noqa: F401
from .models.citizen import Citizen

logging.basicConfig(level=logging.INFO)
install_logging_filter()
logger = logging.getLogger(__name__)


async def _seed_if_empty() -> None:
    """If the citizens table is empty, load seed/citizens.json."""
    settings = get_settings()
    if not settings.auto_seed:
        return

    async with async_session() as session:
        count = (await session.execute(select(func.count(Citizen.id)))).scalar()
        if count and count > 0:
            logger.info("Registry already seeded (%d citizens) — skipping", count)
            return

        try:
            with open(settings.seed_file_path) as f:
                rows = json.load(f)
        except FileNotFoundError:
            logger.warning("Seed file missing at %s; registry starts empty", settings.seed_file_path)
            return

        for row in rows:
            dob = None
            if row.get("date_of_birth"):
                dob = date.fromisoformat(row["date_of_birth"])
            session.add(Citizen(
                full_name_en=row["full_name_en"],
                full_name_ar=row.get("full_name_ar"),
                father_name=row.get("father_name"),
                mother_name=row.get("mother_name"),
                date_of_birth=dob,
                place_of_birth=row.get("place_of_birth"),
                gender=row.get("gender"),
                registry_number=row["registry_number"],
                registry_place=row["registry_place"],
                municipality=row.get("municipality"),
                deceased=row.get("deceased", False),
                nationality=row.get("nationality", "Lebanese"),
            ))
        await session.commit()
        logger.info("Seeded civil registry with %d citizens from %s", len(rows), settings.seed_file_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting DocFlow Civil Registry Service...")
    await init_db()
    await _seed_if_empty()
    yield
    logger.info("Shutting down registry service")


app = FastAPI(title="DocFlow - Civil Registry Service", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)

Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=["/health", "/health/ready", "/metrics"],
).instrument(app).expose(app, endpoint="/metrics")

app.include_router(registry.router)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "registry"}


@app.get("/health/ready")
async def ready():
    """Readiness — DB is reachable AND has at least one seeded citizen."""
    checks: dict = {}
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
            citizen_count = (await session.execute(select(func.count(Citizen.id)))).scalar() or 0
        checks["db"] = {"ok": True, "citizens": citizen_count}
    except Exception as e:
        checks["db"] = {"ok": False, "error": str(e)[:200]}
        return JSONResponse(status_code=503, content={"status": "not_ready", "checks": checks})

    if checks["db"]["citizens"] == 0:
        checks["db"]["warning"] = "registry has no citizens — verifies will return no_match"

    return {"status": "ready", "checks": checks}
