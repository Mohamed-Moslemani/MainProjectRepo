"""Lazy singleton boto3 clients.

boto3 clients are thread-safe once constructed. Avoid creating a new
client on every request — each constructor re-parses credentials,
re-loads service data, and allocates a fresh connection pool.
"""

import logging
from functools import lru_cache

import boto3

from .config import get_settings

logger = logging.getLogger(__name__)


def _kwargs_from_settings(settings) -> dict:
    """Build boto3 client kwargs. Falls back to default credential chain
    (env vars, ~/.aws/credentials, IAM role) if keys aren't set."""
    kwargs = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return kwargs


@lru_cache(maxsize=1)
def get_rekognition_client():
    settings = get_settings()
    return boto3.client("rekognition", **_kwargs_from_settings(settings))


@lru_cache(maxsize=1)
def get_sts_client():
    settings = get_settings()
    return boto3.client("sts", **_kwargs_from_settings(settings))
