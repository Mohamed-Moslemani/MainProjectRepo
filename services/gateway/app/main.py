import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import init_db
from .middleware.rate_limit import init_redis, close_redis
from .routers import auth, cases, payments, admin

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting DocFlow Gateway...")
    await init_db()
    logger.info("Database initialized")
    await init_redis()
    logger.info("Redis connected")
    yield
    await close_redis()
    logger.info("Shutting down DocFlow Gateway...")


app = FastAPI(
    title="DocFlow Lebanon - API Gateway",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router)
app.include_router(cases.router)
app.include_router(payments.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "gateway"}
