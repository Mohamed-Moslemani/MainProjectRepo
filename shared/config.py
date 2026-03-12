"""Shared configuration utilities."""
import os
from functools import lru_cache
from pathlib import Path


def load_env_file(path: str | None = None):
    """Load variables from a .env file into os.environ.

    Skips blank lines and comments. Does not override variables
    that are already set in the environment (e.g. by Docker).
    """
    if path is None:
        root = Path(__file__).resolve().parent.parent
        for name in (".env.dev", ".env"):
            candidate = root / name
            if candidate.exists():
                path = str(candidate)
                break

    if path is None or not os.path.isfile(path):
        return

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key not in os.environ:
                os.environ[key] = value


def get_env(key: str, default: str | None = None, required: bool = False) -> str:
    """Read an environment variable with an optional default."""
    value = os.getenv(key, default)
    if required and value is None:
        raise ValueError(f"Required environment variable {key} is not set")
    return value
