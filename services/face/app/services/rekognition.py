"""AWS Rekognition face comparison and liveness service."""

import time
import logging

from ..clients import get_rekognition_client
from ..config import get_settings
from .mocks import (
    mock_create_liveness_session,
    mock_get_liveness_session_results,
    mock_compare_faces,
    mock_compare_faces_bytes,
    mock_detect_faces,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rekognition Face Liveness
# ---------------------------------------------------------------------------

def create_liveness_session() -> dict:
    """Create a Face Liveness session.

    Returns:
        {"session_id": str}
    """
    if get_settings().mock_mode:
        return mock_create_liveness_session()

    client = get_rekognition_client()
    response = client.create_face_liveness_session(
        Settings={"AuditImagesLimit": 4},
    )
    return {"session_id": response["SessionId"]}


def get_liveness_session_results(session_id: str) -> dict:
    """Get Face Liveness session results.

    Returns:
        {
            "session_id": str,
            "status": str,  # "CREATED" | "IN_PROGRESS" | "SUCCEEDED" | "FAILED" | "EXPIRED"
            "confidence": float,  # 0-100, only meaningful if SUCCEEDED
            "reference_image": bytes | None,  # the face image captured during liveness
        }
    """
    if get_settings().mock_mode:
        return mock_get_liveness_session_results(session_id)

    client = get_rekognition_client()
    response = client.get_face_liveness_session_results(SessionId=session_id)

    status = response.get("Status", "FAILED")
    confidence = response.get("Confidence", 0.0)

    reference_image = None
    ref = response.get("ReferenceImage")
    if ref and ref.get("Bytes"):
        reference_image = ref["Bytes"]
    elif ref and ref.get("S3Object"):
        logger.info(f"Liveness reference image is in S3: {ref['S3Object']}")

    return {
        "session_id": session_id,
        "status": status,
        "confidence": confidence,
        "reference_image": reference_image,
    }


# ---------------------------------------------------------------------------
# Face Comparison
# ---------------------------------------------------------------------------


def compare_faces(selfie_path: str, reference_path: str) -> dict:
    """Compare two faces using AWS Rekognition.

    Returns:
        {
            "similarity_score": float (0-100),
            "face_detected_selfie": bool,
            "face_detected_reference": bool,
            "processing_time_ms": int,
        }
    """
    if get_settings().mock_mode:
        return mock_compare_faces(selfie_path, reference_path)

    client = get_rekognition_client()

    with open(selfie_path, "rb") as sf, open(reference_path, "rb") as rf:
        selfie_bytes = sf.read()
        reference_bytes = rf.read()

    start = time.time()
    response = client.compare_faces(
        SourceImage={"Bytes": selfie_bytes},
        TargetImage={"Bytes": reference_bytes},
        SimilarityThreshold=0.0,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    similarity_score = 0.0
    if response.get("FaceMatches"):
        similarity_score = response["FaceMatches"][0]["Similarity"]

    return {
        "similarity_score": similarity_score,
        "face_detected_selfie": len(response.get("SourceImageFace", {}).get("BoundingBox", {})) > 0
            if response.get("SourceImageFace") else False,
        "face_detected_reference": len(response.get("FaceMatches", [])) > 0
            or len(response.get("UnmatchedFaces", [])) > 0,
        "processing_time_ms": elapsed_ms,
    }


def detect_faces(image_path: str) -> dict:
    """Detect faces in an image and return attributes."""
    if get_settings().mock_mode:
        return mock_detect_faces(image_path)

    client = get_rekognition_client()

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    response = client.detect_faces(
        Image={"Bytes": image_bytes},
        Attributes=["ALL"],
    )

    faces = []
    for detail in response.get("FaceDetails", []):
        faces.append({
            "confidence": detail.get("Confidence", 0),
            "quality": {
                "brightness": detail.get("Quality", {}).get("Brightness", 0),
                "sharpness": detail.get("Quality", {}).get("Sharpness", 0),
            },
            "eyes_open": detail.get("EyesOpen", {}).get("Value", False),
            "sunglasses": detail.get("Sunglasses", {}).get("Value", False),
        })

    return {"face_count": len(faces), "faces": faces}


def compare_faces_bytes(source_bytes: bytes, target_bytes: bytes) -> dict:
    """Compare two faces using raw image bytes (for liveness reference image)."""
    if get_settings().mock_mode:
        return mock_compare_faces_bytes(source_bytes, target_bytes)

    client = get_rekognition_client()

    start = time.time()
    response = client.compare_faces(
        SourceImage={"Bytes": source_bytes},
        TargetImage={"Bytes": target_bytes},
        SimilarityThreshold=0.0,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    similarity_score = 0.0
    if response.get("FaceMatches"):
        similarity_score = response["FaceMatches"][0]["Similarity"]

    return {
        "similarity_score": similarity_score,
        "face_detected_selfie": bool(response.get("SourceImageFace")),
        "face_detected_reference": len(response.get("FaceMatches", [])) > 0
            or len(response.get("UnmatchedFaces", [])) > 0,
        "processing_time_ms": elapsed_ms,
    }
