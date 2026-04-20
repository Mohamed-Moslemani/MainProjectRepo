"""Prometheus metrics for the civil registry service."""

from prometheus_client import Counter, Histogram, Info

SERVICE_INFO = Info("docflow_registry", "Civil registry service metadata")
SERVICE_INFO.info({"version": "0.1.0", "service": "registry"})

REGISTRY_REQUESTS = Counter(
    "docflow_registry_requests_total",
    "Total registry verification requests",
)

REGISTRY_DURATION = Histogram(
    "docflow_registry_duration_seconds",
    "Registry verification duration",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

REGISTRY_RESULTS = Counter(
    "docflow_registry_results_total",
    "Registry verification outcomes",
    ["status"],  # exact_match / partial_match / no_match / deceased / error
)

REGISTRY_CONFIDENCE = Histogram(
    "docflow_registry_match_confidence",
    "Aggregate match confidence across all verifications",
    buckets=[0, 0.25, 0.5, 0.7, 0.85, 0.9, 0.95, 1.0],
)
