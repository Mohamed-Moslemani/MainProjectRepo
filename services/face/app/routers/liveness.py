"""Liveness session endpoints — create and get results for AWS Rekognition Face Liveness."""

import json
import os
import uuid
import logging
import boto3
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.rekognition import (
    create_liveness_session,
    get_liveness_session_results,
    compare_faces_bytes,
)
from ..config import get_settings
from ..metrics import (
    FACE_LIVENESS_SESSIONS,
    FACE_LIVENESS_RESULTS,
    FACE_LIVENESS_SCORE,
    FACE_SIMILARITY_SCORE,
    FACE_ERRORS,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/face/liveness", tags=["liveness"])


class CredentialsResponse(BaseModel):
    access_key_id: str
    secret_access_key: str
    session_token: str
    region: str


@router.get("/credentials", response_model=CredentialsResponse)
async def get_streaming_credentials():
    """Get temporary AWS credentials for Rekognition Face Liveness streaming.

    Uses STS to create short-lived credentials scoped to Rekognition streaming.
    """
    settings = get_settings()

    sts = boto3.client(
        "sts",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )

    policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["rekognition:StartFaceLivenessSession"],
            "Resource": "*",
        }],
    })

    response = sts.get_federation_token(
        Name="docflow-liveness",
        Policy=policy,
        DurationSeconds=900,
    )

    creds = response["Credentials"]
    return CredentialsResponse(
        access_key_id=creds["AccessKeyId"],
        secret_access_key=creds["SecretAccessKey"],
        session_token=creds["SessionToken"],
        region=settings.aws_region,
    )


class CreateSessionResponse(BaseModel):
    session_id: str
    region: str


class SessionResultRequest(BaseModel):
    session_id: str
    reference_doc_path: str | None = None


class SessionResultResponse(BaseModel):
    session_id: str
    status: str
    confidence: float
    liveness_passed: bool
    similarity_score: float | None = None
    face_comparison_decision: str | None = None
    reference_image_path: str | None = None
    reasons: list[str] = []


@router.post("/create-session", response_model=CreateSessionResponse)
async def create_session():
    """Create a new Rekognition Face Liveness session."""
    try:
        result = create_liveness_session()
        FACE_LIVENESS_SESSIONS.inc()
        settings = get_settings()
        return CreateSessionResponse(
            session_id=result["session_id"],
            region=settings.aws_region,
        )
    except Exception as e:
        FACE_ERRORS.labels(operation="liveness_create").inc()
        logger.error(f"Failed to create liveness session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create liveness session: {str(e)}")


@router.post("/get-results", response_model=SessionResultResponse)
async def get_results(req: SessionResultRequest):
    """Get liveness session results and optionally compare with reference document."""
    try:
        result = get_liveness_session_results(req.session_id)
    except Exception as e:
        FACE_ERRORS.labels(operation="liveness_results").inc()
        logger.error(f"Failed to get liveness results: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get liveness results: {str(e)}")

    settings = get_settings()
    status = result["status"]
    confidence = result["confidence"]
    liveness_passed = status == "SUCCEEDED" and confidence >= settings.liveness_pass_threshold * 100

    FACE_LIVENESS_RESULTS.labels(status=status).inc()
    FACE_LIVENESS_SCORE.observe(confidence / 100.0)

    reasons = []

    if status != "SUCCEEDED":
        reasons.append(f"Liveness session status: {status}")
    elif confidence < settings.liveness_pass_threshold * 100:
        reasons.append(f"Liveness confidence too low ({confidence:.1f}%, threshold: {settings.liveness_pass_threshold * 100}%)")

    # Save the reference image from the liveness session
    reference_image_path = None
    if result.get("reference_image"):
        upload_dir = os.environ.get("FACE_UPLOAD_DIR", "/app/uploads/liveness")
        os.makedirs(upload_dir, exist_ok=True)
        reference_image_path = os.path.join(upload_dir, f"{req.session_id}_{uuid.uuid4().hex}.jpg")
        with open(reference_image_path, "wb") as f:
            f.write(result["reference_image"])

    # Face comparison if reference document provided
    similarity_score = None
    face_comparison_decision = None

    if req.reference_doc_path and result.get("reference_image"):
        try:
            with open(req.reference_doc_path, "rb") as f:
                doc_bytes = f.read()

            comparison = compare_faces_bytes(
                source_bytes=result["reference_image"],
                target_bytes=doc_bytes,
            )
            similarity_score = comparison["similarity_score"]
            FACE_SIMILARITY_SCORE.observe(similarity_score)

            if similarity_score >= settings.similarity_pass_threshold:
                face_comparison_decision = "pass"
            elif similarity_score < settings.similarity_review_threshold:
                face_comparison_decision = "fail"
                reasons.append(f"Face similarity too low ({similarity_score:.1f}%)")
            else:
                face_comparison_decision = "manual_review"
                reasons.append(f"Face similarity borderline ({similarity_score:.1f}%)")

        except FileNotFoundError:
            reasons.append(f"Reference document not found: {req.reference_doc_path}")
        except Exception as e:
            FACE_ERRORS.labels(operation="compare").inc()
            logger.error(f"Face comparison failed: {e}")
            reasons.append(f"Face comparison failed: {str(e)}")

    return SessionResultResponse(
        session_id=req.session_id,
        status=status,
        confidence=confidence,
        liveness_passed=liveness_passed,
        similarity_score=similarity_score,
        face_comparison_decision=face_comparison_decision,
        reference_image_path=reference_image_path,
        reasons=reasons,
    )