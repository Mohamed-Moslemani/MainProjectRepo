"""Langfuse integration for the gateway service.

Mirrors services/ocr/app/services/langfuse_client.py — same API,
intentionally NOT shared via /shared/ so each service can evolve its
schema independently. The OCR copy emits LLM generations under
per-document traces; this gateway copy emits CASE-LEVEL traces with:

  - Spans for non-LLM decisions (cross-doc check, spoof, reconciliation,
    risk scoring) so a Langfuse user can replay an entire pipeline run
    in one place.
  - Scores for evaluation feedback:
      * `recon_integrity`         — field match rate vs declared
      * `face_similarity`         — Rekognition CompareFaces output
      * `liveness_passed`         — boolean
      * `risk_score`              — final risk
      * `decision`                — categorical (auto_approve / manual_review / reject / pending_mukhtar)
      * `mukhtar_decision`        — emitted later when the mukhtar acts;
                                    treated as ground-truth label vs
                                    the AI's auto-decision
      * `cross_doc_coherent`      — boolean

Why the score schema matters: Langfuse aggregates these by name across
all traces. The product gets a free dashboard of "auto_approve rate
trend", "mukhtar disagreement rate", "median recon integrity" — all
out of the box, no custom analytics.

Fail-OPEN on every error. Observability MUST NOT block the pipeline.
"""

from __future__ import annotations

import logging
import os
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_client_lock = Lock()
_client: Any = None
_client_attempted = False


def _is_enabled() -> bool:
    raw = (os.getenv("LANGFUSE_ENABLED") or "").strip().lower()
    if raw in ("0", "false", "no"):
        return False
    pk = os.getenv("LANGFUSE_PUBLIC_KEY") or ""
    sk = os.getenv("LANGFUSE_SECRET_KEY") or ""
    return bool(pk.strip() and sk.strip())


def get_client() -> Any | None:
    global _client, _client_attempted
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None or _client_attempted:
            return _client
        _client_attempted = True
        if not _is_enabled():
            logger.info("langfuse(gateway): disabled (no keys / explicit off)")
            return None
        try:
            from langfuse import Langfuse
        except ImportError:
            logger.info("langfuse(gateway): package not installed")
            return None
        try:
            host = (
                os.getenv("LANGFUSE_HOST")
                or os.getenv("LANGFUSE_BASE_URL")
                or "https://cloud.langfuse.com"
            )
            client = Langfuse(
                public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
                secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                host=host,
                max_retries=2,
                threads=1,
                timeout=10,
            )
            _client = client
            logger.info("langfuse(gateway): initialised against host=%s", host)
            return client
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse(gateway): init failed: %s", exc)
            return None


def shutdown() -> None:
    client = _client
    if client is None:
        return
    try:
        client.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("langfuse(gateway): flush failed: %s", exc)


def start_trace(
    name: str,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: dict | None = None,
    tags: list[str] | None = None,
) -> Any | None:
    client = get_client()
    if client is None:
        return None
    try:
        return client.trace(
            name=name,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata or {},
            tags=tags or [],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("langfuse(gateway): trace(%s) failed: %s", name, exc)
        return None


def log_span(
    trace_handle: Any | None,
    *,
    name: str,
    input: Any | None = None,
    output: Any | None = None,
    metadata: dict | None = None,
    level: str = "DEFAULT",
) -> None:
    if trace_handle is None:
        return
    try:
        span = trace_handle.span(
            name=name,
            input=input,
            output=output,
            metadata=metadata or {},
            level=level,
        )
        try:
            span.end()
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("langfuse(gateway): log_span(%s) failed: %s", name, exc)


def log_score(
    trace_handle: Any | None = None,
    *,
    name: str,
    value: float | str,
    trace_id: str | None = None,
    comment: str | None = None,
    data_type: str = "NUMERIC",
) -> None:
    """Attach a score to a trace. Either pass `trace_handle` (preferred,
    when the trace is in scope) OR `trace_id` (string, when scoring
    after the trace handle is gone — e.g. mukhtar feedback hours later).
    """
    try:
        if trace_handle is not None and hasattr(trace_handle, "score"):
            trace_handle.score(name=name, value=value, comment=comment, data_type=data_type)
            return
        client = get_client()
        if client is None:
            return
        tid = trace_id or (
            getattr(trace_handle, "id", None) or getattr(trace_handle, "trace_id", None)
            if trace_handle is not None else None
        )
        if not tid:
            return
        client.score(
            trace_id=tid,
            name=name,
            value=value,
            comment=comment,
            data_type=data_type,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("langfuse(gateway): log_score(%s) failed: %s", name, exc)
