"""Risk scoring service - weighted model combining all validation signals.

Inputs: OCR confidence, face similarity, liveness confidence, mismatch flags,
        service type severity, duplicate detection.

Output: risk score (0-100) and routing decision.
"""

import logging

logger = logging.getLogger(__name__)

# Weights for risk components (must sum to 1.0)
WEIGHTS = {
    "ocr_confidence": 0.15,
    "face_similarity": 0.20,
    "liveness": 0.20,
    "reconciliation": 0.25,
    "document_quality": 0.10,
    "service_severity": 0.10,
}

# Passport is stricter than ID; new is stricter than renewal
SERVICE_SEVERITY = {
    "id_renewal": 0.2,
    "id_new": 0.4,
    "passport_renewal": 0.6,
    "passport_new": 0.8,
}

# Routing thresholds
AUTO_APPROVE_THRESHOLD = 25    # risk <= 25 -> straight-through
MANUAL_REVIEW_THRESHOLD = 60   # 25 < risk <= 60 -> manual review
# risk > 60 -> reject


def compute_risk_score(
    ocr_avg_confidence: float,         # 0-1
    face_similarity: float,            # 0-100
    liveness_score: float,             # 0-1
    reconciliation_integrity: float,   # 0-1
    document_quality_avg: float,       # 0-1 (avg quality across docs)
    service_type: str,
    mismatch_count: int = 0,
    duplicate_detected: bool = False,
) -> dict:
    """Compute weighted risk score.

    Lower score = lower risk = more likely to auto-approve.
    Higher score = higher risk = more likely to reject or review.
    """

    # Convert all inputs to risk (0 = no risk, 100 = max risk)
    ocr_risk = (1 - ocr_avg_confidence) * 100
    face_risk = max(0, 100 - face_similarity)  # similarity 90 -> risk 10
    liveness_risk = (1 - liveness_score) * 100
    reconciliation_risk = (1 - reconciliation_integrity) * 100
    quality_risk = (1 - document_quality_avg) * 100
    severity = SERVICE_SEVERITY.get(service_type, 0.5) * 100

    # Weighted sum
    raw_score = (
        WEIGHTS["ocr_confidence"] * ocr_risk +
        WEIGHTS["face_similarity"] * face_risk +
        WEIGHTS["liveness"] * liveness_risk +
        WEIGHTS["reconciliation"] * reconciliation_risk +
        WEIGHTS["document_quality"] * quality_risk +
        WEIGHTS["service_severity"] * severity
    )

    # Penalty for mismatches
    raw_score += mismatch_count * 8

    # Hard penalty for duplicates
    if duplicate_detected:
        raw_score += 30

    risk_score = min(100, max(0, round(raw_score, 2)))

    # Routing decision
    if risk_score <= AUTO_APPROVE_THRESHOLD:
        routing = "auto_approve"
    elif risk_score <= MANUAL_REVIEW_THRESHOLD:
        routing = "manual_review"
    else:
        routing = "reject"

    return {
        "risk_score": risk_score,
        "routing": routing,
        "breakdown": {
            "ocr_risk": round(ocr_risk, 2),
            "face_risk": round(face_risk, 2),
            "liveness_risk": round(liveness_risk, 2),
            "reconciliation_risk": round(reconciliation_risk, 2),
            "quality_risk": round(quality_risk, 2),
            "severity": round(severity, 2),
            "mismatch_penalty": mismatch_count * 8,
            "duplicate_penalty": 30 if duplicate_detected else 0,
        },
    }
