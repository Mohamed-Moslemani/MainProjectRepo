"""Registry service configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://registry:registry@registry_db:5432/registry"

    # Matching thresholds
    exact_match_threshold: float = 0.92   # confidence >= this → exact_match
    partial_match_threshold: float = 0.55  # >= this but below exact → partial_match
    # Below partial → no_match

    # Auto-seed the registry on startup when the citizens table is empty.
    # Production would of course never do this.
    auto_seed: bool = True
    seed_file_path: str = "/app/seed/citizens.json"

    model_config = {"env_prefix": "REGISTRY_", "env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
