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
