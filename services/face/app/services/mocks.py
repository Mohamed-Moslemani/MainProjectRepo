"""Fixture-based mock responses for Face verification.

Activated by setting FACE_MOCK_MODE=1. Returns deterministic happy-path
fixtures (valid face, high similarity, successful liveness) so E2E tests
can exercise the full pipeline without hitting AWS Rekognition.
"""

import uuid


def mock_detect_faces(image_path: str) -> dict:
    """One clean face detected with high confidence."""
    return {
        "face_count": 1,
        "faces": [{
            "confidence": 99.5,
            "quality": {"brightness": 85.0, "sharpness": 85.0},
            "eyes_open": True,
            "sunglasses": False,
        }],
    }


def mock_compare_faces(selfie_path: str, reference_path: str) -> dict:
    """High similarity match."""
    return {
        "similarity_score": 95.0,
        "face_detected_selfie": True,
        "face_detected_reference": True,
        "processing_time_ms": 15,
    }


def mock_compare_faces_bytes(source_bytes: bytes, target_bytes: bytes) -> dict:
    return {
        "similarity_score": 95.0,
        "face_detected_selfie": True,
        "face_detected_reference": True,
        "processing_time_ms": 15,
    }


def mock_create_liveness_session() -> dict:
    """Return a fresh fake session id."""
    return {"session_id": f"mock-{uuid.uuid4().hex}"}


def mock_get_liveness_session_results(session_id: str) -> dict:
    """Succeeded liveness session with a fake reference image."""
    return {
        "session_id": session_id,
        "status": "SUCCEEDED",
        "confidence": 95.0,
        "reference_image": b"MOCK_REFERENCE_IMAGE_BYTES",
    }


def mock_assess_liveness(image_path: str) -> dict:
    """Heuristic liveness replacement — always passing."""
    return {
        "liveness_score": 0.95,
        "checks": {
            "texture_analysis": True,
            "color_distribution": True,
            "reflection_check": True,
            "frequency_analysis": True,
        },
        "reasons": [],
    }
