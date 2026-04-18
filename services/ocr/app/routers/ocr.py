import asyncio
import time
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.quality import assess_quality
from ..services.google_ocr import extract_text
from ..services.field_extractor import extract_fields
from ..services.mrz_parser import parse_mrz
from ..config import get_settings
from ..metrics import (
    OCR_REQUESTS,
    OCR_DURATION,
    OCR_RETAKE_REQUIRED,
    OCR_CONFIDENCE,
    OCR_QUALITY_ISSUES,
    OCR_ERRORS,
    OCR_MRZ_RESULTS,
    OCR_FIELDS_EXTRACTED,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ocr", tags=["ocr"])


class ProcessRequest(BaseModel):
    document_id: str
    file_path: str
    document_type: str


def _record_quality_issues(quality: dict) -> None:
    if quality.get("is_blurry"):
        OCR_QUALITY_ISSUES.labels(issue_type="blur").inc()
    if quality.get("glare_detected"):
        OCR_QUALITY_ISSUES.labels(issue_type="glare").inc()
    if not quality.get("resolution_ok", True):
        OCR_QUALITY_ISSUES.labels(issue_type="low_resolution").inc()
    if not quality.get("angle_ok", True):
        OCR_QUALITY_ISSUES.labels(issue_type="skewed").inc()


@router.post("/process")
async def process_document(req: ProcessRequest):
    OCR_REQUESTS.labels(document_type=req.document_type).inc()
    start = time.time()

    try:
        try:
            quality = await asyncio.to_thread(assess_quality, req.file_path)
        except Exception as e:
            OCR_ERRORS.labels(stage="quality").inc()
            logger.error(f"Quality assessment failed: {e}")
            raise HTTPException(status_code=500, detail=f"Quality assessment failed: {str(e)}")

        _record_quality_issues(quality)

        retake_reasons = []
        if not quality["is_readable"]:
            retake_reasons.extend(quality["issues"])

        try:
            ocr_result = await asyncio.to_thread(extract_text, req.file_path)
        except Exception as e:
            OCR_ERRORS.labels(stage="extract_text").inc()
            logger.error(f"OCR extraction failed: {e}")
            raise HTTPException(status_code=500, detail=f"OCR extraction failed: {str(e)}")

        try:
            field_result = extract_fields(
                ocr_result["full_text"],
                req.document_type,
                ocr_result["words"],
            )
        except Exception as e:
            OCR_ERRORS.labels(stage="field_extract").inc()
            logger.error(f"Field extraction failed: {e}")
            raise HTTPException(status_code=500, detail=f"Field extraction failed: {str(e)}")

        extracted_fields = field_result["fields"]
        confidence_scores = field_result["confidence_scores"]

        OCR_FIELDS_EXTRACTED.observe(len(extracted_fields))

        nonzero_scores = [c for c in confidence_scores.values() if c > 0]
        if nonzero_scores:
            avg_conf = sum(nonzero_scores) / len(nonzero_scores)
            OCR_CONFIDENCE.observe(avg_conf)

        settings = get_settings()
        low_confidence_fields = [
            f for f, c in confidence_scores.items()
            if c < settings.min_confidence_threshold and c > 0
        ]
        if low_confidence_fields:
            retake_reasons.append(
                f"Low confidence on fields: {', '.join(low_confidence_fields)}"
            )

        missing_fields = [f for f, c in confidence_scores.items() if c == 0.0]
        if missing_fields:
            retake_reasons.append(f"Could not extract fields: {', '.join(missing_fields)}")

        mrz_result = None
        if req.document_type in ("old_passport_data_page", "passport_data_page"):
            try:
                mrz_result = parse_mrz(ocr_result["full_text"])
            except Exception as e:
                OCR_ERRORS.labels(stage="mrz").inc()
                logger.error(f"MRZ parsing raised: {e}")
                mrz_result = None

            if mrz_result:
                extracted_fields["mrz_passport_number"] = mrz_result["passport_number"]
                extracted_fields["mrz_surname"] = mrz_result["surname"]
                extracted_fields["mrz_given_names"] = mrz_result["given_names"]
                extracted_fields["mrz_date_of_birth"] = mrz_result["date_of_birth"]
                extracted_fields["mrz_expiry_date"] = mrz_result["expiry_date"]
                extracted_fields["mrz_nationality"] = mrz_result["nationality"]
                extracted_fields["mrz_sex"] = mrz_result["sex"]

                if mrz_result["all_checks_passed"]:
                    OCR_MRZ_RESULTS.labels(outcome="parsed_valid").inc()
                else:
                    OCR_MRZ_RESULTS.labels(outcome="parsed_invalid").inc()
                    retake_reasons.append("MRZ check digit validation failed")
            else:
                OCR_MRZ_RESULTS.labels(outcome="not_found").inc()
                retake_reasons.append("Could not parse MRZ from passport")

        retake_required = len(retake_reasons) > 0
        if retake_required:
            OCR_RETAKE_REQUIRED.labels(document_type=req.document_type).inc()

        total_ms = int((time.time() - start) * 1000)

        return {
            "document_id": req.document_id,
            "status": "completed",
            "extracted_fields": extracted_fields,
            "confidence_scores": confidence_scores,
            "quality": quality,
            "mrz": mrz_result,
            "retake_required": retake_required,
            "retake_reasons": retake_reasons,
            "processing_time_ms": total_ms,
        }
    finally:
        OCR_DURATION.labels(document_type=req.document_type).observe(time.time() - start)


@router.get("/health")
async def health():
    return {"status": "healthy", "service": "ocr"}
