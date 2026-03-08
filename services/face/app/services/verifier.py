"""Face verification orchestrator - combines comparison + liveness into a decision."""

import logging
from ..config import get_settings
from .rekognition import compare_faces
from .liveness import assess_liveness

logger = logging.getLogger(__name__)


def verify(selfie_path: str, reference_path: str) -> dict:
    """Run full face verification pipeline.

    Returns decision: pass / manual_review / fail
    Uses conservative thresholds: borderline -> manual_review.
    """
    settings = get_settings()

    # Step 1: Liveness check on selfie
    liveness = assess_liveness(selfie_path)
    liveness_score = liveness["liveness_score"]

    # Step 2: Face comparison
    comparison = compare_faces(selfie_path, reference_path)
    similarity_score = comparison["similarity_score"]

    # Step 3: Decision logic (conservative)
    reasons = []
    total_time_ms = comparison["processing_time_ms"]

    # Liveness decision
    if liveness_score >= settings.liveness_pass_threshold:
        liveness_passed = True
    elif liveness_score >= settings.liveness_review_threshold:
        liveness_passed = False
        reasons.append(f"Liveness score borderline ({liveness_score:.2f})")
    else:
        liveness_passed = False
        reasons.append(f"Liveness check failed ({liveness_score:.2f})")
        reasons.extend(liveness.get("reasons", []))

    # Similarity decision
    if similarity_score >= settings.similarity_pass_threshold and liveness_passed:
        decision = "pass"
    elif similarity_score < settings.similarity_review_threshold:
        decision = "fail"
        reasons.append(f"Face similarity too low ({similarity_score:.1f}%)")
    elif not liveness_passed and liveness_score < settings.liveness_review_threshold:
        decision = "fail"
    else:
        decision = "manual_review"
        if similarity_score < settings.similarity_pass_threshold:
            reasons.append(
                f"Face similarity borderline ({similarity_score:.1f}%, "
                f"threshold: {settings.similarity_pass_threshold}%)"
            )

    return {
        "similarity_score": similarity_score,
        "liveness_score": liveness_score,
        "liveness_passed": liveness_passed,
        "decision": decision,
        "reasons": reasons,
        "processing_time_ms": total_time_ms,
    }
