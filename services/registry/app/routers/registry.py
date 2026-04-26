import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from shared.model_info import build_model_info

from ..config import get_settings
from ..db import get_db
from ..schemas import VerifyRequest, VerifyResponse
from ..services.matcher import verify as matcher_verify
from ..metrics import (
    REGISTRY_REQUESTS, REGISTRY_DURATION, REGISTRY_RESULTS, REGISTRY_CONFIDENCE,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/registry", tags=["registry"])


@router.post("/verify", response_model=VerifyResponse)
async def verify_citizen(req: VerifyRequest, db: AsyncSession = Depends(get_db)):
    """Verify a citizen's identity against the Lebanese civil registry."""
    REGISTRY_REQUESTS.inc()
    start = time.time()

    # At least one search key required — either a registry number or a name
    if not (req.registry_number or req.full_name):
        raise HTTPException(
            status_code=400,
            detail="At least one of registry_number or full_name is required",
        )

    settings = get_settings()
    try:
        result = await matcher_verify(
            db,
            req,
            exact_threshold=settings.exact_match_threshold,
            partial_threshold=settings.partial_match_threshold,
        )
    except Exception as e:
        REGISTRY_RESULTS.labels(status="error").inc()
        logger.exception("registry verification failed")
        raise HTTPException(status_code=500, detail=f"Verification failed: {e}")
    finally:
        REGISTRY_DURATION.observe(time.time() - start)

    result.processing_time_ms = int((time.time() - start) * 1000)
    result.model_info = build_model_info(
        service_name="registry",
        provider="docflow-fuzzy-matcher",
        provider_version="v1",
        config={
            "exact_match_threshold": settings.exact_match_threshold,
            "partial_match_threshold": settings.partial_match_threshold,
        },
    )
    REGISTRY_RESULTS.labels(status=result.status).inc()
    REGISTRY_CONFIDENCE.observe(result.confidence)
    return result
