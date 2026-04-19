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
        async with httpx.AsyncClient(timeout=30.0) as client:
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
        async with httpx.AsyncClient(timeout=30.0) as client:
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

    # ---- Step 1: OCR extraction ----
    ocr_documents = policy.get("ocr_documents", [])
    all_extracted_fields = {}
    all_confidence_scores = {}
    quality_scores = []

    for doc_type in ocr_documents:
        doc_type_val = doc_type.value if hasattr(doc_type, 'value') else doc_type
        doc = documents.get(doc_type_val)
        if not doc:
            results["issues"].append(f"Missing document: {doc_type_val}")
            continue

        try:
            ocr_data = await call_ocr_service(doc)
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

            # Quality score
            quality = ocr_data.get("quality", {})
            if quality.get("is_readable"):
                quality_scores.append(1.0)
            else:
                quality_scores.append(0.3)
                results["issues"].extend(ocr_data.get("retake_reasons", []))

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

        except Exception as e:
            logger.error(f"OCR failed for {doc_type_val}: {e}")
            results["issues"].append(f"OCR failed for {doc_type_val}")
            quality_scores.append(0.0)
            await log_action(
                db, "ocr_failure", case_id=case.id,
                details={"document_type": doc_type_val, "error": str(e)},
            )

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
            face_similarity = liveness_data.get("similarity_score") or 0.0
            liveness_passed = liveness_data.get("liveness_passed", False)

            face_decision = liveness_data.get("face_comparison_decision", "manual_review")

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
                results["issues"].append("Face verification service unavailable")
                await log_action(
                    db, "face_verification_failure", case_id=case.id,
                    details={"error": str(e)},
                )
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

    # ---- Step 4: Risk scoring ----
    avg_confidence = (
        sum(all_confidence_scores.values()) / len(all_confidence_scores)
        if all_confidence_scores else 0.0
    )
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0

    risk_result = compute_risk_score(
        ocr_avg_confidence=avg_confidence,
        face_similarity=face_similarity,
        liveness_score=liveness_score,
        reconciliation_integrity=recon_result["integrity_score"],
        document_quality_avg=avg_quality,
        service_type=case.service_type,
        mismatch_count=len(recon_result["mismatch_flags"]),
    )
    case.risk_result = risk_result
    results["risk"] = risk_result

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
                "document_quality_avg": avg_quality,
                "service_type": case.service_type,
                "mismatch_count": len(recon_result["mismatch_flags"]),
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

        # Generate the application form PDF
        from .form_generator import generate_passport_application
        user_result = await db.execute(select(User).where(User.id == case.user_id))
        applicant = user_result.scalar_one_or_none()
        if applicant:
            form_path = generate_passport_application(case, applicant)
            case.generated_form_path = form_path
    elif routing == "auto_approve":
        CASE_STATUS_TRANSITIONS.labels(from_status="risk_evaluated", to_status="approved").inc()
        CASE_STATUS_TRANSITIONS.labels(from_status="approved", to_status="payment_pending").inc()
        _transition(case, "approved", "Auto-approved: low risk, all checks passed")
        _transition(case, "payment_pending", "Please complete payment to proceed")
    else:
        # manual_review - stays at risk_evaluated, clerk must act
        pass

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
            )
    except Exception:
        logger.exception(f"Failed to send status email for case {case.id}")

    return results
