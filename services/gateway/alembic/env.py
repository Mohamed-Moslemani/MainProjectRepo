import os
import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# ---------------------------------------------------------------------------
# Make the gateway app importable
# ---------------------------------------------------------------------------
gateway_root = Path(__file__).resolve().parent.parent          # services/gateway
project_root = gateway_root.parent.parent                      # finalproject
sys.path.insert(0, str(gateway_root))
sys.path.insert(0, str(project_root))

# Import Base without triggering the async engine creation in app.db.
# We import DeclarativeBase directly and then import all models so they
# register on Base.metadata.
from sqlalchemy.orm import DeclarativeBase


# Re-create the same Base class used by app.db so models attach to it.
# We need to import from the actual module so the models' metadata is shared.
# Patch: temporarily mock the engine creation to avoid asyncpg import.
import unittest.mock as mock

with mock.patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=None), \
     mock.patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=None):
    from app.db import Base                    # noqa: E402
    from app.models import *                   # noqa: E402, F401, F403

# ---------------------------------------------------------------------------
# Alembic Config
# ---------------------------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Allow overriding the DB URL via environment variable
db_url = os.environ.get("ALEMBIC_DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()