import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.verifier import verify

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/face", tags=["face"])


class VerifyRequest(BaseModel):
    case_id: str
    selfie_path: str
    reference_path: str


@router.post("/verify")
async def verify_face(req: VerifyRequest):
    try:
        result = verify(req.selfie_path, req.reference_path)
        result["case_id"] = req.case_id
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"Image file not found: {e}")
    except Exception as e:
        logger.error(f"Face verification failed: {e}")
        raise HTTPException(status_code=500, detail=f"Verification failed: {str(e)}")
