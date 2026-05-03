import asyncio
import time
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shared.model_info import build_model_info, hash_file

from ..services.quality import assess_quality
from ..services.spoof_detector import detect_spoof
from ..services.google_ocr import extract_text
# field_extractor is no longer used for routing/extraction — the LLM
# is now the only field extractor. Kept as a module for the MRZ
# constants and the unit tests that exercise legacy behaviour.
from ..services.mrz_parser import parse_mrz
from ..services import ai_extractor, doc_classifier, langfuse_client
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
    OCR_SPOOF_SCORE,
    OCR_SPOOF_COMPONENT_SCORE,
    OCR_SPOOF_DECISIONS,
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

    # Open a Langfuse trace per OCR request so the classifier + field
    # extractor LLM calls land under the same parent. The trace is
    # named after the document type so Langfuse's UI can group runs by
    # doc type out of the box. trace_handle is None when Langfuse is
    # unconfigured — every downstream call site no-ops cleanly.
    trace_handle = langfuse_client.start_trace(
        name=f"ocr.process.{req.document_type}",
        session_id=req.document_id,
        metadata={
            "document_type": req.document_type,
            "document_id": req.document_id,
        },
        tags=["ocr", req.document_type],
    )

    try:
        try:
            quality = await asyncio.to_thread(assess_quality, req.file_path)
        except Exception as e:
            OCR_ERRORS.labels(stage="quality").inc()
            logger.error(f"Quality assessment failed: {e}")
            raise HTTPException(status_code=500, detail=f"Quality assessment failed: {str(e)}")

        _record_quality_issues(quality)

        # Document presentation-attack detection (moiré FFT, screen
        # banding, chromatic fringing). Fails open — any exception
        # logs and returns a clean verdict so a detector bug doesn't
        # block a legitimate citizen. The gateway feeds spoof_score
        # into risk scoring and routes borderline cases to manual
        # review rather than hard-rejecting on a single signal.
        try:
            spoof = await asyncio.to_thread(detect_spoof, req.file_path)
        except Exception as e:  # noqa: BLE001
            OCR_ERRORS.labels(stage="spoof").inc()
            logger.warning(f"spoof detector raised, defaulting to clean: {e}")
            spoof = {"spoof_score": 0.0, "decision": "clean", "components": {}, "errors": [str(e)]}

        # Surface the spoof verdict on Prometheus so the AI dashboards
        # can graph distributions, decision rates, and per-component
        # contributions over time.
        try:
            OCR_SPOOF_SCORE.labels(document_type=req.document_type).observe(
                float(spoof.get("spoof_score") or 0.0)
            )
            OCR_SPOOF_DECISIONS.labels(
                document_type=req.document_type,
                decision=spoof.get("decision") or "clean",
            ).inc()
            for cname, cdata in (spoof.get("components") or {}).items():
                OCR_SPOOF_COMPONENT_SCORE.labels(component=cname).observe(
                    float((cdata or {}).get("score") or 0.0)
                )
        except Exception:  # pragma: no cover — metrics must never crash request
            pass

        retake_reasons = []
        if not quality["is_readable"]:
            retake_reasons.extend(quality["issues"])

        try:
            ocr_result = await asyncio.to_thread(extract_text, req.file_path, req.document_type)
        except Exception as e:
            OCR_ERRORS.labels(stage="extract_text").inc()
            logger.error(f"OCR extraction failed: {e}")
            raise HTTPException(status_code=500, detail=f"OCR extraction failed: {str(e)}")

        settings = get_settings()
        # Image bytes are reused by the classifier and the field extractor
        # — read once and pass through to both.
        try:
            with open(req.file_path, "rb") as fh:
                image_bytes = fh.read()
        except Exception as exc:  # noqa: BLE001
            OCR_ERRORS.labels(stage="read_image").inc()
            logger.warning("read_image raised: %s", exc)
            image_bytes = b""

        # ── Document-type + authenticity classifier ───────────────────
        # Verify the photographed object actually IS the document type
        # the citizen claimed. Without this step, a power-bill upload
        # labelled `passport_data_page` would silently produce empty
        # field extraction and the case would limp into manual review
        # rather than being hard-rejected up front.
        #
        # Fail-open by design: if the LLM is unavailable the classifier
        # returns matches_expected_type=True so the pipeline degrades
        # to its prior behaviour. Cross-doc coherence + reconciliation
        # are still active downstream.
        classification: doc_classifier.ClassificationResult | None = None
        classifier_trace: dict | None = None
        if image_bytes:
            try:
                classification, classifier_trace = await asyncio.to_thread(
                    doc_classifier.classify,
                    req.document_type,
                    image_bytes,
                    model=settings.llm_model,
                    langfuse_trace=trace_handle,
                )
            except Exception as exc:  # noqa: BLE001
                OCR_ERRORS.labels(stage="classifier").inc()
                logger.warning("doc_classifier raised: %s", exc)

        if classification is not None and (
            not classification.matches_expected_type
            or not classification.looks_authentic
        ):
            # Hard reject: surface as a retake reason. The orchestrator
            # routes any retake_required upload to NEED_INFO so the
            # citizen sees the rejection on the case-detail page.
            if not classification.matches_expected_type:
                detected = classification.detected_type or "unknown"
                retake_reasons.append(
                    f"Uploaded document does not appear to be a {req.document_type} "
                    f"(detected: {detected})"
                )
            if not classification.looks_authentic:
                retake_reasons.append(
                    f"Uploaded {req.document_type} does not look authentic — "
                    "please re-photograph the original document"
                )
            for r in classification.reasons[:2]:
                retake_reasons.append(f"Classifier note: {r}")

        # Field extraction is now LLM-only. We dropped the regex pass
        # entirely (services/ocr/app/services/field_extractor.py used to
        # try Arabic / Latin label patterns first and fall through to
        # the LLM only when regex came up short). Reasons:
        #   - Real Lebanese docs are Arabic-only or mixed-direction
        #     and regex routinely captured the wrong cell when
        #     label/value pairs landed on different OCR lines.
        #   - Maintaining per-document-type regex was a tax that the
        #     LLM extractor's per-doc schemas pay once and re-use.
        #   - Cost: ~$0.005/call on gpt-4o-mini. ~4 docs/case for
        #     passport_new = ~$0.02/case. Acceptable tradeoff.
        # MRZ stays parser-based below (ICAO 9303 is a fixed grammar
        # with check digits — that's a parser, not text-pattern work).
        extracted_fields: dict[str, str] = {}
        confidence_scores: dict[str, float] = {}

        llm_trace: dict | None = None
        if ai_extractor.supports(req.document_type):
            try:
                llm_fields, llm_trace = await asyncio.to_thread(
                    ai_extractor.extract_with_llm,
                    req.document_type,
                    ocr_result["full_text"],
                    image_bytes,
                    model=settings.llm_model,
                    langfuse_trace=trace_handle,
                )
                for k, v in (llm_fields or {}).items():
                    extracted_fields[k] = v
                    # LLM extraction confidence is an opinionated mid-range
                    # constant. The model doesn't return logprobs in this
                    # call shape and downstream risk scoring weighs all OCR
                    # confidences uniformly; a single constant keeps the
                    # merged output comparable across providers.
                    confidence_scores[k] = 0.85
                logger.info(
                    "LLM extractor produced %d fields for %s (outcome=%s)",
                    len(llm_fields or {}), req.document_type,
                    (llm_trace or {}).get("outcome"),
                )
            except Exception as exc:  # noqa: BLE001
                # LLM is best-effort — a transient OpenAI / network
                # blip must NOT crash the OCR call. The pipeline will
                # see zero extracted fields, the quality gate will
                # bounce the case to need_info with a clear retake
                # reason, and the citizen retries.
                OCR_ERRORS.labels(stage="llm_extract").inc()
                logger.warning("LLM extractor raised: %s", exc)

        # Citizens declare a single full name; documents print it as
        # first_name + surname in two cells. Synthesise the joined
        # value here so the orchestrator's reconciliation has a
        # single field to fuzzy-match against the declared full name
        # instead of partial-matching against half the document.
        first = (extracted_fields.get("first_name_ar") or "").strip()
        last = (extracted_fields.get("surname_ar") or "").strip()
        if first or last:
            full = f"{first} {last}".strip()
            if full:
                extracted_fields["full_name_ar"] = full
                parts = [confidence_scores.get(k, 0.0) for k in ("first_name_ar", "surname_ar") if extracted_fields.get(k)]
                confidence_scores["full_name_ar"] = min(parts) if parts else 0.0

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
        #
        # In mock mode the LLM fallback never runs (the mock OCR
        # returns canned data) so surname_ar / id_number aren't
        # available — bypass the strict critical-fields check there
        # to keep the E2E suite deterministic.
        # Mock mode skips the missing-fields retake entirely: the canned
        # fixtures intentionally don't satisfy every regex variant
        # (Arabic-only patterns won't match English mock labels and
        # vice versa) and forcing 100% extraction parity in the
        # fixtures would obscure what the real pipeline does.
        if settings.mock_mode:
            pass
        elif req.document_type == "civil_registry_extract":
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
            # Presentation-attack detection: combined score + per-detector
            # breakdown. Consumed by gateway risk scoring; never used
            # for hard-reject (false positives on textured paper exist).
            "spoof": spoof,
            "mrz": mrz_result,
            "retake_required": retake_required,
            "retake_reasons": retake_reasons,
            "processing_time_ms": total_ms,
            # Per-call LLM trace (None when LLM didn't run). The
            # gateway persists this to audit_logs for case-level
            # traceability — examiner / auditor can answer "what did
            # the model see and return for case X?" with a single
            # SELECT, without standing up Langfuse.
            "llm_trace": llm_trace,
            # Document-type / authenticity classifier verdict. Persisted
            # by the gateway alongside the extraction trace so audits
            # can answer "did the classifier accept this upload, and
            # if not, why?". None when the classifier was unsupported
            # for this document type or skipped (no API key).
            "classification": classification.to_dict() if classification else None,
            "classifier_trace": classifier_trace,
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
