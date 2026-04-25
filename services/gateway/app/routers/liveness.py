"""Gateway liveness endpoints — proxy to face service for Rekognition Face Liveness."""

import httpx
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from shared.request_id import propagate_headers

from ..db import get_db
from ..config import get_settings
from ..models.user import User
from ..models.case import Case
from ..models.document import Document
from ..middleware.auth import get_current_user
from ..services.audit import log_action

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/liveness", tags=["liveness"])


class CredentialsResponse(BaseModel):
    access_key_id: str
    secret_access_key: str
    session_token: str
    region: str


@router.get("/credentials", response_model=CredentialsResponse)
async def get_liveness_credentials(
    user: User = Depends(get_current_user),
):
    """Get temporary AWS credentials for the frontend liveness component."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=propagate_headers()) as client:
            resp = await client.get(
                f"{settings.face_service_url}/api/v1/face/liveness/credentials"
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"Failed to get liveness credentials: {e}")
        raise HTTPException(status_code=502, detail="Face service unavailable")


class CreateSessionRequest(BaseModel):
    case_id: str


class CreateSessionResponse(BaseModel):
    session_id: str
    region: str


class GetResultsRequest(BaseModel):
    case_id: str
    session_id: str


class LivenessResultResponse(BaseModel):
    session_id: str
    status: str
    confidence: float
    liveness_passed: bool
    similarity_score: float | None = None
    face_comparison_decision: str | None = None
    reasons: list[str] = []


@router.post("/create-session", response_model=CreateSessionResponse)
async def create_liveness_session(
    req: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a Rekognition Face Liveness session for a case."""
    # Verify case ownership and status
    result = await db.execute(select(Case).where(Case.id == req.case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if case.status not in ("draft", "need_info"):
        raise HTTPException(status_code=400, detail="Liveness can only be done in draft or need_info status")

    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=propagate_headers()) as client:
            resp = await client.post(
                f"{settings.face_service_url}/api/v1/face/liveness/create-session"
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"Failed to create liveness session: {e}")
        raise HTTPException(status_code=502, detail="Face service unavailable")

    # Store session ID on the case
    case.liveness_session_id = data["session_id"]
    await db.commit()

    await log_action(
        db, "liveness_session_created", user_id=user.id, case_id=case.id,
        details={"session_id": data["session_id"]},
    )

    return CreateSessionResponse(
        session_id=data["session_id"],
        region=data["region"],
    )


@router.post("/get-results", response_model=LivenessResultResponse)
async def get_liveness_results(
    req: GetResultsRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get liveness results and trigger face comparison against reference doc."""
    result = await db.execute(select(Case).where(Case.id == req.case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if case.liveness_session_id != req.session_id:
        raise HTTPException(status_code=400, detail="Session ID mismatch")

    # Find the reference document for face comparison (per policy)
    from ..services.policy import get_policy
    policy = get_policy(case.service_type)
    reference_doc_path = None

    if policy.get("face_match_required"):
        ref_doc_type = policy.get("face_reference_doc")
        if ref_doc_type:
            ref_doc_type_val = ref_doc_type.value if hasattr(ref_doc_type, 'value') else ref_doc_type
            doc_result = await db.execute(
                select(Document).where(
                    Document.case_id == case.id,
                    Document.document_type == ref_doc_type_val,
                )
            )
            ref_doc = doc_result.scalar_one_or_none()
            if ref_doc:
                reference_doc_path = ref_doc.file_path

    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=propagate_headers()) as client:
            payload = {
                "session_id": req.session_id,
                "reference_doc_path": reference_doc_path,
            }
            resp = await client.post(
                f"{settings.face_service_url}/api/v1/face/liveness/get-results",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"Failed to get liveness results: {e}")
        raise HTTPException(status_code=502, detail="Face service unavailable")

    # Store liveness result on the case
    case.liveness_result = {
        "session_id": data["session_id"],
        "status": data["status"],
        "confidence": data["confidence"],
        "liveness_passed": data["liveness_passed"],
        "similarity_score": data.get("similarity_score"),
        "face_comparison_decision": data.get("face_comparison_decision"),
        "reference_image_path": data.get("reference_image_path"),
        "reasons": data.get("reasons", []),
    }
    await db.commit()

    await log_action(
        db, "liveness_completed", user_id=user.id, case_id=case.id,
        details={
            "status": data["status"],
            "confidence": data["confidence"],
            "liveness_passed": data["liveness_passed"],
            "similarity_score": data.get("similarity_score"),
        },
    )

    return LivenessResultResponse(
        session_id=data["session_id"],
        status=data["status"],
        confidence=data["confidence"],
        liveness_passed=data["liveness_passed"],
        similarity_score=data.get("similarity_score"),
        face_comparison_decision=data.get("face_comparison_decision"),
        reasons=data.get("reasons", []),
    )