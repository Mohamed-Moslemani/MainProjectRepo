"""Prometheus custom metrics for the OCR service."""

from prometheus_client import Counter, Histogram, Info

SERVICE_INFO = Info("docflow_ocr", "OCR service metadata")
SERVICE_INFO.info({"version": "0.1.0", "service": "ocr"})

OCR_REQUESTS = Counter(
    "docflow_ocr_requests_total",
    "Total OCR processing requests",
    ["document_type"],
)

OCR_DURATION = Histogram(
    "docflow_ocr_duration_seconds",
    "OCR processing time",
    ["document_type"],
    buckets=[0.5, 1, 2, 5, 10, 20, 30],
)

OCR_RETAKE_REQUIRED = Counter(
    "docflow_ocr_retake_required_total",
    "Documents requiring retake",
    ["document_type"],
)

OCR_CONFIDENCE = Histogram(
    "docflow_ocr_avg_confidence",
    "Average field confidence per document",
    buckets=[0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95, 1.0],
)

OCR_QUALITY_ISSUES = Counter(
    "docflow_ocr_quality_issues_total",
    "Quality issues detected in uploaded documents",
    ["issue_type"],  # blur, glare, low_resolution, skewed
)

OCR_ERRORS = Counter(
    "docflow_ocr_errors_total",
    "OCR processing errors",
    ["stage"],  # quality, extract_text, field_extract, mrz
)

OCR_MRZ_RESULTS = Counter(
    "docflow_ocr_mrz_results_total",
    "MRZ parsing results",
    ["outcome"],  # parsed_valid, parsed_invalid, not_found
)

OCR_FIELDS_EXTRACTED = Histogram(
    "docflow_ocr_fields_extracted",
    "Number of fields extracted per document",
    buckets=[0, 1, 2, 3, 5, 7, 10, 15],
)

# ── LLM extractor (vision-LLM fallback for table-shaped docs) ────────────
# The LLM path is opt-in (regex-first), so these counters also tell us
# how often we paid for an LLM call vs. served the request from regex.
OCR_LLM_CALLS = Counter(
    "docflow_ocr_llm_calls_total",
    "LLM extractor invocations",
    ["document_type", "model", "outcome"],  # outcome: success, error, skipped_no_key, skipped_unsupported, skipped_no_package
)
OCR_LLM_DURATION = Histogram(
    "docflow_ocr_llm_duration_seconds",
    "Wall-clock time per LLM extraction call",
    ["document_type", "model"],
    buckets=[0.5, 1, 2, 3, 5, 8, 12, 20, 30],
)
OCR_LLM_FIELDS_EXTRACTED = Histogram(
    "docflow_ocr_llm_fields_extracted",
    "Number of fields the LLM returned (after schema filter)",
    ["document_type"],
    buckets=[0, 1, 2, 3, 5, 7, 10, 15],
)
OCR_LLM_TOKENS = Counter(
    "docflow_ocr_llm_tokens_total",
    "Token usage on LLM extractor calls",
    ["model", "kind"],  # kind: prompt, completion
)

# ── Document-type / authenticity classifier ──────────────────────────────
# Runs a vision-LLM classification pass before field extraction so the
# pipeline can reject wrong-document and casually-forged uploads up front
# instead of leaking them into manual review with empty extraction output.
OCR_CLASSIFIER_CALLS = Counter(
    "docflow_ocr_classifier_calls_total",
    "Document-type classifier invocations",
    ["document_type", "model", "outcome"],  # outcome: success, error, mock, skipped_*
)
OCR_CLASSIFIER_DURATION = Histogram(
    "docflow_ocr_classifier_duration_seconds",
    "Wall-clock time per classifier call",
    ["document_type", "model"],
    buckets=[0.5, 1, 2, 3, 5, 8, 12, 20],
)
OCR_CLASSIFIER_REJECTED = Counter(
    "docflow_ocr_classifier_rejected_total",
    "Uploads the classifier flagged as wrong-type or not-authentic",
    ["expected_type", "reason"],  # reason: type_mismatch, not_authentic
)
