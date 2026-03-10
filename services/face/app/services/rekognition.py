"""AWS Rekognition face comparison service."""

import time
import logging
import boto3

from ..config import get_settings

logger = logging.getLogger(__name__)


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
    settings = get_settings()

    client = boto3.client(
        "rekognition",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )

    with open(selfie_path, "rb") as sf, open(reference_path, "rb") as rf:
        selfie_bytes = sf.read()
        reference_bytes = rf.read()

    start = time.time()

    response = client.compare_faces(
        SourceImage={"Bytes": selfie_bytes},
        TargetImage={"Bytes": reference_bytes},
        SimilarityThreshold=0.0,  # get all matches, we'll threshold ourselves
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
    settings = get_settings()

    client = boto3.client(
        "rekognition",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )

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