"""Model + service version metadata for AI decision reproducibility.

Every AI service (OCR, face, registry) returns a small `model_info`
dict alongside its primary payload. The orchestrator persists those
into the audit log + the Case row, so months later we can answer
"which model version produced this decision" — the load-bearing
question for any audited / regulated AI deployment.

The metadata captures three layers:
  1. service_version   — our code revision (git SHA at build time)
  2. provider_version  — the upstream model identifier (e.g. Google
                         Vision API revision the call hit)
  3. config_snapshot   — the configurable knobs that affected this
                         decision (thresholds, weights)

Combine those with the input hash (SHA-256 of the document bytes,
stored on the Document row) and the audit log trail and a decision
becomes fully reproducible: same image + same model + same config
=> same result.

Service git SHA is read from the GIT_SHA env var, set at container
build time. Falls back to "unknown" in dev to keep things working
when running outside Docker.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any


def get_service_version() -> str:
    """Container-build git SHA, or 'dev' for local runs."""
    return os.environ.get("GIT_SHA") or os.environ.get("DOCFLOW_VERSION") or "dev"


def hash_bytes(blob: bytes) -> str:
    """Stable SHA-256 hex digest of an arbitrary blob — used for image
    hashes so a decision can be replayed against the original input
    even if the file moves on disk."""
    return hashlib.sha256(blob).hexdigest()


def hash_file(path: str) -> str | None:
    """SHA-256 of a file's contents, or None if the file isn't readable."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, FileNotFoundError):
        return None


def build_model_info(
    *,
    service_name: str,
    provider: str,
    provider_version: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Standardised provenance dict every AI service includes in its
    response. Use this rather than rolling your own structure so the
    orchestrator can persist it consistently across services.

    Example:
        return {
            "extracted_fields": {...},
            ...,
            "model_info": build_model_info(
                service_name="ocr",
                provider="google-cloud-vision" if not mock else "mock",
                provider_version="v1" if not mock else "mock-v1",
                config={"min_confidence": settings.min_confidence_threshold,
                        "blur_threshold": settings.blur_threshold},
            ),
        }
    """
    return {
        "service_name": service_name,
        "service_version": get_service_version(),
        "provider": provider,
        "provider_version": provider_version,
        "config": config or {},
    }
