import asyncio
import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings

logger = logging.getLogger(__name__)

engine = create_async_engine(get_settings().database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


def _run_alembic_upgrade_sync(sync_url: str, alembic_ini_path: str) -> None:
    """Run alembic upgrade head synchronously. Called from a thread."""
    from alembic.config import Config
    from alembic import command

    cfg = Config(alembic_ini_path)
    cfg.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(cfg, "head")


async def init_db() -> None:
    """Bring the database schema up to the latest alembic revision.

    Replaces the old Base.metadata.create_all() so schema changes are
    versioned, reversible, and deterministic across environments.
    """
    settings = get_settings()

    # alembic uses sync drivers; convert the async URL.
    sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")

    alembic_ini_path = os.environ.get("ALEMBIC_INI_PATH", "/app/alembic.ini")
    if not os.path.exists(alembic_ini_path):
        raise RuntimeError(f"alembic config not found at {alembic_ini_path}")

    logger.info("Running alembic upgrade head (config: %s)", alembic_ini_path)
    await asyncio.to_thread(_run_alembic_upgrade_sync, sync_url, alembic_ini_path)
    logger.info("Schema up-to-date at alembic head")
