"""Lazy singleton clients for external AI APIs.

Avoids creating a new client on every request (which is slow, re-parses
credentials, and allocates a fresh gRPC channel each time).
"""

import os
import logging
from functools import lru_cache

from google.cloud import vision
from google.oauth2 import service_account

from .config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_vision_client() -> vision.ImageAnnotatorClient:
    """Return a process-wide Google Cloud Vision client.

    Loads service-account credentials from the configured JSON file.
    Subsequent calls return the cached client.
    """
    settings = get_settings()
    cred_path = settings.google_credentials_path

    if not os.path.exists(cred_path):
        logger.warning(
            "Google Vision credentials file not found at %s — client will "
            "fall back to ADC (env var / default service account).",
            cred_path,
        )
        return vision.ImageAnnotatorClient()

    credentials = service_account.Credentials.from_service_account_file(cred_path)
    return vision.ImageAnnotatorClient(credentials=credentials)
