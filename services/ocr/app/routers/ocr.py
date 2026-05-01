import asyncio
import time
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shared.model_info import build_model_info, hash_file

from ..services.quality import assess_quality
from ..services.google_ocr import extract_text
from ..services.field_extractor import extract_fields
from ..services.mrz_parser import parse_mrz
from ..services import ai_extractor
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
            ocr_result = await asyncio.to_thread(extract_text, req.file_path, req.document_type)
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

        settings = get_settings()

        # ── LLM extraction ──────────────────────────────────────
        # Lebanese civil-status docs are 3-column tables whose
        # label/value pairs land on different OCR lines — regex
        # frequently grabs the wrong cell (e.g. "father_name" picks
        # up "محل الولادة" because it follows the label spatially
        # but not by the line-flow regex assumes). For these doc
        # types we let the LLM extract the canonical truth and
        # OVERWRITE the regex output rather than treating it as
        # fallback. Regex is kept ONLY for fixed-grammar docs
        # (passport MRZ) where it's reliable and cheap.
        #
        # For other table-shaped docs (national_id_*, old_id_*) the
        # LLM still runs but only as a fallback when regex returned
        # too few fields, so we don't pay LLM cost on every call.
        ALWAYS_LLM = {"civil_registry_extract"}

        if settings.llm_fallback_enabled and ai_extractor.supports(req.document_type):
            should_call_llm = (
                req.document_type in ALWAYS_LLM
                or len(extracted_fields) < settings.llm_fallback_min_fields
            )
            if should_call_llm:
                try:
                    with open(req.file_path, "rb") as fh:
                        image_bytes = fh.read()
                    llm_fields = await asyncio.to_thread(
                        ai_extractor.extract_with_llm,
                        req.document_type,
                        ocr_result["full_text"],
                        image_bytes,
                        model=settings.llm_model,
                    )
                    if llm_fields:
                        force_overwrite = req.document_type in ALWAYS_LLM
                        for k, v in llm_fields.items():
                            if force_overwrite or k not in extracted_fields or not extracted_fields[k]:
                                extracted_fields[k] = v
                                # LLM extraction confidence is opinionated — we use a
                                # mid-range constant rather than a model-reported
                                # logprob. Risk scoring downstream weighs all OCR
                                # confidences uniformly; this keeps the merged
                                # output comparable.
                                confidence_scores[k] = 0.85
                        logger.info(
                            "LLM extractor produced %d fields for %s (overwrite=%s)",
                            len(llm_fields), req.document_type, force_overwrite,
                        )
                except Exception as exc:  # noqa: BLE001
                    # LLM is best-effort — never crash the OCR call
                    # because it failed. The regex-only output stays.
                    OCR_ERRORS.labels(stage="llm_fallback").inc()
                    logger.warning("LLM extractor raised: %s", exc)

        OCR_FIELDS_EXTRACTED.observe(len(extracted_fields))

        nonzero_scores = [c for c in confidence_scores.values() if c > 0]
        if nonzero_scores:
            avg_conf = sum(nonzero_scores) / len(nonzero_scores)
            OCR_CONFIDENCE.observe(avg_conf)

        low_confidence_fields = [
            f for f, c in confidence_scores.items()
            if c < settings.min_confidence_threshold and c > 0
        ]
        if low_confidence_fields:
            retake_reasons.append(
                f"Low confidence on fields: {', '.join(low_confidence_fields)}"
            )

        # Civil-registry extracts have fields whose value cells the
        # OCR routinely skips (full_name_ar in particular — the
        # citizen photo overlaps with the first-name row geometry).
        # Don't bounce a doc that produced *most* fields just
        # because OCR couldn't read every cell. Critical fields
        # (surname, ID number, DOB) being missing is the trigger;
        # everything else is informational.
        if req.document_type == "civil_registry_extract":
            critical = ("surname_ar", "id_number", "date_of_birth")
            missing_critical = [
                f for f in critical
                if confidence_scores.get(f, 0.0) == 0.0
            ]
            if missing_critical:
                retake_reasons.append(
                    f"Could not extract fields: {', '.join(missing_critical)}"
                )
        else:
            missing_fields = [f for f, c in confidence_scores.items() if c == 0.0]
            if missing_fields:
                retake_reasons.append(
                    f"Could not extract fields: {', '.join(missing_fields)}"
                )

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

        settings_snapshot = get_settings()
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
            # Reproducibility metadata. The image hash + this dict
            # together let an investigator replay the exact same
            # inputs through the same code months later.
            "input_hash": hash_file(req.file_path),
            "model_info": build_model_info(
                service_name="ocr",
                provider="mock" if settings_snapshot.mock_mode else "google-cloud-vision",
                provider_version="mock-v1" if settings_snapshot.mock_mode else "v1",
                config={
                    "min_confidence_threshold": settings_snapshot.min_confidence_threshold,
                    "blur_threshold": settings_snapshot.blur_threshold,
                    "min_resolution": [
                        settings_snapshot.min_resolution_width,
                        settings_snapshot.min_resolution_height,
                    ],
                },
            ),
        }
    finally:
        OCR_DURATION.labels(document_type=req.document_type).observe(time.time() - start)


@router.get("/health")
async def health():
    return {"status": "healthy", "service": "ocr"}
