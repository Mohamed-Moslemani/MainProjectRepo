"""Prometheus custom metrics for the Gateway service."""

from prometheus_client import Counter, Histogram, Info

# ── Service info ──────────────────────────────────────────────────────────────
SERVICE_INFO = Info("docflow_gateway", "Gateway service metadata")
SERVICE_INFO.info({"version": "0.1.0", "service": "gateway"})

# ── Authentication ────────────────────────────────────────────────────────────
AUTH_REGISTRATIONS = Counter(
    "docflow_auth_registrations_total",
    "Total user registrations",
)
AUTH_LOGINS = Counter(
    "docflow_auth_logins_total",
    "Total login attempts",
    ["status"],  # success, failed, unverified, rate_limited
)
AUTH_PASSWORD_RESETS = Counter(
    "docflow_auth_password_resets_total",
    "Total password reset requests",
)
AUTH_EMAIL_VERIFICATIONS = Counter(
    "docflow_auth_email_verifications_total",
    "Total email verifications",
    ["status"],  # success, failed
)

# ── Cases ─────────────────────────────────────────────────────────────────────
CASES_CREATED = Counter(
    "docflow_cases_created_total",
    "Total cases created",
    ["service_type"],  # id_new, id_renewal, passport_new, passport_renewal
)
CASES_SUBMITTED = Counter(
    "docflow_cases_submitted_total",
    "Total cases submitted for processing",
    ["service_type"],
)
CASE_STATUS_TRANSITIONS = Counter(
    "docflow_case_status_transitions_total",
    "Total case status transitions",
    ["from_status", "to_status"],
)

# ── Pipeline processing ──────────────────────────────────────────────────────
PIPELINE_DURATION = Histogram(
    "docflow_pipeline_duration_seconds",
    "Time to run the full processing pipeline",
    ["service_type"],
    buckets=[1, 2, 5, 10, 20, 30, 60, 120],
)
PIPELINE_DECISIONS = Counter(
    "docflow_pipeline_decisions_total",
    "Pipeline routing decisions",
    ["decision"],  # auto_approve, manual_review, reject
)
RISK_SCORE = Histogram(
    "docflow_risk_score",
    "Distribution of risk scores",
    buckets=[0, 10, 20, 25, 30, 40, 50, 60, 70, 80, 90, 100],
)

# ── Reconciliation ────────────────────────────────────────────────────────────
# Reconciliation compares declared fields vs OCR-extracted fields. Integrity
# score is the weighted match ratio (0-1); validation_result classifies the
# outcome (pass / need_info / fail). These feed into risk scoring (~25%
# weight) and are the only AI signal currently invisible on the dashboard.
RECONCILIATION_INTEGRITY = Histogram(
    "docflow_reconciliation_integrity_score",
    "Reconciliation integrity score (0-1)",
    buckets=[0.0, 0.25, 0.5, 0.65, 0.75, 0.85, 0.9, 0.95, 1.0],
)
RECONCILIATION_RESULTS = Counter(
    "docflow_reconciliation_results_total",
    "Reconciliation validation outcomes",
    ["validation_result"],  # pass, need_info, fail
)
RECONCILIATION_MISMATCHES = Counter(
    "docflow_reconciliation_mismatches_total",
    "Per-field reconciliation mismatches",
    ["field"],
)

# ── Documents ─────────────────────────────────────────────────────────────────
DOCUMENTS_UPLOADED = Counter(
    "docflow_documents_uploaded_total",
    "Total documents uploaded",
    ["document_type"],
)
DOCUMENT_UPLOAD_SIZE = Histogram(
    "docflow_document_upload_bytes",
    "Document upload size in bytes",
    buckets=[50_000, 100_000, 500_000, 1_000_000, 5_000_000, 10_000_000],
)

# ── Payments ──────────────────────────────────────────────────────────────────
PAYMENTS_CREATED = Counter(
    "docflow_payments_created_total",
    "Total payment checkout sessions created",
)
PAYMENTS_COMPLETED = Counter(
    "docflow_payments_completed_total",
    "Total successful payments",
)
PAYMENTS_FAILED = Counter(
    "docflow_payments_failed_total",
    "Total failed payments",
)
PAYMENT_AMOUNT = Histogram(
    "docflow_payment_amount_cents",
    "Payment amounts in cents",
    buckets=[1000, 1500, 2000, 4000, 6000, 10000],
)

# ── Email ─────────────────────────────────────────────────────────────────────
EMAILS_SENT = Counter(
    "docflow_emails_sent_total",
    "Total emails sent",
    ["type"],  # verification, password_reset, status_notification
)
EMAILS_FAILED = Counter(
    "docflow_emails_failed_total",
    "Total email send failures",
    ["type"],
)

# ── External service calls ────────────────────────────────────────────────────
EXTERNAL_CALL_DURATION = Histogram(
    "docflow_external_call_duration_seconds",
    "Duration of calls to external services",
    ["service"],  # ocr, face
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30],
)
EXTERNAL_CALL_ERRORS = Counter(
    "docflow_external_call_errors_total",
    "Failed calls to external services",
    ["service"],
)

# ── Rate limiting ─────────────────────────────────────────────────────────────
RATE_LIMIT_HITS = Counter(
    "docflow_rate_limit_hits_total",
    "Total rate limit rejections",
    ["endpoint"],  # login, reset, verification, general
)

