"""Risk scoring service - weighted model combining all validation signals.

Inputs: OCR confidence, face similarity, liveness confidence,
        declared-vs-OCR reconciliation integrity, civil-registry match,
        document quality, service-type severity, mismatch + duplicate
        penalties.

Output: risk score (0-100) and routing decision.
"""

import logging

logger = logging.getLogger(__name__)

# Weights for risk components (must sum to 1.0).
#
# Document quality used to live here, but it's now a *gate* enforced by
# the orchestrator before scoring (any retake_required short-circuits to
# NEED_INFO). When risk runs, every doc is already readable, so quality
# carries no signal. Its 0.10 weight was redistributed: +0.05 to
# reconciliation, +0.05 to ocr_confidence — both gain meaning once we
# know the underlying images were sharp.
WEIGHTS = {
    "registry_match": 0.25,   # authoritative identity check (Ministry lookup)
    "face_similarity": 0.20,
    "reconciliation": 0.20,   # declared vs OCR consistency
    "liveness": 0.15,
    "ocr_confidence": 0.15,
    "service_severity": 0.05,
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
    service_type: str,
    mismatch_count: int = 0,
    duplicate_detected: bool = False,
    registry_match_score: float = 1.0,  # 0-1 from civil registry verification
    registry_deceased: bool = False,
    document_quality_avg: float | None = None,  # deprecated; retained for callers
) -> dict:
    """Compute weighted risk score.

    Lower score = lower risk = more likely to auto-approve.
    Higher score = higher risk = more likely to reject or review.

    A `registry_deceased=True` hard-overrides the score to 100 regardless
    of other inputs — no document can be issued to a registered-dead
    citizen, period.
    """

    # Convert all inputs to risk (0 = no risk, 100 = max risk)
    ocr_risk = (1 - ocr_avg_confidence) * 100
    face_risk = max(0, 100 - face_similarity)  # similarity 90 -> risk 10
    liveness_risk = (1 - liveness_score) * 100
    reconciliation_risk = (1 - reconciliation_integrity) * 100
    registry_risk = (1 - registry_match_score) * 100
    severity = SERVICE_SEVERITY.get(service_type, 0.5) * 100

    # Weighted sum
    raw_score = (
        WEIGHTS["registry_match"] * registry_risk +
        WEIGHTS["ocr_confidence"] * ocr_risk +
        WEIGHTS["face_similarity"] * face_risk +
        WEIGHTS["liveness"] * liveness_risk +
        WEIGHTS["reconciliation"] * reconciliation_risk +
        WEIGHTS["service_severity"] * severity
    )

    # Penalty for mismatches
    raw_score += mismatch_count * 8

    # Hard penalty for duplicates
    if duplicate_detected:
        raw_score += 30

    # Deceased override — always reject
    if registry_deceased:
        raw_score = 100

    risk_score = min(100, max(0, round(raw_score, 2)))

    # Routing decision
    if registry_deceased:
        routing = "reject"
    elif risk_score <= AUTO_APPROVE_THRESHOLD:
        routing = "auto_approve"
    elif risk_score <= MANUAL_REVIEW_THRESHOLD:
        routing = "manual_review"
    else:
        routing = "reject"

    return {
        "risk_score": risk_score,
        "routing": routing,
        "breakdown": {
            "registry_risk": round(registry_risk, 2),
            "ocr_risk": round(ocr_risk, 2),
            "face_risk": round(face_risk, 2),
            "liveness_risk": round(liveness_risk, 2),
            "reconciliation_risk": round(reconciliation_risk, 2),
            "severity": round(severity, 2),
            "mismatch_penalty": mismatch_count * 8,
            "duplicate_penalty": 30 if duplicate_detected else 0,
            "registry_deceased_override": registry_deceased,
        },
    }
