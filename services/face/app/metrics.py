"""Prometheus custom metrics for the Face verification service."""

from prometheus_client import Counter, Histogram, Info

SERVICE_INFO = Info("docflow_face", "Face service metadata")
SERVICE_INFO.info({"version": "0.1.0", "service": "face"})

FACE_VERIFY_REQUESTS = Counter(
    "docflow_face_verify_total",
    "Total face verification requests",
)

FACE_VERIFY_DURATION = Histogram(
    "docflow_face_verify_duration_seconds",
    "Face verification time",
    buckets=[0.5, 1, 2, 5, 10, 20],
)

FACE_VERIFY_DECISIONS = Counter(
    "docflow_face_verify_decisions_total",
    "Verification decisions",
    ["decision"],  # pass, manual_review, fail
)

FACE_SIMILARITY_SCORE = Histogram(
    "docflow_face_similarity_score",
    "Face similarity scores (0-100)",
    buckets=[0, 20, 40, 60, 70, 80, 90, 95, 100],
)

FACE_LIVENESS_SCORE = Histogram(
    "docflow_face_liveness_score",
    "Liveness confidence scores (0-1)",
    buckets=[0, 0.25, 0.5, 0.7, 0.85, 0.9, 0.95, 1.0],
)

FACE_LIVENESS_SESSIONS = Counter(
    "docflow_face_liveness_sessions_total",
    "Liveness sessions created",
)

FACE_LIVENESS_RESULTS = Counter(
    "docflow_face_liveness_results_total",
    "Liveness results",
    ["status"],  # SUCCEEDED, FAILED, EXPIRED, IN_PROGRESS, CREATED
)

FACE_ERRORS = Counter(
    "docflow_face_errors_total",
    "Face service errors",
    ["operation"],  # verify, detect, compare, liveness_create, liveness_results
)

FACE_VALIDATION_FAILURES = Counter(
    "docflow_face_validation_failures_total",
    "Selfie/reference pre-validation failures",
    ["reason"],  # no_face, multiple_faces, sunglasses, eyes_closed, low_brightness, low_sharpness
)
