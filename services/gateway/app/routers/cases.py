import os
import uuid
import logging
import aiofiles
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db import get_db
from ..config import get_settings
from ..models.user import User
from ..models.case import Case
from ..models.document import Document
from ..schemas.case import (
    CaseCreate, CaseSubmit, CaseResponse, CaseDetailResponse, CaseListResponse,
    CaseStatusUpdate, TrackingResponse, TrackingEventResponse, CompletenessResponse,
)
from ..schemas.document import DocumentResponse, DocumentWithOCR
from ..middleware.auth import get_current_user, require_role
from ..services.case_machine import can_transition, get_next_action
from ..services.policy import get_required_documents, get_policy, check_completeness
from ..services.orchestrator import process_case
from ..services.audit import log_action
from ..services.idempotency import idempotent_response, store_idempotent_response
from ..metrics import (
    CASES_CREATED, CASES_SUBMITTED, CASE_STATUS_TRANSITIONS,
    DOCUMENTS_UPLOADED, DOCUMENT_UPLOAD_SIZE,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/cases", tags=["cases"])


# ---- Case CRUD ----

@router.post("", response_model=CaseResponse, status_code=201)
async def create_case(
    req: CaseCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    case = Case(
        user_id=user.id,
        service_type=req.service_type,
        status="draft",
        declared_fields=req.declared_fields,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)

    CASES_CREATED.labels(service_type=req.service_type).inc()
    await log_action(db, "case_created", user_id=user.id, case_id=case.id,
                     details={"service_type": req.service_type})
    return case


@router.get("", response_model=CaseListResponse)
async def list_cases(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Case).where(Case.user_id == user.id).order_by(Case.created_at.desc())
    result = await db.execute(query)
    cases = list(result.scalars().all())
    return CaseListResponse(cases=cases, total=len(cases))


@router.get("/{case_id}", response_model=CaseDetailResponse)
async def get_case(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    case = await _get_user_case(db, case_id, user)
    return case


# ---- Required documents ----

@router.get("/{case_id}/required-documents")
async def get_required_docs(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    case = await _get_user_case(db, case_id, user)
    # Pass declared_fields so passport_renewal pulls in reason-specific
    # docs (police report, court ruling, etc).
    required = get_required_documents(case.service_type, declared_fields=case.declared_fields)
    policy = get_policy(case.service_type)
    declared_fields = policy.get("declared_fields", [])
    return {"service_type": case.service_type, "required_documents": required, "declared_fields": declared_fields}


@router.get("/{case_id}/completeness", response_model=CompletenessResponse)
async def check_case_completeness(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    case = await _get_user_case(db, case_id, user)
    docs_result = await db.execute(select(Document).where(Document.case_id == case.id))
    uploaded_types = [d.document_type for d in docs_result.scalars().all()]
    has_liveness = bool(case.liveness_result and case.liveness_result.get("liveness_passed"))
    return check_completeness(
        case.service_type, uploaded_types,
        has_liveness_session=has_liveness,
        declared_fields=case.declared_fields,
    )


# ---- Document upload ----

@router.post("/{case_id}/documents", response_model=DocumentResponse)
async def upload_document(
    case_id: str,
    document_type: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    case = await _get_user_case(db, case_id, user)

    if case.status not in ("draft", "need_info"):
        raise HTTPException(status_code=400, detail="Documents can only be uploaded in draft or need_info status")

    settings = get_settings()

    declared_mime = file.content_type
    if declared_mime not in ("image/jpeg", "image/png", "image/webp", "application/pdf"):
        raise HTTPException(status_code=400, detail="Unsupported file type")

    content = await file.read()
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large")

    # Magic-byte verification: the Content-Type header is whatever
    # the client says — a malicious upload of "evil.exe" relabelled
    # as image/jpeg would otherwise sail through. Sniff the first
    # bytes against known signatures for our allowlist and reject
    # anything that doesn't match the *declared* mime.
    from ..services.file_sniff import detect_mime
    detected_mime = detect_mime(content)
    if detected_mime != declared_mime:
        raise HTTPException(
            status_code=400,
            detail=(
                "File content does not match its declared type. "
                f"Declared: {declared_mime}, detected: {detected_mime or 'unknown'}."
            ),
        )

    # Use a deterministic extension derived from the *detected* mime,
    # not the filename — caller-supplied filenames can include path
    # separators or polyglot extensions that bypass simple guards.
    safe_ext = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }.get(detected_mime, ".bin")
    filename = f"{uuid.uuid4().hex}{safe_ext}"
    dir_path = os.path.join(settings.upload_dir, case_id)
    os.makedirs(dir_path, exist_ok=True)
    file_path = os.path.join(dir_path, filename)

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    doc = Document(
        case_id=case_id,
        document_type=document_type,
        file_path=file_path,
        original_filename=file.filename or "upload",
        file_size=len(content),
        mime_type=file.content_type or "application/octet-stream",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    DOCUMENTS_UPLOADED.labels(document_type=document_type).inc()
    DOCUMENT_UPLOAD_SIZE.observe(len(content))
    await log_action(db, "document_uploaded", user_id=user.id, case_id=case_id,
                     details={"document_type": document_type, "document_id": doc.id})
    return doc


@router.get("/{case_id}/documents", response_model=list[DocumentWithOCR])
async def list_documents(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_user_case(db, case_id, user)
    result = await db.execute(select(Document).where(Document.case_id == case_id))
    documents = list(result.scalars().all())

    response = []
    for doc in documents:
        data = DocumentWithOCR.model_validate(doc)
        if doc.ocr_result:
            data.ocr_status = "completed"
            data.extracted_fields = doc.ocr_result.extracted_fields
            data.confidence_scores = doc.ocr_result.confidence_scores
            data.retake_required = doc.ocr_result.retake_required
            data.retake_reasons = doc.ocr_result.retake_reasons
        response.append(data)
    return response


@router.get("/{case_id}/documents/{document_id}/image")
async def serve_case_document_image(
    case_id: str,
    document_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Serve an uploaded document image to its owner.

    The citizen needs to see what they uploaded for the inline doc-card
    thumbnail in CaseDetail. Reuses the same path-on-disk model as the
    mukhtar endpoint, just scoped to case ownership instead of mukhtar
    assignment. Admins/clerks aren't covered here — they get the image
    from /admin endpoints.
    """
    import os
    from fastapi.responses import FileResponse

    case = await _get_user_case(db, case_id, user)
    doc_result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.case_id == case.id,
        )
    )
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(
        doc.file_path,
        media_type=doc.mime_type,
        filename=doc.original_filename,
    )


# ---- Submit case (triggers pipeline) ----

@router.post("/{case_id}/submit")
async def submit_case(
    case_id: str,
    req: CaseSubmit,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Idempotency: a retried submit (flaky 3G, click "Submit" twice)
    # would otherwise create two pipeline runs on the same case. If
    # the client supplied an Idempotency-Key header on the original
    # request and we already cached a response, replay it verbatim.
    cached = await idempotent_response(db, user.id, request, route="cases.submit")
    if cached is not None:
        return cached

    case = await _get_user_case(db, case_id, user)

    if not can_transition(case.status, "submitted"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot submit from status '{case.status}'"
        )

    # Check completeness — declared_fields from this submit request,
    # since the renewal_reason picked here may add police_report /
    # court_ruling / damaged_passport to the required-docs list.
    docs_result = await db.execute(select(Document).where(Document.case_id == case.id))
    uploaded_types = [d.document_type for d in docs_result.scalars().all()]
    has_liveness = bool(case.liveness_result and case.liveness_result.get("liveness_passed"))
    completeness = check_completeness(
        case.service_type, uploaded_types,
        has_liveness_session=has_liveness,
        declared_fields=req.declared_fields,
    )

    if not completeness["complete"]:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required documents: {', '.join(completeness['missing_documents'])}"
        )

    # Save declared fields
    case.declared_fields = req.declared_fields
    prev_status = case.status  # "draft" or "need_info" (resubmit after retake)
    case.status = "submitted"
    case.status_history = case.status_history + [{
        "status": "submitted",
        "message": "Application submitted for processing",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]
    await db.commit()

    CASES_SUBMITTED.labels(service_type=case.service_type).inc()
    CASE_STATUS_TRANSITIONS.labels(from_status=prev_status, to_status="submitted").inc()
    await log_action(db, "case_submitted", user_id=user.id, case_id=case_id)

    # Push to the durable Arq queue so a gateway crash mid-pipeline
    # doesn't strand the case. If the queue itself is unreachable
    # (Redis blip), fall back to the in-process BackgroundTasks path
    # so submission still works in degraded mode — the orchestrator's
    # own state-machine guard prevents double-processing if both
    # eventually run.
    from ..queue import enqueue_process_case
    try:
        job_id = await enqueue_process_case(case_id)
        logger.info(
            "process_case enqueued",
            extra={"case_id": case_id, "arq_job_id": job_id},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Arq enqueue failed (%s); falling back to in-process BackgroundTasks",
            exc,
        )
        background_tasks.add_task(_process_case_bg, case_id)

    body = {"message": "Case submitted for processing", "tracking_id": case.tracking_id}
    return await store_idempotent_response(
        db, user.id, request, route="cases.submit", body=body,
    )


# ---- Clerk/Admin status updates ----

@router.patch("/{case_id}/status", response_model=CaseDetailResponse)
async def update_case_status(
    case_id: str,
    req: CaseStatusUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("clerk", "admin")),
):
    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    old_status = case.status
    if not can_transition(old_status, req.status):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from '{old_status}' to '{req.status}'"
        )

    CASE_STATUS_TRANSITIONS.labels(from_status=old_status, to_status=req.status).inc()
    case.status = req.status
    if req.notes:
        case.notes = req.notes
    if req.rejection_reasons:
        case.rejection_reasons = req.rejection_reasons
    case.status_history = case.status_history + [{
        "status": req.status,
        "message": req.notes or f"Status updated by {user.role}",
        "actor": user.role,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]

    # Auto-chain: approved → payment_pending
    if req.status == "approved" and can_transition("approved", "payment_pending"):
        case.status = "payment_pending"
        case.status_history = case.status_history + [{
            "status": "payment_pending",
            "message": "Please complete payment to proceed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]

    await db.commit()
    await db.refresh(case)

    await log_action(db, "case_status_updated", user_id=user.id, case_id=case_id,
                     details={"new_status": case.status})

    # Send email notification to the case owner
    try:
        from ..services.email import send_case_status_email
        owner_result = await db.execute(select(User).where(User.id == case.user_id))
        owner = owner_result.scalar_one_or_none()
        if owner:
            await send_case_status_email(
                to=owner.email,
                full_name=owner.full_name,
                tracking_id=case.tracking_id,
                service_type=case.service_type,
                new_status=case.status,
                notes=req.notes,
                rejection_reasons=req.rejection_reasons,
            )
    except Exception:
        logger.warning(f"Failed to send status email for case {case_id}", exc_info=True)

    return case


# ---- Tracking ----

@router.get("/{case_id}/tracking", response_model=TrackingResponse)
async def get_tracking(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    case = await _get_user_case(db, case_id, user)
    return _build_tracking_response(case)


@router.get("/track/{tracking_id}", response_model=TrackingResponse)
async def track_by_id(tracking_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Case).where(Case.tracking_id == tracking_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Tracking ID not found")
    return _build_tracking_response(case)


# ---- Helpers ----

def _build_tracking_response(case: Case) -> TrackingResponse:
    events = [
        TrackingEventResponse(
            timestamp=case.created_at,
            status=e.get("status", ""),
            message=e.get("message", ""),
            actor=e.get("actor"),
        )
        for e in (case.status_history or [])
    ]
    return TrackingResponse(
        tracking_id=case.tracking_id,
        service_type=case.service_type,
        current_status=case.status,
        events=events,
        next_action=get_next_action(case.status),
    )


async def _get_user_case(db: AsyncSession, case_id: str, user: User) -> Case:
    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.user_id != user.id and user.role not in ("clerk", "admin"):
        raise HTTPException(status_code=403, detail="Not authorized to access this case")
    return case


PIPELINE_BUDGET_SECONDS = 120


async def _process_case_bg(case_id: str):
    """Background task to run the processing pipeline.

    Wrapped in a wall-clock budget: if OCR / face / registry hangs for
    over PIPELINE_BUDGET_SECONDS combined, force the case to NEED_INFO
    so it doesn't sit in SUBMITTED forever. The citizen can resubmit
    once whatever was hanging recovers.
    """
    import asyncio
    import logging as _logging

    from ..db import async_session
    from .. import metrics
    from ..services.case_machine import can_transition

    log = _logging.getLogger(__name__)

    async with async_session() as db:
        result = await db.execute(select(Case).where(Case.id == case_id))
        case = result.scalar_one_or_none()
        if not case:
            return
        try:
            await asyncio.wait_for(process_case(db, case), timeout=PIPELINE_BUDGET_SECONDS)
        except asyncio.TimeoutError:
            log.error("Pipeline budget exceeded for case %s — bouncing to need_info", case_id)
            # Refetch in case the pipeline started writing then stalled
            result = await db.execute(select(Case).where(Case.id == case_id))
            case = result.scalar_one_or_none()
            if not case:
                return
            if can_transition(case.status, "need_info"):
                case.status = "need_info"
                case.retake_reasons = [{
                    "document_type": "_pipeline",
                    "reasons": [
                        f"Processing took longer than {PIPELINE_BUDGET_SECONDS}s "
                        "and was cancelled. Please re-submit."
                    ],
                }]
                case.status_history = case.status_history + [{
                    "status": "need_info",
                    "message": "Processing pipeline timed out",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }]
                await db.commit()
                metrics.CASE_STATUS_TRANSITIONS.labels(
                    from_status=case.status, to_status="need_info",
                ).inc()
        except Exception:
            log.exception("Pipeline crashed for case %s", case_id)
            # Same bounce-to-need_info on any uncaught error so we never
            # leave the case stuck in SUBMITTED.
            result = await db.execute(select(Case).where(Case.id == case_id))
            case = result.scalar_one_or_none()
            if case and can_transition(case.status, "need_info"):
                case.status = "need_info"
                case.retake_reasons = [{
                    "document_type": "_pipeline",
                    "reasons": ["Internal processing error. Please re-submit."],
                }]
                case.status_history = case.status_history + [{
                    "status": "need_info",
                    "message": "Pipeline crashed",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }]
                await db.commit()
