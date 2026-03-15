from pydantic import BaseModel
from datetime import datetime


class CaseCreate(BaseModel):
    service_type: str
    declared_fields: dict = {}


class CaseSubmit(BaseModel):
    """Submitted with the full declared application data."""
    declared_fields: dict


class CaseResponse(BaseModel):
    id: str
    user_id: str
    service_type: str
    status: str
    tracking_id: str
    declared_fields: dict
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CaseDetailResponse(CaseResponse):
    reconciliation_result: dict | None = None
    risk_result: dict | None = None
    rejection_reasons: list | None = None
    production_tracking_number: str | None = None
    pickup_center: str | None = None


class CaseListResponse(BaseModel):
    cases: list[CaseResponse]
    total: int


class CaseStatusUpdate(BaseModel):
    status: str
    notes: str | None = None
    rejection_reasons: list[str] | None = None


class TrackingEventResponse(BaseModel):
    timestamp: datetime
    status: str
    message: str
    actor: str | None = None


class TrackingResponse(BaseModel):
    tracking_id: str
    service_type: str
    current_status: str
    events: list[TrackingEventResponse]
    next_action: str | None = None


class CompletenessResponse(BaseModel):
    complete: bool
    missing_documents: list[str]
    uploaded_count: int
    required_count: int
