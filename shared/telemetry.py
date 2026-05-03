"""OpenTelemetry tracing + Sentry/GlitchTip error capture bootstrap.

One install_telemetry() call per service, in the FastAPI startup
hook. Instruments FastAPI, httpx, SQLAlchemy, and asyncpg
out-of-the-box so spans for every HTTP request, every cross-service
call, every DB query, and every nested operation flow into Jaeger
without per-handler annotation.

Errors not caught by route handlers (and 500s the boundary turns
into responses) are also captured by sentry-sdk if SENTRY_DSN is
set. Same SDK works against self-hosted GlitchTip and SaaS Sentry —
GlitchTip implements the Sentry protocol.

Env vars:
  OTEL_EXPORTER_OTLP_ENDPOINT  default http://jaeger:4317 inside the
                               compose network. Override to point at
                               a different OTLP collector.
  OTEL_SERVICE_NAME            sets the service label every span
                               carries; required so Jaeger groups
                               traces by service.
  TRACING_ENABLED              set to '0' or 'false' to skip span
                               export entirely (useful for local
                               quick runs without Jaeger).
  SENTRY_DSN                   if blank, Sentry init is skipped
                               quietly — local dev works without it.

Idempotent — calling twice is a no-op so module reloads in tests
don't trip over duplicate provider setup.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_initialised = False


def _truthy(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).lower() not in ("0", "false", "no", "")


def install_telemetry(*, service_name: str, app=None) -> None:
    """Wire OTel + Sentry once per service. Pass `app=` after the
    FastAPI() call so FastAPI instrumentation can attach.
    """
    global _initialised
    if _initialised:
        return
    _initialised = True

    if _truthy("TRACING_ENABLED"):
        try:
            _setup_tracing(service_name=service_name, app=app)
        except Exception as exc:  # pragma: no cover - bootstrap defensive
            # Tracing failures must never block service startup —
            # log and continue without spans.
            logger.warning("OpenTelemetry init failed (%s); continuing without traces", exc)

    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if dsn:
        try:
            _setup_sentry(service_name=service_name, dsn=dsn)
        except Exception as exc:  # pragma: no cover
            logger.warning("Sentry/GlitchTip init failed (%s); continuing without error capture", exc)


def _setup_tracing(*, service_name: str, app=None) -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
    # Two transports — gRPC (default for local Jaeger) and HTTP/protobuf
    # (default for Grafana Cloud Tempo). When the wrong one is used,
    # exports fail in a background thread, the BatchSpanProcessor buffer
    # fills up, and the NEXT span the SQLAlchemyInstrumentor wraps blocks
    # waiting for room — which manifests as a hard hang in alembic
    # upgrade right after "Will assume transactional DDL". Pick the
    # exporter from the protocol env var to avoid that cliff.
    protocol = os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").lower()
    headers_raw = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "").strip()
    headers: dict[str, str] | None = None
    if headers_raw:
        # Format: "Authorization=Basic%20...,Other-Header=value"
        from urllib.parse import unquote
        headers = {}
        for pair in headers_raw.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                headers[k.strip()] = unquote(v.strip())

    if protocol in ("http/protobuf", "http"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        # Grafana Cloud expects spans at <base>/v1/traces. Be lenient
        # in case the configured endpoint already has the suffix.
        ep = endpoint.rstrip("/")
        if not ep.endswith("/v1/traces"):
            ep = ep + "/v1/traces"
        exporter = OTLPSpanExporter(endpoint=ep, headers=headers or {})
    else:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        # insecure only for plaintext gRPC (e.g. local jaeger:4317).
        is_insecure = endpoint.startswith("http://") or "://" not in endpoint
        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            insecure=is_insecure,
            headers=headers or None,
        )
    resource = Resource.create({
        "service.name": service_name,
        "service.version": os.environ.get("GIT_SHA") or os.environ.get("DOCFLOW_VERSION") or "dev",
        "deployment.environment": os.environ.get("DEPLOY_ENV", "dev"),
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # Auto-instrument the libraries we actually use. Each .instrument()
    # call is idempotent at the library level.
    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(
            app,
            # Health/metrics endpoints would otherwise dominate the
            # span volume with no diagnostic value.
            excluded_urls="/health,/health/ready,/metrics",
        )

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
    except Exception:
        pass

    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        SQLAlchemyInstrumentor().instrument()
    except Exception:
        pass

    logger.info("OpenTelemetry tracing → %s as service.name=%s", endpoint, service_name)


def _setup_sentry(*, service_name: str, dsn: str) -> None:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=dsn,
        send_default_pii=False,  # we redact PII in audit logs already
        traces_sample_rate=0.0,  # tracing is OTel's job; don't double-cost
        environment=os.environ.get("DEPLOY_ENV", "dev"),
        release=os.environ.get("GIT_SHA") or os.environ.get("DOCFLOW_VERSION") or "dev",
        server_name=service_name,
        integrations=[
            FastApiIntegration(),
            StarletteIntegration(),
        ],
    )
    logger.info("Sentry/GlitchTip error capture initialised for service=%s", service_name)
