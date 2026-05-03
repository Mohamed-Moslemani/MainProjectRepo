"""Orchestrator - runs the full processing pipeline for a submitted case.

Pipeline:
  1. OCR extraction on all applicable documents
  2. Face verification (selfie vs reference doc)
  3. Reconciliation (declared fields vs OCR fields)
  4. Risk scoring
  5. State transition based on results
"""

import httpx
import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from shared.request_id import propagate_headers

from ..config import get_settings
from ..models.case import Case
from ..models.document import Document
from ..models.ocr_result import OCRResult
from ..models.face_result import FaceResult
from .case_machine import can_transition
from .policy import get_policy
from .reconciliation import reconcile
from .risk import compute_risk_score
from .audit import log_action
from .email import send_case_status_email
from ..models.user import User
from ..metrics import (
    PIPELINE_DURATION, PIPELINE_DECISIONS, RISK_SCORE,
    CASE_STATUS_TRANSITIONS, EXTERNAL_CALL_DURATION, EXTERNAL_CALL_ERRORS,
    RECONCILIATION_INTEGRITY, RECONCILIATION_RESULTS, RECONCILIATION_MISMATCHES,
)

logger = logging.getLogger(__name__)


async def _pick_least_busy(db: AsyncSession, mukhtars: list) -> User | None:
    """Pick the mukhtar with the fewest pending cases."""
    best = None
    min_count = float("inf")
    for m in mukhtars:
        count_result = await db.execute(
            select(func.count(Case.id)).where(
                Case.mukhtar_id == m.id,
                Case.status == "pending_mukhtar",
            )
        )
        count = count_result.scalar() or 0
        if count < min_count:
            min_count = count
            best = m
    return best


async def _assign_mukhtar(db: AsyncSession, case: Case) -> bool:
    """Auto-assign a mukhtar based on the citizen's municipality.

    Matching priority:
      1. Municipality-level match (most precise)
      2. District-level fallback (if no mukhtar in that municipality)
      3. Load-balanced across matches (fewest pending cases)
    """
    declared = case.declared_fields or {}
    municipality = declared.get("municipality", "")
    registry_place = declared.get("registry_place", "")

    # Try from user profile if not in declared fields
    if not registry_place:
        user_result = await db.execute(select(User).where(User.id == case.user_id))
        user = user_result.scalar_one_or_none()
        if user:
            registry_place = user.registry_place or ""
            municipality = municipality or user.municipality or ""

    if not registry_place:
        logger.warning(f"No registry_place for case {case.id}, cannot assign mukhtar")
        return False

    mukhtars = []

    # 1. Try municipality-level match first
    if municipality:
        result = await db.execute(
            select(User)
            .where(User.role == "mukhtar")
            .where(func.lower(User.municipality) == municipality.lower())
        )
        mukhtars = list(result.scalars().all())

    # 2. Fallback to district-level match
    if not mukhtars:
        result = await db.execute(
            select(User)
            .where(User.role == "mukhtar")
            .where(func.lower(User.registry_place) == registry_place.lower())
        )
        mukhtars = list(result.scalars().all())

    if not mukhtars:
        logger.warning(f"No mukhtar found for municipality={municipality}, district={registry_place}")
        return False

    best = await _pick_least_busy(db, mukhtars)
    if best:
        case.mukhtar_id = best.id
        return True
    return False


async def call_ocr_service(document: Document) -> dict:
    import time as _time
    settings = get_settings()
    start = _time.time()
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=propagate_headers()) as client:
            response = await client.post(
                f"{settings.ocr_service_url}/api/v1/ocr/process",
                json={
                    "document_id": document.id,
                    "file_path": document.file_path,
                    "document_type": document.document_type,
                    # case_id lets OCR's Langfuse trace use the same
                    # session_id as the gateway's case.evaluation trace
                    # so both timelines collapse into one Langfuse session.
                    "case_id": document.case_id,
                },
            )
            response.raise_for_status()
            return response.json()
    except Exception:
        EXTERNAL_CALL_ERRORS.labels(service="ocr").inc()
        raise
    finally:
        EXTERNAL_CALL_DURATION.labels(service="ocr").observe(_time.time() - start)


async def call_face_service(case_id: str, selfie_path: str, reference_path: str) -> dict:
    import time as _time
    settings = get_settings()
    start = _time.time()
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=propagate_headers()) as client:
            response = await client.post(
                f"{settings.face_service_url}/api/v1/face/verify",
                json={
                    "case_id": case_id,
                    "selfie_path": selfie_path,
                    "reference_path": reference_path,
                },
            )
        response.raise_for_status()
        return response.json()
    except Exception:
        EXTERNAL_CALL_ERRORS.labels(service="face").inc()
        raise
    finally:
        EXTERNAL_CALL_DURATION.labels(service="face").observe(_time.time() - start)


async def call_registry_service(declared: dict) -> dict:
    """Cross-check declared identity fields against the civil registry.

    Returns the raw service response. On failure (service down, network
    error), returns a best-effort "error" result so the pipeline can
    continue in degraded mode rather than crashing.
    """
    import time as _time
    settings = get_settings()
    start = _time.time()
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=propagate_headers()) as client:
            response = await client.post(
                f"{settings.registry_service_url}/api/v1/registry/verify",
                json={
                    "full_name": declared.get("full_name"),
                    "father_name": declared.get("father_name"),
                    "mother_name": declared.get("mother_name"),
                    "date_of_birth": declared.get("date_of_birth"),
                    "place_of_birth": declared.get("place_of_birth"),
                    "registry_number": declared.get("registry_number"),
                    "registry_place": declared.get("registry_place"),
                },
            )
            response.raise_for_status()
            return response.json()
    except Exception as e:
        EXTERNAL_CALL_ERRORS.labels(service="registry").inc()
        logger.warning("Registry service unavailable, continuing with no_match: %s", e)
        # Degrade gracefully — treat as no_match so the case flows to
        # manual_review rather than crashing the submit.
        return {
            "status": "error",
            "confidence": 0.0,
            "matched_citizen": None,
            "field_scores": {},
            "reasons": [f"Registry service unavailable: {e}"],
            "processing_time_ms": 0,
        }
    finally:
        EXTERNAL_CALL_DURATION.labels(service="registry").observe(_time.time() - start)


def _transition(case: Case, new_status: str, message: str):
    """Helper to transition case and record history."""
    if can_transition(case.status, new_status):
        case.status = new_status
        case.status_history = case.status_history + [{
            "status": new_status,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]


def _worst_quality(*qs: dict | None) -> dict:
    """Pick the worst quality assessment across the passport halves.

    Risk scoring should reflect the weakest link — if the bottom half
    is blurry but the top is clean, the case still has an unreadable
    MRZ. We OR the boolean flags and take min/max accordingly.
    """
    qs = [q for q in qs if q]
    if not qs:
        return {}
    worst: dict = {
        "is_readable":     all(q.get("is_readable", True) for q in qs),
        "is_blurry":       any(q.get("is_blurry") for q in qs),
        "glare_detected":  any(q.get("glare_detected") for q in qs),
        "angle_ok":        all(q.get("angle_ok", True) for q in qs),
        "resolution_ok":   all(q.get("resolution_ok", True) for q in qs),
        # Numeric scores: take the worst (highest blur, lowest sharpness).
        "blur_score":      max((q.get("blur_score") or 0.0) for q in qs),
        # Issues: union, deduped.
        "issues":          sorted({i for q in qs for i in (q.get("issues") or [])}),
    }
    return worst


def _worst_spoof(*spoofs: dict | None) -> dict:
    """Pick the most spoof-suspicious result across the halves."""
    spoofs = [s for s in spoofs if s]
    if not spoofs:
        return {"spoof_score": 0.0, "decision": "clean", "components": {}, "errors": []}
    # The half with the highest spoof_score is the worse signal.
    worst = max(spoofs, key=lambda s: s.get("spoof_score") or 0.0)
    return worst


def _mrz_llm_vs_parser_mismatches(
    mrz: dict | None, llm_fields: dict | None,
) -> dict[str, str]:
    """Compare ICAO-parser MRZ output against the LLM's MRZ transcription.

    Both signals come from the same bottom-half capture but are
    derived independently. Disagreement is suspicious — either the
    capture is too poor for one path to read it correctly, or the
    document has been tampered with.

    Returns {field_name: "parser=X, llm=Y"} for each disagreeing
    field. Missing values on either side are skipped (we can't
    score what isn't there).
    """
    if not mrz or not llm_fields:
        return {}
    pairs = (
        ("passport_number", "mrz_llm_passport_number"),
        ("date_of_birth",   "mrz_llm_date_of_birth"),
        ("expiry_date",     "mrz_llm_date_of_expiry"),
        ("nationality",     "mrz_llm_nationality"),
        ("sex",             "mrz_llm_sex"),
    )
    out: dict[str, str] = {}
    for parser_key, llm_key in pairs:
        a = (mrz.get(parser_key) or "").strip().upper()
        b = (llm_fields.get(llm_key) or "").strip().upper()
        if a and b and a != b:
            out[parser_key] = f"parser={a}, llm={b}"
    return out


async def process_case(db: AsyncSession, case: Case) -> dict:
    """Run full processing pipeline on a submitted case."""
    import time as _time
    from . import langfuse_client as _lf

    pipeline_start = _time.time()
    policy = get_policy(case.service_type)
    if not policy:
        logger.error(f"No policy for service type: {case.service_type}")
        return {"error": "Unknown service type"}

    # Case-level Langfuse trace. Every Mimir-style audit log we already
    # write also gets a Langfuse span/score so a reviewer can replay
    # the entire AI pipeline from one place. session_id=case.id ties
    # this trace to OCR sub-traces (which use the same session_id),
    # so Langfuse groups them under one timeline. Persisted onto the
    # case so a later mukhtar decision can score the same trace.
    case_trace = _lf.start_trace(
        name=f"case.evaluation.{case.service_type}",
        user_id=case.user_id,
        session_id=case.id,
        metadata={
            "case_id": case.id,
            "tracking_id": case.tracking_id,
            "service_type": case.service_type,
        },
        tags=["docflow", "case", case.service_type],
    )
    case_trace_id = (
        getattr(case_trace, "id", None) or getattr(case_trace, "trace_id", None)
        if case_trace is not None else None
    )

    docs_result = await db.execute(
        select(Document).where(Document.case_id == case.id)
    )
    documents = {doc.document_type: doc for doc in docs_result.scalars().all()}

    results = {
        "ocr_results": {},
        "face_result": None,
        "reconciliation": None,
        "risk": None,
        "issues": [],
    }
    # Captured per-stage and persisted on case.model_versions at the
    # end of the pipeline. Investigators reading audit trails months
    # later use this to replay decisions against the exact same
    # provider + config that produced them.
    model_versions: dict[str, dict] = {}

    # ---- Step 1: OCR extraction ----
    ocr_documents = policy.get("ocr_documents", [])
    all_extracted_fields = {}
    all_confidence_scores = {}
    # Per-doc retake reasons collected from the OCR service. Quality is a
    # *gate*, not a risk signal: any retake_required short-circuits the
    # pipeline and routes the case back to the citizen (NEED_INFO), so the
    # officer queue never sees blurry uploads.
    retake_findings: list[dict] = []

    for doc_type in ocr_documents:
        doc_type_val = doc_type.value if hasattr(doc_type, 'value') else doc_type
        doc = documents.get(doc_type_val)
        if not doc:
            results["issues"].append(f"Missing document: {doc_type_val}")
            continue

        try:
            ocr_data = await call_ocr_service(doc)
            # Re-uploaded documents keep the same document_id but the
            # underlying file changed; the previous OCR row from the
            # failed first attempt would otherwise collide with the
            # unique constraint on ocr_results.document_id. Wipe the
            # stale row before inserting the fresh one so a retake
            # cycle is idempotent across submits.
            from sqlalchemy import delete as sa_delete
            await db.execute(
                sa_delete(OCRResult).where(OCRResult.document_id == doc.id)
            )
            ocr_record = OCRResult(
                document_id=doc.id,
                extracted_fields=ocr_data.get("extracted_fields", {}),
                confidence_scores=ocr_data.get("confidence_scores", {}),
                quality_assessment=ocr_data.get("quality", {}),
                retake_required=ocr_data.get("retake_required", False),
                retake_reasons=ocr_data.get("retake_reasons", []),
                processing_time_ms=ocr_data.get("processing_time_ms"),
            )
            db.add(ocr_record)
            results["ocr_results"][doc_type_val] = ocr_data

            # Aggregate fields
            all_extracted_fields.update(ocr_data.get("extracted_fields", {}))
            all_confidence_scores.update(ocr_data.get("confidence_scores", {}))

            # First OCR call wins the model_info entry (all docs use the
            # same OCR provider; this captures it once). Image hashes
            # are per-doc and stored on the OCRResult row.
            if "ocr" not in model_versions and ocr_data.get("model_info"):
                model_versions["ocr"] = ocr_data["model_info"]
            if ocr_data.get("input_hash"):
                ocr_record.input_hash = ocr_data["input_hash"]

            # Collect retake findings — short-circuit at the end of the loop
            # if any required doc failed quality.
            if ocr_data.get("retake_required"):
                retake_findings.append({
                    "document_type": doc_type_val,
                    "reasons": ocr_data.get("retake_reasons", []),
                })

            await log_action(
                db, "ocr_completed", case_id=case.id,
                details={
                    "document_id": doc.id,
                    "document_type": doc_type_val,
                    "extracted_fields": ocr_data.get("extracted_fields", {}),
                    "confidence_scores": ocr_data.get("confidence_scores", {}),
                    "quality": ocr_data.get("quality", {}),
                    "mrz": ocr_data.get("mrz"),
                    "retake_required": ocr_data.get("retake_required", False),
                    "retake_reasons": ocr_data.get("retake_reasons", []),
                    "processing_time_ms": ocr_data.get("processing_time_ms"),
                },
            )

            # Per-call LLM trace gets its own audit_log row so an
            # auditor can answer "what did the model see + return
            # for case X?" with one SELECT. Skipped-outcome traces
            # (no_key / unsupported / no_package) carry no prompt
            # or response — they're still recorded so the absence
            # of an LLM call is itself part of the trail.
            llm_trace = ocr_data.get("llm_trace")
            if llm_trace:
                await log_action(
                    db, "llm_extraction_completed", case_id=case.id,
                    details={
                        "document_id": doc.id,
                        "document_type": doc_type_val,
                        **llm_trace,
                    },
                )

            # Document-type / authenticity classifier outcome. Recorded
            # on every call so audits can show the verdict that gated
            # acceptance — including the happy path, where it confirms
            # the upload looked right. classifier_trace carries prompt
            # + raw response (image bytes excluded).
            classification = ocr_data.get("classification")
            classifier_trace = ocr_data.get("classifier_trace")
            if classification or classifier_trace:
                await log_action(
                    db, "doc_classification_completed", case_id=case.id,
                    details={
                        "document_id": doc.id,
                        "document_type": doc_type_val,
                        "classification": classification,
                        "trace": classifier_trace,
                    },
                )

        except Exception as e:
            logger.error(f"OCR failed for {doc_type_val}: {e}")
            results["issues"].append(f"OCR failed for {doc_type_val}")
            # Treat OCR service failure as a retake/resubmit need — the
            # citizen can't fix infra issues, but routing to NEED_INFO keeps
            # the case out of the officer queue and lets us retry on resubmit.
            retake_findings.append({
                "document_type": doc_type_val,
                "reasons": [f"OCR service unavailable for {doc_type_val}"],
            })
            await log_action(
                db, "ocr_failure", case_id=case.id,
                details={"document_type": doc_type_val, "error": str(e)},
            )

    # ---- Quality gate ----
    # If any required document needs a retake (blur, glare, low-res, skew,
    # OCR failure), short-circuit and bounce the case back to the citizen.
    # We do NOT run face / registry / risk on un-readable documents — those
    # signals would be unreliable and would pollute officer queues with
    # cases that just need a better photo.
    if retake_findings:
        case.retake_reasons = retake_findings
        results["retake_findings"] = retake_findings
        results["routing"] = "needs_info"

        # Persist whatever model_versions we've captured so far (just
        # OCR at this stage) so even bounced cases have provenance —
        # important if the same image keeps getting bounced and we
        # need to reproduce the OCR run.
        if model_versions:
            case.model_versions = model_versions

        CASE_STATUS_TRANSITIONS.labels(
            from_status="submitted", to_status="need_info",
        ).inc()
        _transition(
            case, "need_info",
            "Document quality gate failed — citizen must retake",
        )
        await db.commit()

        await log_action(
            db, "quality_gate_failed", case_id=case.id,
            details={"retake_findings": retake_findings},
        )

        PIPELINE_DURATION.labels(service_type=case.service_type).observe(
            _time.time() - pipeline_start
        )
        PIPELINE_DECISIONS.labels(decision="needs_info").inc()
        return results

    # All required docs passed the quality gate; clear any prior retake state
    # so a previously-bounced case that re-submitted with better photos
    # isn't carrying stale reasons.
    if case.retake_reasons:
        case.retake_reasons = None

    # ---- Step 1.4: Merge passport top+bottom halves ──────────────
    # The data page is captured as two photos (top = visual fields +
    # photo, bottom = MRZ). Each half is OCR'd with its own schema.
    # Downstream consumers (cross_doc_check, eligibility rules, MRZ
    # lookup) expect a single logical `passport_data_page` /
    # `old_passport_data_page` entry, so we synthesise one here.
    #
    # Merge strategy:
    #   - extracted_fields: union; top wins on key collisions because
    #     the top half holds the printed visual values and the bottom
    #     half exposes only `mrz_*` / `mrz_llm_*` keys that don't
    #     collide with top fields.
    #   - mrz: taken from the bottom half (only the bottom carries it).
    #   - quality / spoof: worst of the two halves so risk scoring
    #     reflects the weakest link.
    #   - retake_required / retake_reasons: union (already gated above).
    #   - llm_trace: the bottom-half MRZ-LLM trace is preserved as
    #     `llm_trace_bottom` for audit; top trace is the primary.
    for legacy_key, top_key, bottom_key in (
        ("passport_data_page",
         "passport_data_page_top", "passport_data_page_bottom"),
        ("old_passport_data_page",
         "old_passport_data_page_top", "old_passport_data_page_bottom"),
    ):
        top = results["ocr_results"].get(top_key)
        bottom = results["ocr_results"].get(bottom_key)
        if not (top or bottom):
            continue

        merged_fields: dict[str, str] = {}
        merged_conf: dict[str, float] = {}
        if bottom:
            merged_fields.update(bottom.get("extracted_fields", {}) or {})
            merged_conf.update(bottom.get("confidence_scores", {}) or {})
        if top:
            # top wins — printed visual fields are authoritative over
            # any duplicate that might come from a bottom-half misread.
            merged_fields.update(top.get("extracted_fields", {}) or {})
            merged_conf.update(top.get("confidence_scores", {}) or {})

        merged: dict = {
            "document_id": (top or bottom).get("document_id"),
            "status": "completed",
            "extracted_fields": merged_fields,
            "confidence_scores": merged_conf,
            "quality": _worst_quality(
                (top or {}).get("quality"), (bottom or {}).get("quality"),
            ),
            "spoof": _worst_spoof(
                (top or {}).get("spoof"), (bottom or {}).get("spoof"),
            ),
            "mrz": (bottom or {}).get("mrz"),
            "retake_required": bool(
                (top or {}).get("retake_required")
                or (bottom or {}).get("retake_required")
            ),
            "retake_reasons": [
                *((top or {}).get("retake_reasons") or []),
                *((bottom or {}).get("retake_reasons") or []),
            ],
            "processing_time_ms": (
                ((top or {}).get("processing_time_ms") or 0)
                + ((bottom or {}).get("processing_time_ms") or 0)
            ),
            "llm_trace": (top or {}).get("llm_trace"),
            "llm_trace_bottom": (bottom or {}).get("llm_trace"),
            "classification": (top or {}).get("classification"),
            "classifier_trace": (top or {}).get("classifier_trace"),
            # Composite hash — both halves contribute. Same hash =
            # same physical pages photographed, lets the auditor
            # reproduce the merged outcome deterministically.
            "input_hash": "+".join(filter(None, [
                (top or {}).get("input_hash"), (bottom or {}).get("input_hash"),
            ])) or None,
            "model_info": (top or {}).get("model_info") or (bottom or {}).get("model_info"),
        }

        # Sanity-check: the LLM's transcription of the MRZ vs the
        # ICAO parser. Disagreement on passport_number / DOB / expiry
        # is a fraud / bad-capture signal — surface as a reason so
        # risk scoring + the officer review can act on it.
        mismatches = _mrz_llm_vs_parser_mismatches(
            mrz=(bottom or {}).get("mrz"),
            llm_fields=(bottom or {}).get("extracted_fields") or {},
        )
        if mismatches:
            merged["mrz_llm_mismatches"] = mismatches
            merged["retake_reasons"] = [
                *merged["retake_reasons"],
                *(f"MRZ {field} disagrees with printed text ({why})"
                  for field, why in mismatches.items()),
            ]
            await log_action(
                db, "mrz_llm_disagreement", case_id=case.id,
                details={"document_type": legacy_key, "mismatches": mismatches},
            )

        results["ocr_results"][legacy_key] = merged

    # ---- Step 1.5: Lebanese eligibility rules ────────────────────
    # Apply legal / procedural rules from the General Directorate of
    # General Security before we burn cycles on face + registry. These
    # produce specific citizen-facing guidance ("apply as new passport",
    # "upload guardian consent") rather than the generic manual_review
    # outcome the risk model would otherwise emit.
    from .lebanese_rules import (
        check_passport_renewal_eligibility,
        check_minor_guardian_requirements,
    )
    eligibility_issues = []
    uploaded_doc_types = set(documents.keys())

    if case.service_type == "passport_renewal":
        # Find the MRZ from the passport_data_page OCR result if any.
        passport_ocr = (
            results["ocr_results"].get("passport_data_page")
            or results["ocr_results"].get("old_passport_data_page")
        )
        mrz_result = (passport_ocr or {}).get("mrz")
        issue = check_passport_renewal_eligibility(
            declared_fields=case.declared_fields or {},
            ocr_extracted_fields=all_extracted_fields,
            mrz_result=mrz_result,
        )
        if issue:
            eligibility_issues.append(issue)

    # Guardian-consent check applies to *every* service type — minors
    # always need it, regardless of which document they're applying for.
    minor_issue = check_minor_guardian_requirements(
        declared_fields=case.declared_fields or {},
        uploaded_doc_types=uploaded_doc_types,
    )
    if minor_issue:
        eligibility_issues.append(minor_issue)

    if eligibility_issues:
        # Bundle issues into the retake-banner format so the existing
        # frontend renders them without UI changes.
        case.retake_reasons = [
            {
                "document_type": "_eligibility",
                "code": issue.code,
                "reasons": [issue.message_en],
                "reasons_ar": [issue.message_ar],
                "suggested_action": issue.suggested_action,
            }
            for issue in eligibility_issues
        ]
        results["eligibility_issues"] = [issue.code for issue in eligibility_issues]
        results["routing"] = "needs_info"

        if model_versions:
            case.model_versions = model_versions

        CASE_STATUS_TRANSITIONS.labels(
            from_status="submitted", to_status="need_info",
        ).inc()
        _transition(case, "need_info", "Lebanese eligibility rule failed")
        await db.commit()

        await log_action(
            db, "eligibility_rule_failed", case_id=case.id,
            details={"issues": [
                {"code": i.code, "severity": i.severity, "action": i.suggested_action}
                for i in eligibility_issues
            ]},
        )
        PIPELINE_DURATION.labels(service_type=case.service_type).observe(
            _time.time() - pipeline_start
        )
        PIPELINE_DECISIONS.labels(decision="needs_info").inc()
        return results

    # ---- Step 2: Face verification ----
    face_similarity = 0.0
    liveness_score = 0.0

    selfie_doc = documents.get("selfie")
    ref_doc_type = policy.get("face_reference_doc")
    ref_doc_type_val = ref_doc_type.value if hasattr(ref_doc_type, 'value') else ref_doc_type
    reference_doc = documents.get(ref_doc_type_val) if ref_doc_type else None

    if policy.get("face_match_required"):
        # Check if liveness was done via Rekognition session (frontend flow)
        if case.liveness_result and case.liveness_result.get("status") == "SUCCEEDED":
            liveness_data = case.liveness_result
            liveness_score = liveness_data["confidence"] / 100.0
            # similarity_score=None means Rekognition couldn't run a
            # face-to-face comparison. There are two situations:
            #
            # (a) The service legitimately has no reference photo to
            #     compare against — passport_new and id_new only
            #     carry a civil-registry extract whose photo cell is
            #     small and frequently undetectable. There falling
            #     back to liveness confidence is reasonable: liveness
            #     proves the person is real, even if we can't prove
            #     they're the SAME real person.
            #
            # (b) A renewal flow uploaded an OLD passport / ID with
            #     a clean photo cell — Rekognition SHOULD have found
            #     a face. similarity_score=None there is a signal
            #     that the face match genuinely failed to land
            #     (degraded scan, occluded photo) AND the case
            #     potentially conceals a mismatched-applicant fraud
            #     attempt. Falling back to liveness confidence here
            #     would let "uploaded mom's passport + my liveness"
            #     score artificially high. Set face_similarity = 0
            #     so the risk component reflects the failure.
            raw_similarity = liveness_data.get("similarity_score")
            liveness_passed = liveness_data.get("liveness_passed", False)
            renewal_with_existing_doc = case.service_type in (
                "passport_renewal", "id_renewal"
            )
            if raw_similarity is None:
                if renewal_with_existing_doc:
                    # Renewal: reference doc DOES have a face cell.
                    # No comparison = comparison failed. Don't paper
                    # over with liveness confidence.
                    face_similarity = 0.0
                else:
                    face_similarity = (liveness_score * 100.0) if liveness_passed else 0.0
            else:
                face_similarity = float(raw_similarity)

            # face_comparison_decision can come back as null (not just
            # missing) when there's no reference document to compare
            # against — passport_new is the canonical case: a brand-new
            # citizen has no existing ID/passport to face-match a
            # selfie to, but they DO need liveness. In that case the
            # decision is "pass" if liveness succeeded, "fail" if not;
            # falling back to "manual_review" only when both signals
            # are absent. Without this `or`, the .get default never
            # fires (the key exists with value None) and the FaceResult
            # insert violates the NOT NULL constraint.
            face_decision = (
                liveness_data.get("face_comparison_decision")
                or ("pass" if liveness_passed else "fail")
                or "manual_review"
            )

            face_data = {
                "similarity_score": face_similarity,
                "liveness_score": liveness_score,
                "liveness_passed": liveness_passed,
                "decision": face_decision,
                "reasons": liveness_data.get("reasons", []),
                "processing_time_ms": 0,
            }

            # Create FaceResult record (use selfie doc or first doc as reference)
            selfie_doc_id = selfie_doc.id if selfie_doc else list(documents.values())[0].id
            ref_doc_id = reference_doc.id if reference_doc else selfie_doc_id
            face_record = FaceResult(
                case_id=case.id,
                selfie_document_id=selfie_doc_id,
                reference_document_id=ref_doc_id,
                similarity_score=face_similarity,
                liveness_score=liveness_score,
                liveness_passed=liveness_passed,
                decision=face_decision,
                reasons=liveness_data.get("reasons", []),
                processing_time_ms=0,
            )
            db.add(face_record)
            results["face_result"] = face_data

            if face_decision == "fail":
                results["issues"].extend(liveness_data.get("reasons", []))

            await log_action(
                db, "face_verification_completed", case_id=case.id,
                details={
                    "source": "liveness_session",
                    "decision": face_decision,
                    "similarity_score": face_similarity,
                    "liveness_score": liveness_score,
                    "liveness_passed": liveness_passed,
                    "liveness_session_id": liveness_data.get("session_id"),
                    "reference_image_path": liveness_data.get("reference_image_path"),
                    # bbox + face count + confidence for the cropped
                    # document-side face the similarity score was
                    # scored against — lets a later audit replay the
                    # exact crop the model saw.
                    "reference_crop": liveness_data.get("reference_crop"),
                    "reasons": liveness_data.get("reasons", []),
                },
            )

        elif selfie_doc and reference_doc:
            # Fallback: old flow (heuristic liveness + file-based comparison)
            try:
                face_data = await call_face_service(
                    case.id, selfie_doc.file_path, reference_doc.file_path
                )
                face_record = FaceResult(
                    case_id=case.id,
                    selfie_document_id=selfie_doc.id,
                    reference_document_id=reference_doc.id,
                    similarity_score=face_data["similarity_score"],
                    liveness_score=face_data["liveness_score"],
                    liveness_passed=face_data["liveness_passed"],
                    decision=face_data["decision"],
                    reasons=face_data.get("reasons", []),
                    processing_time_ms=face_data.get("processing_time_ms"),
                )
                db.add(face_record)
                results["face_result"] = face_data
                face_similarity = face_data["similarity_score"]
                liveness_score = face_data["liveness_score"]

                if face_data.get("model_info"):
                    model_versions["face"] = face_data["model_info"]

                if face_data["decision"] == "fail":
                    results["issues"].extend(face_data.get("reasons", []))

                await log_action(
                    db, "face_verification_completed", case_id=case.id,
                    details={
                        "source": "heuristic",
                        "decision": face_data["decision"],
                        "similarity_score": face_similarity,
                        "liveness_score": liveness_score,
                        "liveness_passed": face_data.get("liveness_passed", False),
                        "face_quality": face_data.get("face_quality", {}),
                        # See "reference_crop" comment on the
                        # liveness_session branch above.
                        "reference_crop": face_data.get("reference_crop"),
                        "reasons": face_data.get("reasons", []),
                        "processing_time_ms": face_data.get("processing_time_ms"),
                    },
                )

            except Exception as e:
                logger.error(f"Face verification failed for case {case.id}: {e}")
                await log_action(
                    db, "face_verification_failure", case_id=case.id,
                    details={"error": str(e)},
                )
                # Face service down — bounce back to citizen rather than
                # running risk on a 0-similarity score (which would auto-reject
                # an honest applicant for an infra outage).
                case.retake_reasons = [{
                    "document_type": "selfie",
                    "reasons": ["Face verification temporarily unavailable. Please re-submit shortly."],
                }]
                results["routing"] = "needs_info"
                CASE_STATUS_TRANSITIONS.labels(
                    from_status=case.status, to_status="need_info",
                ).inc()
                _transition(case, "need_info", "Face service unavailable")
                await db.commit()
                PIPELINE_DURATION.labels(service_type=case.service_type).observe(
                    _time.time() - pipeline_start
                )
                PIPELINE_DECISIONS.labels(decision="needs_info").inc()
                return results
        else:
            results["issues"].append("Missing selfie or reference document for face verification")
    elif not policy.get("face_match_required"):
        # New ID: no face comparison needed
        face_similarity = 100.0  # neutral (doesn't penalize risk)
        liveness_score = 1.0

    # ---- Transition: SUBMITTED -> VALIDATED ----
    CASE_STATUS_TRANSITIONS.labels(from_status="submitted", to_status="validated").inc()
    _transition(case, "validated", "OCR and face verification completed")
    await db.commit()

    # ---- Step 3: Reconciliation ----
    declared = case.declared_fields or {}
    recon_result = reconcile(declared, all_extracted_fields)
    case.reconciliation_result = recon_result
    results["reconciliation"] = recon_result

    RECONCILIATION_INTEGRITY.observe(float(recon_result.get("integrity_score") or 0.0))
    RECONCILIATION_RESULTS.labels(
        validation_result=recon_result.get("validation_result", "unknown"),
    ).inc()
    for flag in recon_result.get("mismatch_flags") or []:
        # mismatch_flags is a list of field names that didn't reconcile;
        # cardinality is bounded by the declared-field schema.
        RECONCILIATION_MISMATCHES.labels(field=str(flag)).inc()

    _lf.log_span(
        case_trace, name="reconciliation",
        input={"declared_fields": declared, "extracted_fields": all_extracted_fields},
        output={
            "integrity_score": recon_result["integrity_score"],
            "validation_result": recon_result["validation_result"],
            "matched_fields": recon_result["matched_fields"],
            "total_fields": recon_result["total_fields"],
            "mismatch_flags": recon_result["mismatch_flags"],
        },
        metadata={"step": "reconciliation"},
    )

    # ── Continuous extraction eval ─────────────────────────────────
    # The citizen's declared values are a free, real-time ground
    # truth for the LLM extractor's output: every legitimate
    # submission tells us what the doc SHOULD say. Emit a per-field
    # numeric score (similarity 0-1) and a categorical status score
    # (exact_match / close_match / partial_match / mismatch /
    # not_found_in_ocr) on the case trace. Langfuse aggregates these
    # by name across all cases — so over time you get a free
    # production dashboard of "first_name extraction quality",
    # "date_of_birth extraction quality", etc., per service_type tag.
    #
    # Filter: skip free-form fields like 'address' and 'notes' —
    # those legitimately diverge between declared and OCR (a citizen
    # types "Hamra St 12" while the doc shows "12 Hamra St, Beirut")
    # and would bias every aggregate score downward.
    _SKIP_FOR_EVAL = {"address", "notes", "renewal_reason", "passport_validity_years", "marital_status"}
    field_results = recon_result.get("field_results") or {}
    for fname, fres in list(field_results.items())[:20]:  # bound to keep traces small
        if fname in _SKIP_FOR_EVAL:
            continue
        try:
            sim = float(fres.get("similarity") or 0.0)
        except (TypeError, ValueError):
            continue
        _lf.log_score(
            case_trace,
            name=f"extraction.{fname}",
            value=sim,
            comment=(
                f"declared={fres.get('declared')!r} | "
                f"extracted={fres.get('extracted')!r} | "
                f"status={fres.get('status')}"
            )[:480],
        )
        _lf.log_score(
            case_trace,
            name=f"extraction_status.{fname}",
            value=str(fres.get("status") or "unknown"),
            data_type="CATEGORICAL",
        )
    await log_action(
        db, "reconciliation_completed", case_id=case.id,
        details={
            "integrity_score": recon_result["integrity_score"],
            "validation_result": recon_result["validation_result"],
            "total_fields": recon_result["total_fields"],
            "matched_fields": recon_result["matched_fields"],
            "mismatch_flags": recon_result["mismatch_flags"],
            "not_found_fields": recon_result.get("not_found_fields", []),
            "field_results": recon_result["field_results"],
            "declared_fields": declared,
        },
    )

    # ---- Step 3.1: Cross-document identity coherence ----
    # Reconciliation above only checks declared values vs a *merged*
    # OCR dict. That misses the canonical fraud case where a citizen
    # uploads someone else's passport plus their own civil-registry
    # extract: each doc reconciles against declared_fields fine, but
    # the docs disagree with each other. Compare every pair of
    # identity-bearing docs against each other on name + DOB + gender.
    # Any field divergence below the per-field threshold triggers a
    # hard reject — a case where the documents describe two different
    # people must NOT reach the manual_review queue.
    from .cross_doc_check import check_cross_doc_identity, summarize_for_citizen
    # Feed the citizen's declared/account fields in as a virtual "declared"
    # identity doc — when a real fraud submits someone else's identity
    # document, the divergence between declared and the OCR'd doc fires
    # the rejection even if only one identity doc made it through OCR.
    coherence = check_cross_doc_identity(
        results["ocr_results"], declared_fields=case.declared_fields or {},
    )
    case.cross_doc_coherence = coherence.to_dict()  # persisted for audit
    _lf.log_span(
        case_trace, name="cross_doc_identity_check",
        output=coherence.to_dict(),
        metadata={"step": "cross_doc"},
        level="ERROR" if not coherence.coherent else "DEFAULT",
    )
    await log_action(
        db, "cross_doc_check_completed", case_id=case.id,
        details=coherence.to_dict(),
    )
    # Hard-reject ONLY when two real OCR'd documents disagree with
    # each other — that's the canonical fraud pattern (mom's ID +
    # my registry). Declared-vs-doc divergence usually means OCR
    # misread a single character on the doc OR the citizen typed
    # their name slightly differently from how it's printed; that
    # signal already feeds reconciliation's integrity_score and the
    # risk engine handles it via manual review. Hard-rejecting on
    # OCR noise was bouncing legitimate id_new flows where the user
    # had only one identity doc + their declared values.
    real_divergences = coherence.doc_vs_doc_divergences()
    if real_divergences:
        ar_msg, en_msg = summarize_for_citizen(coherence)
        case.retake_reasons = [{
            "document_type": "_cross_doc_mismatch",
            "code": "documents_describe_different_people",
            "reasons": [en_msg],
            "reasons_ar": [ar_msg],
            "fields": sorted({d.label for d in real_divergences}),
        }]
        case.rejection_reasons = [
            "Cross-document identity check failed: uploaded documents "
            "do not describe the same person."
        ]
        if model_versions:
            case.model_versions = model_versions
        CASE_STATUS_TRANSITIONS.labels(
            from_status="submitted", to_status="rejected",
        ).inc()
        _transition(case, "rejected", "Cross-document identity mismatch")
        await db.commit()
        await log_action(
            db, "cross_doc_check_failed", case_id=case.id,
            details=coherence.to_dict(),
        )
        PIPELINE_DURATION.labels(service_type=case.service_type).observe(
            _time.time() - pipeline_start
        )
        PIPELINE_DECISIONS.labels(decision="reject").inc()
        return results

    # If reconciliation flagged any field-level mismatches, surface
    # them on the case so the citizen sees field names — not just
    # "data integrity issue". Without this, a case bounced to
    # need_info on reconciliation looks identical to a quality-gate
    # bounce in the UI, and the citizen resubmits the same wrong
    # data because they were never told which fields were wrong.
    # Risk scoring still runs; routing uses the mismatch count.
    mismatch_flags = recon_result.get("mismatch_flags") or []
    if mismatch_flags:
        readable = ", ".join(mismatch_flags)
        recon_finding = {
            "document_type": "_reconciliation",
            "code": "field_mismatch",
            "reasons": [f"Declared values don't match the documents for: {readable}"],
            "reasons_ar": [f"البيانات المُدخلة لا تطابق المستندات في: {readable}"],
            "fields": mismatch_flags,
        }
        # Preserve any prior reasons (e.g. eligibility findings) — these
        # accumulate; the UI lists them all so the citizen can fix every
        # issue in one resubmit.
        existing = list(case.retake_reasons or [])
        existing.append(recon_finding)
        case.retake_reasons = existing

    # ---- Step 3.5: Civil registry verification ----
    registry_result = await call_registry_service(declared)
    case.registry_result = registry_result
    results["registry"] = registry_result
    if registry_result.get("model_info"):
        model_versions["registry"] = registry_result["model_info"]

    registry_status = registry_result.get("status", "error")
    registry_confidence = float(registry_result.get("confidence") or 0.0)
    registry_deceased = registry_status == "deceased"
    # When the registry service is unreachable, the raw confidence
    # is 0.0 (see call_registry_service). Feeding 0.0 directly into
    # the risk scorer means an infra outage looks identical to a
    # citizen with bogus data — every case auto-rejects. Treat the
    # error case as a neutral signal so risk is dominated by OCR /
    # face / reconciliation; ops sees the outage on the dashboard.
    if registry_status == "error":
        registry_confidence = 1.0
        await log_action(
            db, "registry_degraded_mode", case_id=case.id,
            details={
                "reason": "registry service unreachable",
                "neutral_confidence_used": 1.0,
                "raw_reasons": registry_result.get("reasons", []),
            },
        )

    await log_action(
        db, "registry_verification_completed", case_id=case.id,
        details={
            "status": registry_status,
            "confidence": registry_confidence,
            "matched_citizen": registry_result.get("matched_citizen"),
            "field_scores": registry_result.get("field_scores", {}),
            "reasons": registry_result.get("reasons", []),
            "processing_time_ms": registry_result.get("processing_time_ms"),
        },
    )

    if registry_status == "no_match":
        results["issues"].append("No matching record in the civil registry")
    elif registry_deceased:
        results["issues"].append("Civil registry records citizen as deceased")

    # ---- Step 4: Risk scoring ----
    # Quality is no longer a risk input — every doc that reaches this step
    # has already passed the quality gate above, so quality carries no
    # signal. See risk.py header for the weight redistribution.
    avg_confidence = (
        sum(all_confidence_scores.values()) / len(all_confidence_scores)
        if all_confidence_scores else 0.0
    )

    # Highest spoof score across all uploaded documents. We take the
    # max (not the mean) because a single screen-captured doc is
    # enough to invalidate the case, and a clean second doc shouldn't
    # dilute the signal.
    spoof_score_max = 0.0
    spoof_offender: str | None = None
    for doc_type_val, ocr_data in (results.get("ocr_results") or {}).items():
        spoof_data = (ocr_data or {}).get("spoof") or {}
        s = float(spoof_data.get("spoof_score") or 0.0)
        if s > spoof_score_max:
            spoof_score_max = s
            spoof_offender = doc_type_val
    if spoof_score_max > 0:
        await log_action(
            db, "spoof_check_completed", case_id=case.id,
            details={
                "max_score": round(spoof_score_max, 4),
                "max_score_doc": spoof_offender,
                "decisions_by_doc": {
                    dt: ((d or {}).get("spoof") or {}).get("decision")
                    for dt, d in (results.get("ocr_results") or {}).items()
                },
            },
        )

    risk_result = compute_risk_score(
        ocr_avg_confidence=avg_confidence,
        face_similarity=face_similarity,
        liveness_score=liveness_score,
        reconciliation_integrity=recon_result["integrity_score"],
        service_type=case.service_type,
        mismatch_count=len(recon_result["mismatch_flags"]),
        registry_match_score=registry_confidence,
        registry_deceased=registry_deceased,
        spoof_score_max=spoof_score_max,
    )
    case.risk_result = risk_result
    results["risk"] = risk_result

    # Snapshot the risk-scoring config (weights + thresholds at this
    # moment) so a decision can be replayed against the exact same
    # rule set even if we tune the weights later.
    from .risk import WEIGHTS, AUTO_APPROVE_THRESHOLD, MANUAL_REVIEW_THRESHOLD
    model_versions["risk"] = {
        "service_name": "risk",
        "service_version": (
            __import__("os").environ.get("GIT_SHA")
            or __import__("os").environ.get("DOCFLOW_VERSION")
            or "dev"
        ),
        "provider": "docflow-risk-engine",
        "provider_version": "v1",
        "config": {
            "weights": WEIGHTS,
            "auto_approve_threshold": AUTO_APPROVE_THRESHOLD,
            "manual_review_threshold": MANUAL_REVIEW_THRESHOLD,
        },
    }
    # Stash the case-trace ID on model_versions so out-of-band events
    # (e.g. mukhtar decision hours later) can find this trace and
    # attach a feedback score without re-creating it.
    if case_trace_id:
        model_versions["langfuse"] = {"trace_id": case_trace_id}
    case.model_versions = model_versions

    # ---- Transition: VALIDATED -> RISK_EVALUATED ----
    CASE_STATUS_TRANSITIONS.labels(from_status="validated", to_status="risk_evaluated").inc()
    RISK_SCORE.observe(risk_result["risk_score"])
    _transition(case, "risk_evaluated", f"Risk score: {risk_result['risk_score']}")
    await db.commit()

    # ── Langfuse: span + summary scores for this case ──────────
    # The span captures the risk-engine inputs+outputs in one place;
    # the scores are individually aggregable in Langfuse so trends
    # ("median risk_score by week", "auto_approve rate", "p95 face
    # similarity") build automatically.
    _lf.log_span(
        case_trace, name="risk_scoring",
        input={
            "ocr_avg_confidence": avg_confidence,
            "face_similarity": face_similarity,
            "liveness_score": liveness_score,
            "reconciliation_integrity": recon_result["integrity_score"],
            "registry_match_score": registry_confidence,
            "spoof_score_max": spoof_score_max,
        },
        output=risk_result,
        metadata={"step": "risk"},
    )
    _lf.log_score(case_trace, name="recon_integrity",   value=float(recon_result["integrity_score"]))
    _lf.log_score(case_trace, name="ocr_confidence",    value=float(avg_confidence))
    _lf.log_score(case_trace, name="face_similarity",   value=float(face_similarity))
    _lf.log_score(case_trace, name="liveness_score",    value=float(liveness_score))
    _lf.log_score(case_trace, name="risk_score",        value=float(risk_result["risk_score"]))
    _lf.log_score(case_trace, name="spoof_score_max",   value=float(spoof_score_max))
    _lf.log_score(
        case_trace, name="cross_doc_coherent",
        value=1.0 if coherence.coherent else 0.0,
        data_type="BOOLEAN",
    )
    _lf.log_score(
        case_trace, name="ai_decision",
        value=str(risk_result["routing"]),
        data_type="CATEGORICAL",
    )

    await log_action(
        db, "risk_evaluated", case_id=case.id,
        details={
            "risk_score": risk_result["risk_score"],
            "routing": risk_result["routing"],
            "breakdown": risk_result["breakdown"],
            "inputs": {
                "ocr_avg_confidence": avg_confidence,
                "face_similarity": face_similarity,
                "liveness_score": liveness_score,
                "reconciliation_integrity": recon_result["integrity_score"],
                "service_type": case.service_type,
                "mismatch_count": len(recon_result["mismatch_flags"]),
                "registry_match_score": registry_confidence,
                "registry_status": registry_status,
                "registry_deceased": registry_deceased,
                "spoof_score_max": spoof_score_max,
            },
        },
    )

    # ---- Step 5: Decision ----
    routing = risk_result["routing"]
    mukhtar_required = policy.get("mukhtar_required", False)
    PIPELINE_DECISIONS.labels(decision=routing).inc()
    PIPELINE_DURATION.labels(service_type=case.service_type).observe(_time.time() - pipeline_start)

    if routing == "reject":
        CASE_STATUS_TRANSITIONS.labels(from_status="risk_evaluated", to_status="rejected").inc()
        _transition(case, "rejected", "Auto-rejected: high risk score")
        case.rejection_reasons = results["issues"] or ["High risk score"]
    elif mukhtar_required:
        # Passport services: route to mukhtar for digital stamp before approval
        CASE_STATUS_TRANSITIONS.labels(from_status="risk_evaluated", to_status="pending_mukhtar").inc()
        _transition(case, "pending_mukhtar", "Pending Mukhtar verification and digital stamp")

        # Auto-assign mukhtar based on citizen's registry_place
        assigned = await _assign_mukhtar(db, case)
        if assigned:
            await log_action(
                db, "mukhtar_assigned", case_id=case.id,
                details={"mukhtar_id": case.mukhtar_id, "registry_place": case.declared_fields.get("registry_place")},
            )

        # Generate the application form PDF. Wrapped because the
        # generator touches the filesystem (template render + write
        # to /app/uploads) — disk-full / permission errors must NOT
        # silently leave the mukhtar with no form to review. Audit
        # the failure and continue: the case still routes to the
        # mukhtar; they get the form on a re-generation request.
        from .form_generator import generate_passport_application
        user_result = await db.execute(select(User).where(User.id == case.user_id))
        applicant = user_result.scalar_one_or_none()
        if applicant:
            try:
                form_path = generate_passport_application(case, applicant)
                case.generated_form_path = form_path
            except Exception as exc:  # noqa: BLE001
                logger.exception("Passport form generation failed for case %s", case.id)
                await log_action(
                    db, "form_generation_failed", case_id=case.id,
                    details={"error": str(exc), "service_type": case.service_type},
                )
    elif routing == "auto_approve":
        CASE_STATUS_TRANSITIONS.labels(from_status="risk_evaluated", to_status="approved").inc()
        CASE_STATUS_TRANSITIONS.labels(from_status="approved", to_status="payment_pending").inc()
        _transition(case, "approved", "Auto-approved: low risk, all checks passed")
        _transition(case, "payment_pending", "Please complete payment to proceed")
    else:
        # manual_review — case stays at RISK_EVALUATED waiting for a
        # clerk in the Admin Review Queue to act. Without an explicit
        # audit row here, an auditor querying audit_logs for the case
        # sees the pipeline silently end with no decision, which looks
        # identical to a crashed worker. Emit a marker so the trail
        # explains *why* the case is parked.
        await log_action(
            db, "manual_review_required", case_id=case.id,
            details={
                "risk_score": risk_result["risk_score"],
                "routing": "manual_review",
                "reason": "Risk score in manual-review band (>auto-approve, <reject)",
            },
        )

    await db.commit()

    await log_action(
        db, "decision_made", case_id=case.id,
        details={
            "routing": routing,
            "mukhtar_required": mukhtar_required,
            "final_status": case.status,
            "mukhtar_id": case.mukhtar_id,
            "rejection_reasons": case.rejection_reasons,
            "pipeline_duration_seconds": round(_time.time() - pipeline_start, 3),
        },
    )

    # Send email notification for the final status
    try:
        user_result = await db.execute(select(User).where(User.id == case.user_id))
        user = user_result.scalar_one_or_none()
        if user:
            await send_case_status_email(
                to=user.email,
                full_name=user.full_name,
                tracking_id=case.tracking_id,
                service_type=case.service_type,
                new_status=case.status,
                rejection_reasons=case.rejection_reasons,
                db=db,
            )
    except Exception:
        logger.exception(f"Failed to send status email for case {case.id}")

    return results
