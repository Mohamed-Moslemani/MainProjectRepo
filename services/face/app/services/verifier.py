"""Face verification orchestrator - combines comparison + liveness into a decision."""

import logging
from ..config import get_settings
from ..metrics import FACE_VALIDATION_FAILURES
from .rekognition import compare_faces, detect_faces, compare_faces_bytes
from .liveness import assess_liveness

logger = logging.getLogger(__name__)


def _validate_selfie(image_path: str, settings) -> dict:
    """Pre-validate selfie using Rekognition DetectFaces.

    Checks: face present, single face, eyes open, no sunglasses, image quality.
    Returns {"ok": bool, "reasons": [...], "quality": {...}, "processing_time_ms": int}
    """
    import time
    start = time.time()
    detection = detect_faces(image_path)
    elapsed_ms = int((time.time() - start) * 1000)

    reasons = []
    face_count = detection["face_count"]

    if face_count == 0:
        FACE_VALIDATION_FAILURES.labels(reason="no_face").inc()
        return {"ok": False, "reasons": ["No face detected in selfie"], "quality": {}, "processing_time_ms": elapsed_ms}

    if face_count > 1:
        FACE_VALIDATION_FAILURES.labels(reason="multiple_faces").inc()
        reasons.append(f"Multiple faces detected in selfie ({face_count})")

    face = detection["faces"][0]

    if face["confidence"] < settings.min_face_confidence:
        FACE_VALIDATION_FAILURES.labels(reason="low_face_confidence").inc()
        reasons.append(f"Low face detection confidence ({face['confidence']:.1f}%)")

    if face["sunglasses"]:
        FACE_VALIDATION_FAILURES.labels(reason="sunglasses").inc()
        reasons.append("Sunglasses detected in selfie")

    if not face["eyes_open"]:
        FACE_VALIDATION_FAILURES.labels(reason="eyes_closed").inc()
        reasons.append("Eyes appear closed in selfie")

    brightness = face["quality"].get("brightness", 0)
    sharpness = face["quality"].get("sharpness", 0)

    if brightness < settings.min_brightness:
        FACE_VALIDATION_FAILURES.labels(reason="low_brightness").inc()
        reasons.append(f"Selfie too dark (brightness {brightness:.1f})")

    if sharpness < settings.min_sharpness:
        FACE_VALIDATION_FAILURES.labels(reason="low_sharpness").inc()
        reasons.append(f"Selfie too blurry (sharpness {sharpness:.1f})")

    return {
        "ok": len(reasons) == 0,
        "reasons": reasons,
        "quality": {"brightness": brightness, "sharpness": sharpness},
        "processing_time_ms": elapsed_ms,
    }


def _validate_reference(image_path: str, settings) -> dict:
    """Pre-validate reference document photo using Rekognition DetectFaces.

    Checks: face present, face large enough, image quality.
    Returns {"ok": bool, "reasons": [...], "processing_time_ms": int}
    """
    import time
    start = time.time()
    detection = detect_faces(image_path)
    elapsed_ms = int((time.time() - start) * 1000)

    reasons = []
    face_count = detection["face_count"]

    if face_count == 0:
        return {"ok": False, "reasons": ["No face detected in reference document"], "processing_time_ms": elapsed_ms}

    face = detection["faces"][0]

    if face["confidence"] < settings.min_face_confidence:
        reasons.append(f"Low face detection confidence in reference document ({face['confidence']:.1f}%)")

    brightness = face["quality"].get("brightness", 0)
    sharpness = face["quality"].get("sharpness", 0)

    if brightness < settings.min_brightness:
        reasons.append(f"Reference document photo too dark (brightness {brightness:.1f})")

    if sharpness < settings.min_sharpness:
        reasons.append(f"Reference document photo too blurry (sharpness {sharpness:.1f})")

    return {
        "ok": len(reasons) == 0,
        "reasons": reasons,
        "processing_time_ms": elapsed_ms,
    }


def verify(selfie_path: str, reference_path: str) -> dict:
    """Run full face verification pipeline.

    Returns decision: pass / manual_review / fail
    Uses conservative thresholds: borderline -> manual_review.
    """
    settings = get_settings()

    # Step 1: Pre-validate selfie (face presence, quality, sunglasses, eyes)
    validation = _validate_selfie(selfie_path, settings)
    reasons = []
    total_time_ms = validation["processing_time_ms"]

    if not validation["ok"]:
        # Hard failures (no face) -> fail immediately; soft issues -> collect reasons
        if "No face detected" in str(validation["reasons"]):
            return {
                "similarity_score": 0.0,
                "liveness_score": 0.0,
                "liveness_passed": False,
                "face_quality": validation["quality"],
                "decision": "fail",
                "reasons": validation["reasons"],
                "processing_time_ms": total_time_ms,
            }
        reasons.extend(validation["reasons"])

    # Step 2: Pre-validate reference document photo
    ref_validation = _validate_reference(reference_path, settings)
    total_time_ms += ref_validation["processing_time_ms"]

    if not ref_validation["ok"]:
        if "No face detected" in str(ref_validation["reasons"]):
            return {
                "similarity_score": 0.0,
                "liveness_score": 0.0,
                "liveness_passed": False,
                "face_quality": validation["quality"],
                "decision": "fail",
                "reasons": ref_validation["reasons"],
                "processing_time_ms": total_time_ms,
            }
        reasons.extend(ref_validation["reasons"])

    # Step 3: Liveness check on selfie
    liveness = assess_liveness(selfie_path)
    liveness_score = liveness["liveness_score"]

    # Step 4: Face comparison
    comparison = compare_faces(selfie_path, reference_path)
    similarity_score = comparison["similarity_score"]
    total_time_ms += comparison["processing_time_ms"]

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

    # Soft validation issues (sunglasses, eyes closed, multiple faces) downgrade pass -> manual_review
    if decision == "pass" and not validation["ok"]:
        decision = "manual_review"

    return {
        "similarity_score": similarity_score,
        "liveness_score": liveness_score,
        "liveness_passed": liveness_passed,
        "face_quality": validation["quality"],
        "decision": decision,
        "reasons": reasons,
        "processing_time_ms": total_time_ms,
    }


def verify_with_liveness_session(
    liveness_confidence: float,
    liveness_passed: bool,
    liveness_reference_image: bytes | None,
    reference_doc_path: str,
) -> dict:
    """Verify using Rekognition Liveness session results + face comparison.

    This replaces the heuristic liveness + selfie upload flow.
    The liveness session already captured a verified live face image.
    We compare that against the reference document photo.
    """
    import time
    settings = get_settings()
    start = time.time()
    reasons = []

    # Liveness score normalized to 0-1
    liveness_score = liveness_confidence / 100.0

    if not liveness_passed:
        reasons.append(f"Liveness check failed (confidence: {liveness_confidence:.1f}%)")

    # Face comparison: liveness reference image vs document photo
    similarity_score = 0.0
    if liveness_reference_image and liveness_passed:
        try:
            with open(reference_doc_path, "rb") as f:
                doc_bytes = f.read()
            comparison = compare_faces_bytes(liveness_reference_image, doc_bytes)
            similarity_score = comparison["similarity_score"]
        except Exception as e:
            logger.error(f"Face comparison failed: {e}")
            reasons.append(f"Face comparison error: {str(e)}")
    elif not liveness_reference_image:
        reasons.append("No reference image from liveness session")

    elapsed_ms = int((time.time() - start) * 1000)

    # Decision logic (same thresholds as verify())
    if similarity_score >= settings.similarity_pass_threshold and liveness_passed:
        decision = "pass"
    elif similarity_score < settings.similarity_review_threshold:
        decision = "fail"
        reasons.append(f"Face similarity too low ({similarity_score:.1f}%)")
    elif not liveness_passed:
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
        "processing_time_ms": elapsed_ms,
    }
