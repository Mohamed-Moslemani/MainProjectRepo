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


async def process_case(db: AsyncSession, case: Case) -> dict:
    """Run full processing pipeline on a submitted case."""
    import time as _time
    pipeline_start = _time.time()
    policy = get_policy(case.service_type)
    if not policy:
        logger.error(f"No policy for service type: {case.service_type}")
        return {"error": "Unknown service type"}

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
            # similarity_score = None means Rekognition couldn't run a
            # face-to-face comparison (no reference face was extractable
            # — typical for first-time applicants where the only photo
            # on file is the civil-registry extract, which Rekognition
            # may not find a face on). Distinguish that case from a
            # genuine 0% match. If liveness passed, fall back to the
            # liveness confidence as the face signal — the alternative
            # (defaulting to 0) caused id_new + passport_new applicants
            # to be auto-penalised with 100% face risk despite a
            # successful liveness check.
            raw_similarity = liveness_data.get("similarity_score")
            liveness_passed = liveness_data.get("liveness_passed", False)
            if raw_similarity is None:
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

    risk_result = compute_risk_score(
        ocr_avg_confidence=avg_confidence,
        face_similarity=face_similarity,
        liveness_score=liveness_score,
        reconciliation_integrity=recon_result["integrity_score"],
        service_type=case.service_type,
        mismatch_count=len(recon_result["mismatch_flags"]),
        registry_match_score=registry_confidence,
        registry_deceased=registry_deceased,
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
    case.model_versions = model_versions

    # ---- Transition: VALIDATED -> RISK_EVALUATED ----
    CASE_STATUS_TRANSITIONS.labels(from_status="validated", to_status="risk_evaluated").inc()
    RISK_SCORE.observe(risk_result["risk_score"])
    _transition(case, "risk_evaluated", f"Risk score: {risk_result['risk_score']}")
    await db.commit()

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
