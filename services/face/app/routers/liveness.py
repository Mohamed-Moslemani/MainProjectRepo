"""Liveness session endpoints — create and get results for AWS Rekognition Face Liveness."""

import asyncio
import json
import os
import uuid
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..clients import get_sts_client
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
    # Amplify v6 FaceLivenessDetector's credentialProvider expects
    # an `expiration` to know when to refresh. Without it, the SDK
    # treats the creds as already-expired and gets stuck retrying
    # the WebSocket handshake — surfaces in the UI as a permanent
    # "Connecting…". STS GetFederationToken always returns this
    # field, we just weren't passing it through.
    expiration: str


@router.get("/credentials", response_model=CredentialsResponse)
async def get_streaming_credentials():
    """Get temporary AWS credentials for Rekognition Face Liveness streaming.

    Uses STS to create short-lived credentials scoped to Rekognition streaming.
    """
    settings = get_settings()
    sts = get_sts_client()

    policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["rekognition:StartFaceLivenessSession"],
            "Resource": "*",
        }],
    })

    try:
        response = await asyncio.to_thread(
            sts.get_federation_token,
            Name="docflow-liveness",
            Policy=policy,
            DurationSeconds=900,
        )
    except Exception as e:
        FACE_ERRORS.labels(operation="sts_federation").inc()
        logger.error(f"STS federation token failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to obtain liveness credentials: {str(e)}")

    creds = response["Credentials"]
    return CredentialsResponse(
        access_key_id=creds["AccessKeyId"],
        secret_access_key=creds["SecretAccessKey"],
        session_token=creds["SessionToken"],
        region=settings.aws_region,
        # ISO-8601 with timezone — what Amplify's credentialProvider
        # contract expects on the JS side.
        expiration=creds["Expiration"].isoformat(),
    )


class CreateSessionResponse(BaseModel):
    session_id: str
    region: str


class SessionResultRequest(BaseModel):
    session_id: str
    reference_doc_path: str | None = None
    # Optional fallback references tried in order if the primary
    # reference returned no detected face. Real-world Lebanese civil
    # registry extracts can be tilted, glared, or partly cropped —
    # the photo on the form is small and CompareFaces sometimes
    # fails to detect it. The pipeline falls back to the next doc
    # (typically national_id_front) before declaring the comparison
    # unrecoverable.
    fallback_doc_paths: list[str] = []


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
        result = await asyncio.to_thread(create_liveness_session)
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
        result = await asyncio.to_thread(get_liveness_session_results, req.session_id)
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

    reference_image_path = None
    if result.get("reference_image"):
        upload_dir = os.environ.get("FACE_UPLOAD_DIR", "/app/uploads/liveness")
        await asyncio.to_thread(os.makedirs, upload_dir, exist_ok=True)
        reference_image_path = os.path.join(upload_dir, f"{req.session_id}_{uuid.uuid4().hex}.jpg")

        def _write_ref(path: str, data: bytes) -> None:
            with open(path, "wb") as f:
                f.write(data)

        await asyncio.to_thread(_write_ref, reference_image_path, result["reference_image"])

    similarity_score = None
    face_comparison_decision = None
    matched_reference_path = None

    # Try the primary reference doc first, then each fallback in order.
    # We attempt the next fallback ONLY when CompareFaces returned
    # no detected face on the reference (face_detected_reference=False).
    # Once a face is detected on a reference we trust that comparison
    # whether it scored high or low — falling back further would let
    # a low-similarity doc be silently swapped for a higher-similarity
    # one, which defeats the verification.
    candidate_paths = [p for p in (
        [req.reference_doc_path] + (req.fallback_doc_paths or [])
    ) if p]

    if candidate_paths and result.get("reference_image"):
        def _read_doc(path: str) -> bytes:
            with open(path, "rb") as f:
                return f.read()

        for ref_path in candidate_paths:
            try:
                doc_bytes = await asyncio.to_thread(_read_doc, ref_path)
                comparison = await asyncio.to_thread(
                    compare_faces_bytes,
                    result["reference_image"],
                    doc_bytes,
                )
                if not comparison.get("face_detected_reference"):
                    # No face on this reference — try the next one.
                    logger.info(
                        "No face detected on reference %s, trying next fallback",
                        ref_path,
                    )
                    continue
                similarity_score = comparison["similarity_score"]
                matched_reference_path = ref_path
                FACE_SIMILARITY_SCORE.observe(similarity_score)
                break
            except FileNotFoundError:
                reasons.append(f"Reference document not found: {ref_path}")
                continue
            except Exception as e:
                FACE_ERRORS.labels(operation="compare").inc()
                logger.error(f"Face comparison failed for {ref_path}: {e}")
                reasons.append(f"Face comparison failed: {str(e)}")
                continue

        if similarity_score is None:
            # No reference (primary or fallback) had a detectable face.
            # That's not the citizen's fault — route to manual review
            # rather than auto-rejecting on a missing-face technicality.
            face_comparison_decision = "manual_review"
            reasons.append(
                "Could not detect a face on any reference document — "
                "manual review required"
            )
        elif similarity_score >= settings.similarity_pass_threshold:
            face_comparison_decision = "pass"
        elif similarity_score < settings.similarity_review_threshold:
            face_comparison_decision = "fail"
            reasons.append(f"Face similarity too low ({similarity_score:.1f}%)")
        else:
            face_comparison_decision = "manual_review"
            reasons.append(f"Face similarity borderline ({similarity_score:.1f}%)")

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
