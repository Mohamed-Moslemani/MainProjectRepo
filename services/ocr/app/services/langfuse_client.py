"""Langfuse integration for the OCR service.

Centralises LLM observability + prompt management for every vision-LLM
call we make from this service:

  - `ai_extractor.extract_with_llm`  → OpenAI vision call, structured
    extraction.
  - `doc_classifier.classify`        → OpenAI vision call, doc-type +
    authenticity verdict.

Both call sites share the same shape: build messages, send to OpenAI,
parse JSON, return result + audit trace. The Langfuse wrapper here
adds a fourth concern — emit a `generation` observation under a
per-OCR-request `trace` so each model call is browsable, comparable,
and costable in Langfuse.

Config via env (set in .env.dev / .env.prod):
  LANGFUSE_PUBLIC_KEY   pk-lf-...
  LANGFUSE_SECRET_KEY   sk-lf-...
  LANGFUSE_HOST         https://cloud.langfuse.com  (default)
                        or http://langfuse-web:3000 for self-hosted
  LANGFUSE_ENABLED      "true"/"false" — explicit kill switch even
                        when keys are present (useful in CI).

Design notes:
  - Fail-OPEN on every Langfuse error. The OCR pipeline's correctness
    must not depend on the observability backend being reachable.
  - Image bytes are NEVER sent to Langfuse. We strip the base64 image
    payload from the message list before logging — the raw OCR text
    + extracted fields + model verdict are enough for debugging,
    and shipping camera frames to a third-party SaaS is not OK.
  - Prompt management uses `get_prompt(name, label="production")` with
    a Python-side fallback. If Langfuse is unreachable or the prompt
    doesn't exist there yet, we serve the hardcoded version. This
    means deployments without Langfuse keep working; deployments WITH
    Langfuse can iterate on prompts without code changes.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

# Public-facing prompt names. We register these in Langfuse so prompt
# editors don't need to dig through code to find string IDs. Keep in
# sync with the names used in get_prompt() calls.
# Prompt names use hyphens, not slashes — the Langfuse v2 SDK builds
# the API path as `/api/public/v2/prompts/{name}` and embedded slashes
# break the route resolver, returning a 404 HTML page.
PROMPT_NAME_FIELD_EXTRACTOR = "ocr-field-extractor"
PROMPT_NAME_DOC_CLASSIFIER = "ocr-doc-classifier"


# ── Lazy singleton ────────────────────────────────────────────────────────
# Imported at module top of doc_classifier + ai_extractor; we don't
# want module load to fail if Langfuse isn't installed or configured,
# and we don't want every request to re-instantiate the client.
_client_lock = Lock()
_client: Any = None
_client_attempted = False  # so we don't retry init on every call


def _is_enabled() -> bool:
    raw = (os.getenv("LANGFUSE_ENABLED") or "").strip().lower()
    if raw in ("0", "false", "no"):
        return False
    pk = os.getenv("LANGFUSE_PUBLIC_KEY") or ""
    sk = os.getenv("LANGFUSE_SECRET_KEY") or ""
    return bool(pk.strip() and sk.strip())


def get_client() -> Any | None:
    """Return a cached Langfuse client, or None if disabled / unavailable.

    Initialisation is best-effort: missing package, missing env, or
    auth failure all return None so callers can no-op cleanly.
    """
    global _client, _client_attempted
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None or _client_attempted:
            return _client
        _client_attempted = True
        if not _is_enabled():
            logger.info("langfuse: disabled (no keys / explicit off)")
            return None
        try:
            from langfuse import Langfuse
        except ImportError:
            logger.info("langfuse: package not installed, tracing disabled")
            return None
        try:
            # Accept either LANGFUSE_HOST (canonical, matches the SDK)
            # or LANGFUSE_BASE_URL (also widely used in Langfuse docs +
            # in some self-hosted compose templates) so a typo in either
            # spelling doesn't silently disable tracing.
            host = (
                os.getenv("LANGFUSE_HOST")
                or os.getenv("LANGFUSE_BASE_URL")
                or "https://cloud.langfuse.com"
            )
            client = Langfuse(
                public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
                secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                host=host,
                # Bound the SDK's worker queue so a stuck network
                # doesn't grow memory unboundedly. The SDK flushes in
                # the background; we don't need a large buffer.
                max_retries=2,
                threads=1,
                timeout=10,
            )
            _client = client
            logger.info("langfuse: initialised against host=%s", host)
            return client
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse: init failed: %s", exc)
            return None


def shutdown() -> None:
    """Flush pending Langfuse events. Call from FastAPI shutdown hook."""
    client = _client
    if client is None:
        return
    try:
        client.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("langfuse: flush failed: %s", exc)


# ── Prompt management ────────────────────────────────────────────────────
@dataclass
class ManagedPrompt:
    """A prompt fetched from Langfuse, or the local fallback.

    `text` is what the caller actually feeds to the model. `langfuse_obj`
    is the original Prompt object (used to link generation observations
    back to the prompt version, which is how Langfuse builds prompt
    eval reports). When we fall back to local, langfuse_obj is None.
    """

    text: str
    version: int
    source: str  # "langfuse" | "fallback"
    langfuse_obj: Any | None = None


def get_prompt(name: str, fallback: str, *, label: str = "production") -> ManagedPrompt:
    """Fetch a prompt from Langfuse, falling back to `fallback`.

    `label` selects which version: "production" (default), "latest", or
    a custom label. Editors in the Langfuse UI promote a draft to
    "production" to roll it out without touching code.

    Network errors return the fallback. Unknown prompts (404) also
    return the fallback so first-time deploys don't break before the
    seeder has run.
    """
    client = get_client()
    if client is None:
        return ManagedPrompt(text=fallback, version=0, source="fallback")
    try:
        p = client.get_prompt(name, label=label, cache_ttl_seconds=300)
        # Langfuse Prompt.prompt is a string for "text" prompts; for
        # "chat" prompts it's a list of messages. We use text prompts
        # for system messages, so str() coercion is safe.
        text = p.prompt if isinstance(p.prompt, str) else str(p.prompt)
        return ManagedPrompt(
            text=text,
            version=getattr(p, "version", 0) or 0,
            source="langfuse",
            langfuse_obj=p,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("langfuse: get_prompt(%s) fell back to local: %s", name, exc)
        return ManagedPrompt(text=fallback, version=0, source="fallback")


# ── Trace + generation helpers ───────────────────────────────────────────
def start_trace(
    name: str,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: dict | None = None,
    tags: list[str] | None = None,
) -> Any | None:
    """Start a Langfuse trace and return its handle (or None if disabled).

    Traces don't need explicit close — the Langfuse SDK batches and
    flushes them in a background thread. Pass the returned handle to
    `log_generation` to attach LLM observations under this trace.
    """
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
        logger.warning("langfuse: trace(%s) start failed: %s", name, exc)
        return None


def _redact_messages(messages: list[dict]) -> list[dict]:
    """Strip base64 image payloads from a chat-completion message list.

    The OpenAI vision API uses {"type": "image_url", "image_url":
    {"url": "data:image/jpeg;base64,..."}} — we replace the data URL
    with a marker so traces stay small AND citizen photos never leave
    our infra.
    """
    out: list[dict] = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            new_parts = []
            for part in content:
                if part.get("type") == "image_url":
                    new_parts.append({
                        "type": "image_url",
                        "image_url": {"url": "<redacted-base64-image>"},
                    })
                else:
                    new_parts.append(part)
            out.append({**m, "content": new_parts})
        else:
            out.append(m)
    return out


def log_generation(
    trace_handle: Any | None,
    *,
    name: str,
    model: str,
    messages: list[dict],
    response_text: str | None,
    parsed_output: Any | None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    elapsed_ms: int = 0,
    outcome: str = "success",
    error: str | None = None,
    prompt_obj: Any | None = None,
    metadata: dict | None = None,
) -> None:
    """Log a single LLM call as a Langfuse generation under `trace_handle`.

    Safe to call with `trace_handle=None` — it's a no-op then. All
    arguments are best-effort: if any fail to serialise, we log a
    warning and move on rather than crashing the OCR request.

    `prompt_obj` should be the Langfuse Prompt object the input was
    rendered from (returned by get_prompt). Passing it lets Langfuse
    aggregate generations by prompt version for eval reports.
    """
    if trace_handle is None:
        return
    try:
        usage = {
            "input": int(prompt_tokens or 0),
            "output": int(completion_tokens or 0),
            "total": int((prompt_tokens or 0) + (completion_tokens or 0)),
            "unit": "TOKENS",
        }
        gen_kwargs: dict[str, Any] = {
            "name": name,
            "model": model,
            "input": _redact_messages(messages),
            "output": parsed_output if parsed_output is not None else response_text,
            "usage": usage,
            "metadata": {
                "elapsed_ms": elapsed_ms,
                "outcome": outcome,
                **(metadata or {}),
            },
        }
        if error:
            gen_kwargs["status_message"] = error[:500]
            gen_kwargs["level"] = "ERROR"
        if prompt_obj is not None:
            gen_kwargs["prompt"] = prompt_obj
        gen = trace_handle.generation(**gen_kwargs)
        # End immediately — we have all the data already, this is a
        # post-hoc record not a streaming generation.
        try:
            gen.end()
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("langfuse: log_generation(%s) failed: %s", name, exc)


def log_span(
    trace_handle: Any | None,
    *,
    name: str,
    input: Any | None = None,
    output: Any | None = None,
    metadata: dict | None = None,
    level: str = "DEFAULT",
) -> None:
    """Record a non-LLM observation under a Langfuse trace.

    Use this for decision points that aren't model calls — cross-doc
    identity check, spoof detector, reconciliation, risk scoring, etc.
    Each one gets its own row in the Langfuse trace tree alongside the
    LLM generations, so a reviewer can see the full pipeline reasoning
    in one place. Fail-OPEN on any error; observability must never
    interrupt the pipeline.

    `level` accepts Langfuse's standard severities (DEFAULT / DEBUG /
    WARNING / ERROR) — set ERROR when the span represents a failed
    decision (e.g. cross-doc check rejected the case).
    """
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
        logger.warning("langfuse: log_span(%s) failed: %s", name, exc)


def log_score(
    trace_handle: Any | None,
    *,
    name: str,
    value: float,
    comment: str | None = None,
    data_type: str = "NUMERIC",
) -> None:
    """Attach a Langfuse score to a trace.

    Scores are how Langfuse aggregates evaluation results across many
    runs — useful for both automatic continuous eval (e.g. compare
    extracted fields to citizen-declared values, score the field-match
    rate) and human feedback (e.g. mukhtar approves/rejects → score
    the AI's auto-decision binary).

    `data_type`: "NUMERIC" (default) | "BOOLEAN" | "CATEGORICAL".
    BOOLEAN expects 0.0 or 1.0; CATEGORICAL takes a string value.
    """
    if trace_handle is None:
        return
    try:
        # Some SDK versions accept the score on the trace handle
        # directly; others require client.score(trace_id=...). Try
        # the handle first, fall back to the client for max
        # compatibility across langfuse versions.
        if hasattr(trace_handle, "score"):
            trace_handle.score(name=name, value=value, comment=comment, data_type=data_type)
            return
        client = get_client()
        if client is None:
            return
        trace_id = getattr(trace_handle, "id", None) or getattr(trace_handle, "trace_id", None)
        if not trace_id:
            return
        client.score(
            trace_id=trace_id,
            name=name,
            value=value,
            comment=comment,
            data_type=data_type,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("langfuse: log_score(%s) failed: %s", name, exc)
