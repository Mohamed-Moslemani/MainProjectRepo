"""Mukhtar router - endpoints for mukhtar dashboard, case review, and approval.

Mukhtars see passport cases assigned to their jurisdiction (registry_place).
They review the pre-verified citizen data and digitally approve or reject.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..db import get_db
from ..models.user import User
from ..models.case import Case
from ..models.document import Document
from ..models.payment import Payment
from ..middleware.auth import require_role
from ..services.case_machine import can_transition
from ..services.audit import log_action
from ..services.email import send_case_status_email

router = APIRouter(prefix="/api/v1/mukhtar", tags=["mukhtar"])


class MukhtarDecision(BaseModel):
    """Mukhtar decision payload.

    Real Lebanese mukhtars attest to three things when stamping an
    application: (1) the citizen lives in their district, (2) the
    submitted photo matches the person standing in front of them, and
    (3) the citizen was physically present in the mukhtar's office
    when the application was signed. We require all three to be True
    for an "approve" decision — this mirrors the legal attestation
    the mukhtar signs on paper today.
    """

    decision: str  # "approve" | "reject" | "need_info"

    # Three structured attestations — all required for approve
    residence_verified: bool = False
    photo_verified: bool = False
    presence_verified: bool = False

    # Free-text context
    residence_notes: str | None = None   # e.g. "resident for 12+ years, known to me"
    failed_attestation_reason: str | None = None  # why any of the three couldn't be attested
    notes: str | None = None
    rejection_reasons: list[str] | None = None


class TransferRequest(BaseModel):
    target_mukhtar_id: str
    reason: str | None = None


@router.get("/cases")
async def list_mukhtar_cases(
    status: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("mukhtar")),
):
    """List cases assigned to this mukhtar."""
    query = (
        select(Case)
        .where(Case.mukhtar_id == user.id)
        .order_by(Case.updated_at.desc())
    )
    count_query = select(func.count(Case.id)).where(Case.mukhtar_id == user.id)

    if status:
        query = query.where(Case.status == status)
        count_query = count_query.where(Case.status == status)

    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    cases = list(result.scalars().all())
    total = (await db.execute(count_query)).scalar()

    return {"cases": cases, "total": total, "limit": limit, "offset": offset}


@router.get("/stats")
async def mukhtar_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("mukhtar")),
):
    """Dashboard stats for this mukhtar."""
    base = select(func.count(Case.id)).where(Case.mukhtar_id == user.id)

    total = (await db.execute(base)).scalar()
    pending = (await db.execute(
        base.where(Case.status == "pending_mukhtar")
    )).scalar()
    approved = (await db.execute(
        base.where(Case.status.in_(["approved", "payment_pending", "in_production", "ready_for_pickup", "closed"]))
    )).scalar()
    rejected = (await db.execute(
        base.where(Case.status == "rejected")
    )).scalar()

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today = (await db.execute(
        select(func.count(Case.id)).where(
            Case.mukhtar_id == user.id,
            Case.updated_at >= today_start,
        )
    )).scalar()

    return {
        "total_cases": total,
        "pending_review": pending,
        "approved": approved,
        "rejected": rejected,
        "today_activity": today,
    }


@router.get("/cases/{case_id}")
async def get_case_detail(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("mukhtar")),
):
    """Get full case details for mukhtar review."""
    result = await db.execute(
        select(Case).where(Case.id == case_id, Case.mukhtar_id == user.id)
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found or not assigned to you")

    # Get applicant info
    owner_result = await db.execute(select(User).where(User.id == case.user_id))
    owner = owner_result.scalar_one_or_none()

    owner_info = None
    if owner:
        owner_info = {
            "id": owner.id,
            "full_name": owner.full_name,
            "father_name": owner.father_name,
            "mother_name": owner.mother_name,
            "date_of_birth": str(owner.date_of_birth) if owner.date_of_birth else None,
            "place_of_birth": owner.place_of_birth,
            "gender": owner.gender,
            "registry_number": owner.registry_number,
            "registry_place": owner.registry_place,
            "phone": owner.phone,
            "address": owner.address,
            "marital_status": owner.marital_status,
        }

    # Get uploaded documents
    docs_result = await db.execute(
        select(Document).where(Document.case_id == case_id)
    )
    documents = [
        {
            "id": d.id,
            "document_type": d.document_type,
            "original_filename": d.original_filename,
            "mime_type": d.mime_type,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs_result.scalars().all()
    ]

    return {
        "case": case,
        "applicant": owner_info,
        "documents": documents,
        "verification_summary": {
            "identity_verified": bool(
                case.liveness_result and case.liveness_result.get("liveness_passed")
            ),
            "liveness_confidence": (
                case.liveness_result.get("confidence") if case.liveness_result else None
            ),
            "face_similarity": (
                case.liveness_result.get("similarity_score") if case.liveness_result else None
            ),
            "data_integrity": (
                case.reconciliation_result.get("integrity_score")
                if case.reconciliation_result else None
            ),
            "mismatches": (
                case.reconciliation_result.get("mismatch_flags")
                if case.reconciliation_result else []
            ),
            "risk_score": (
                case.risk_result.get("risk_score") if case.risk_result else None
            ),
            "has_generated_form": case.generated_form_path is not None,
        },
    }


@router.get("/cases/{case_id}/documents/{document_id}/image")
async def serve_document_image(
    case_id: str,
    document_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("mukhtar")),
):
    """Serve an uploaded document image for mukhtar review."""
    result = await db.execute(
        select(Case).where(Case.id == case_id, Case.mukhtar_id == user.id)
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found or not assigned to you")

    doc_result = await db.execute(
        select(Document).where(Document.id == document_id, Document.case_id == case_id)
    )
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    import os
    if not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        doc.file_path,
        media_type=doc.mime_type,
        filename=doc.original_filename,
    )


@router.get("/cases/{case_id}/form")
async def download_application_form(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("mukhtar")),
):
    """Download the generated passport application PDF."""
    result = await db.execute(
        select(Case).where(Case.id == case_id, Case.mukhtar_id == user.id)
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found or not assigned to you")

    if not case.generated_form_path:
        raise HTTPException(status_code=404, detail="Application form not yet generated")

    import os
    if not os.path.exists(case.generated_form_path):
        raise HTTPException(status_code=404, detail="Form file not found on disk")

    return FileResponse(
        case.generated_form_path,
        media_type="application/pdf",
        filename=f"passport_application_{case.tracking_id}.pdf",
    )


@router.post("/cases/{case_id}/decide")
async def mukhtar_decide(
    case_id: str,
    body: MukhtarDecision,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("mukhtar")),
):
    """Mukhtar approves, rejects, or requests more info for a case."""
    result = await db.execute(
        select(Case).where(Case.id == case_id, Case.mukhtar_id == user.id)
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found or not assigned to you")

    if case.status != "pending_mukhtar":
        raise HTTPException(status_code=400, detail=f"Case is not pending mukhtar review (current: {case.status})")

    now = datetime.now(timezone.utc)

    attestations = {
        "residence_verified": body.residence_verified,
        "photo_verified": body.photo_verified,
        "presence_verified": body.presence_verified,
    }
    all_attested = all(attestations.values())

    if body.decision == "approve":
        if not all_attested:
            failed = [k for k, v in attestations.items() if not v]
            raise HTTPException(
                status_code=400,
                detail=(
                    "Approve requires all three attestations: residence, photo, and presence. "
                    f"Missing: {', '.join(failed)}"
                ),
            )

        # Jurisdiction guard: a Lebanese mukhtar may legally attest only
        # residents of his own محلة (locality). Compare the case's
        # registry_place / municipality against the mukhtar's profile.
        # Auto-assignment already filters by jurisdiction at routing
        # time, but a manually-reassigned case (or one where the
        # citizen edited their declared registry_place between assign
        # and decide) could slip through — guard explicitly here.
        declared = case.declared_fields or {}
        case_municipality = (declared.get("municipality") or "").strip().lower()
        case_registry = (declared.get("registry_place") or "").strip().lower()
        mukh_municipality = (user.municipality or "").strip().lower()
        mukh_registry = (user.registry_place or "").strip().lower()

        municipality_match = bool(
            case_municipality and mukh_municipality and case_municipality == mukh_municipality
        )
        district_match = bool(
            case_registry and mukh_registry and case_registry == mukh_registry
        )

        if not (municipality_match or district_match):
            await log_action(
                db, "mukhtar_jurisdiction_violation", user_id=user.id, case_id=case_id,
                details={
                    "case_municipality": case_municipality or None,
                    "case_registry_place": case_registry or None,
                    "mukhtar_municipality": mukh_municipality or None,
                    "mukhtar_registry_place": mukh_registry or None,
                },
            )
            raise HTTPException(
                status_code=403,
                detail=(
                    "Out of jurisdiction — a mukhtar may only attest residents of his "
                    "own locality. The case's registry place does not match yours. "
                    "Use 'reject' or 'need_info' to flag this case for re-routing."
                ),
            )

        target_status = "approved"
        message = "Mukhtar approved: residence, photo, and presence attested"
    elif body.decision == "reject":
        target_status = "rejected"
        message = "Mukhtar rejected the application"
        if not body.rejection_reasons:
            raise HTTPException(status_code=400, detail="Rejection reasons required")
    elif body.decision == "need_info":
        target_status = "need_info"
        message = "Mukhtar requested additional information"
    else:
        raise HTTPException(status_code=400, detail="Invalid decision. Use: approve, reject, need_info")

    if not can_transition(case.status, target_status):
        raise HTTPException(status_code=400, detail=f"Cannot transition from {case.status} to {target_status}")

    # Record mukhtar approval details — including the three-part attestation
    # that Lebanese mukhtars legally sign off on.
    case.mukhtar_approval = {
        "decision": body.decision,
        "mukhtar_id": user.id,
        "mukhtar_name": user.full_name,
        "attestations": attestations,
        "residence_notes": body.residence_notes,
        "failed_attestation_reason": body.failed_attestation_reason,
        "notes": body.notes,
        "rejection_reasons": body.rejection_reasons,
        "timestamp": now.isoformat(),
    }

    # Transition the case
    case.status = target_status
    case.status_history = case.status_history + [{
        "status": target_status,
        "message": message,
        "timestamp": now.isoformat(),
        "actor": f"mukhtar:{user.full_name}",
    }]

    if body.notes:
        case.notes = body.notes
    if body.rejection_reasons:
        case.rejection_reasons = body.rejection_reasons

    # If approved, auto-chain to payment_pending
    if target_status == "approved" and can_transition("approved", "payment_pending"):
        case.status = "payment_pending"
        case.status_history = case.status_history + [{
            "status": "payment_pending",
            "message": "Please complete payment to proceed",
            "timestamp": now.isoformat(),
        }]

    await db.commit()

    await log_action(
        db, "mukhtar_decision", user_id=user.id, case_id=case.id,
        details={
            "decision": body.decision,
            "attestations": attestations,
            "residence_notes": body.residence_notes,
            "failed_attestation_reason": body.failed_attestation_reason,
            "notes": body.notes,
            "rejection_reasons": body.rejection_reasons,
            "final_status": case.status,
        },
    )

    # ── Langfuse: human-ground-truth feedback ──────────────────
    # The mukhtar is the legal authority on identity for passport
    # cases — their approve/reject is the closest thing we have to
    # a correct label for the AI's pre-mukhtar risk decision. Emit
    # a score on the case's earlier evaluation trace so Langfuse
    # tracks AI-vs-mukhtar agreement over time. The trace ID was
    # stashed in case.model_versions["langfuse"] when the orchestrator
    # ran the case.
    try:
        from ..services import langfuse_client as _lf
        trace_id = ((case.model_versions or {}).get("langfuse") or {}).get("trace_id")
        if trace_id:
            _lf.log_score(
                trace_id=trace_id,
                name="mukhtar_decision",
                value=1.0 if body.decision == "approve" else 0.0,
                data_type="BOOLEAN",
                comment=(
                    f"residence={attestations['residence_verified']}; "
                    f"photo={attestations['photo_verified']}; "
                    f"presence={attestations['presence_verified']}"
                ),
            )
            # Agreement with the AI: AI sent this case to pending_mukhtar
            # because it lacked confidence. If mukhtar approves, AI was
            # right to defer (1.0 — the manual_review routing was
            # correct). If mukhtar rejects, the AI under-flagged risk
            # (0.0 — should have rejected directly). This is the
            # signal you want a model-eval dashboard tracking.
            _lf.log_score(
                trace_id=trace_id,
                name="ai_mukhtar_agreement",
                value=1.0 if body.decision == "approve" else 0.0,
                data_type="BOOLEAN",
            )
    except Exception:
        # Fail-OPEN: feedback is best-effort, never fails a mukhtar
        # decision over an observability hiccup.
        pass

    # Notify citizen
    try:
        citizen_result = await db.execute(select(User).where(User.id == case.user_id))
        citizen = citizen_result.scalar_one_or_none()
        if citizen:
            await send_case_status_email(
                to=citizen.email,
                full_name=citizen.full_name,
                tracking_id=case.tracking_id,
                service_type=case.service_type,
                new_status=case.status,
                rejection_reasons=case.rejection_reasons,
                db=db,
            )
    except Exception:
        pass  # email failure shouldn't block the decision

    return {
        "case_id": case.id,
        "decision": body.decision,
        "new_status": case.status,
        "message": message,
    }


@router.get("/cases/{case_id}/available-mukhtars")
async def list_available_mukhtars(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("mukhtar")),
):
    """List other mukhtars in the same district for transfer."""
    result = await db.execute(
        select(Case).where(Case.id == case_id, Case.mukhtar_id == user.id)
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found or not assigned to you")

    # Find mukhtars in the same district (registry_place), excluding self
    mukhtar_result = await db.execute(
        select(User).where(
            User.role == "mukhtar",
            User.registry_place == user.registry_place,
            User.id != user.id,
        )
    )
    mukhtars = [
        {
            "id": m.id,
            "full_name": m.full_name,
            "municipality": m.municipality,
            "registry_place": m.registry_place,
        }
        for m in mukhtar_result.scalars().all()
    ]

    return {"mukhtars": mukhtars}


@router.post("/cases/{case_id}/transfer")
async def transfer_case(
    case_id: str,
    body: TransferRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("mukhtar")),
):
    """Transfer a case to another mukhtar in the same district."""
    result = await db.execute(
        select(Case).where(Case.id == case_id, Case.mukhtar_id == user.id)
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found or not assigned to you")

    if case.status != "pending_mukhtar":
        raise HTTPException(status_code=400, detail="Can only transfer cases pending mukhtar review")

    # Validate target mukhtar exists and is in the same district
    target_result = await db.execute(
        select(User).where(
            User.id == body.target_mukhtar_id,
            User.role == "mukhtar",
            User.registry_place == user.registry_place,
        )
    )
    target = target_result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Target mukhtar not found in your district")

    now = datetime.now(timezone.utc)

    case.mukhtar_id = target.id
    case.status_history = case.status_history + [{
        "status": "pending_mukhtar",
        "message": f"Transferred from {user.full_name} to {target.full_name}",
        "timestamp": now.isoformat(),
        "actor": f"mukhtar:{user.full_name}",
    }]

    await db.commit()

    await log_action(
        db, "mukhtar_transfer", user_id=user.id, case_id=case.id,
        details={
            "from_mukhtar": user.id,
            "to_mukhtar": target.id,
            "to_mukhtar_name": target.full_name,
            "reason": body.reason,
        },
    )

    return {
        "case_id": case.id,
        "transferred_to": target.full_name,
        "message": f"Case transferred to {target.full_name}",
    }