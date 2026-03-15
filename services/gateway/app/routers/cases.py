import os
import uuid
import aiofiles
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
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
from ..services.policy import get_required_documents, check_completeness
from ..services.orchestrator import process_case
from ..services.audit import log_action

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
    required = get_required_documents(case.service_type)
    return {"service_type": case.service_type, "required_documents": required}


@router.get("/{case_id}/completeness", response_model=CompletenessResponse)
async def check_case_completeness(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    case = await _get_user_case(db, case_id, user)
    docs_result = await db.execute(select(Document).where(Document.case_id == case.id))
    uploaded_types = [d.document_type for d in docs_result.scalars().all()]
    return check_completeness(case.service_type, uploaded_types)


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

    if file.content_type not in ("image/jpeg", "image/png", "image/webp", "application/pdf"):
        raise HTTPException(status_code=400, detail="Unsupported file type")

    content = await file.read()
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large")

    ext = os.path.splitext(file.filename or "upload")[1] or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
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


# ---- Submit case (triggers pipeline) ----

@router.post("/{case_id}/submit")
async def submit_case(
    case_id: str,
    req: CaseSubmit,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    case = await _get_user_case(db, case_id, user)

    if not can_transition(case.status, "submitted"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot submit from status '{case.status}'"
        )

    # Check completeness
    docs_result = await db.execute(select(Document).where(Document.case_id == case.id))
    uploaded_types = [d.document_type for d in docs_result.scalars().all()]
    completeness = check_completeness(case.service_type, uploaded_types)

    if not completeness["complete"]:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required documents: {', '.join(completeness['missing_documents'])}"
        )

    # Save declared fields
    case.declared_fields = req.declared_fields
    case.status = "submitted"
    case.status_history = case.status_history + [{
        "status": "submitted",
        "message": "Application submitted for processing",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]
    await db.commit()

    await log_action(db, "case_submitted", user_id=user.id, case_id=case_id)

    # Process in background
    background_tasks.add_task(_process_case_bg, case_id)

    return {"message": "Case submitted for processing", "tracking_id": case.tracking_id}


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

    if not can_transition(case.status, req.status):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from '{case.status}' to '{req.status}'"
        )

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
    await db.commit()
    await db.refresh(case)

    await log_action(db, "case_status_updated", user_id=user.id, case_id=case_id,
                     details={"new_status": req.status})
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


async def _process_case_bg(case_id: str):
    """Background task to run the processing pipeline."""
    from ..db import async_session
    async with async_session() as db:
        result = await db.execute(select(Case).where(Case.id == case_id))
        case = result.scalar_one_or_none()
        if case:
            await process_case(db, case)
