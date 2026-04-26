import asyncio
import time
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shared.model_info import build_model_info, hash_file

from ..services.verifier import verify
from ..config import get_settings
from ..metrics import (
    FACE_VERIFY_REQUESTS,
    FACE_VERIFY_DURATION,
    FACE_VERIFY_DECISIONS,
    FACE_SIMILARITY_SCORE,
    FACE_LIVENESS_SCORE,
    FACE_ERRORS,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/face", tags=["face"])


class VerifyRequest(BaseModel):
    case_id: str
    selfie_path: str
    reference_path: str


@router.post("/verify")
async def verify_face(req: VerifyRequest):
    FACE_VERIFY_REQUESTS.inc()
    start = time.time()
    try:
        result = await asyncio.to_thread(verify, req.selfie_path, req.reference_path)
        result["case_id"] = req.case_id

        FACE_VERIFY_DECISIONS.labels(decision=result["decision"]).inc()
        FACE_SIMILARITY_SCORE.observe(result["similarity_score"])
        FACE_LIVENESS_SCORE.observe(result["liveness_score"])

        # Reproducibility metadata — image hashes plus the model info
        # that produced this similarity / liveness score.
        settings = get_settings()
        result["selfie_hash"] = hash_file(req.selfie_path)
        result["reference_hash"] = hash_file(req.reference_path)
        result["model_info"] = build_model_info(
            service_name="face",
            provider="mock" if settings.mock_mode else "aws-rekognition",
            provider_version="mock-v1" if settings.mock_mode else "rekognition-2016-06-27",
            config={
                "similarity_threshold": getattr(settings, "similarity_threshold", None),
                "liveness_pass_threshold": getattr(settings, "liveness_pass_threshold", None),
                "aws_region": getattr(settings, "aws_region", None),
            },
        )

        return result
    except FileNotFoundError as e:
        FACE_ERRORS.labels(operation="verify").inc()
        raise HTTPException(status_code=400, detail=f"Image file not found: {e}")
    except Exception as e:
        FACE_ERRORS.labels(operation="verify").inc()
        logger.error(f"Face verification failed: {e}")
        raise HTTPException(status_code=500, detail=f"Verification failed: {str(e)}")
    finally:
        FACE_VERIFY_DURATION.observe(time.time() - start)
