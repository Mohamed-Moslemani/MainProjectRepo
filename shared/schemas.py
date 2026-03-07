"""Shared Pydantic schemas used across all services."""
from enum import Enum
from pydantic import BaseModel
from datetime import datetime


#   Enums  

class ServiceType(str, Enum):
    PASSPORT_NEW = "passport_new"
    PASSPORT_RENEWAL = "passport_renewal"
    PASSPORT_LOST = "passport_lost"
    PASSPORT_STOLEN = "passport_stolen"
    ID_NEW = "id_new"
    ID_RENEWAL = "id_renewal"
    ID_LOST = "id_lost"
    ID_STOLEN = "id_stolen"


class CaseStatus(str, Enum):
    DRAFT = "draft"
    DOCUMENTS_PENDING = "documents_pending"
    DOCUMENTS_UPLOADED = "documents_uploaded"
    PROCESSING = "processing"
    ACTION_REQUIRED = "action_required"
    PAYMENT_PENDING = "payment_pending"
    PAYMENT_COMPLETED = "payment_completed"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    MANUAL_REVIEW = "manual_review"
    APPROVED = "approved"
    READY_FOR_PICKUP = "ready_for_pickup"
    COMPLETED = "completed"
    REJECTED = "rejected"


class DocumentType(str, Enum):
    NATIONAL_ID = "national_id"
    BIRTH_CERTIFICATE = "birth_certificate"
    PASSPORT_PHOTO = "passport_photo"
    SELFIE = "selfie"
    FAMILY_RECORD = "family_record"
    POLICE_REPORT = "police_report"
    OLD_PASSPORT = "old_passport"
    OLD_ID = "old_id"


class UserRole(str, Enum):
    CITIZEN = "citizen"
    CLERK = "clerk"
    ADMIN = "admin"


class VerificationDecision(str, Enum):
    PASS = "pass"
    MANUAL_REVIEW = "manual_review"
    FAIL = "fail"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


#   OCR Schemas  

class OCRRequest(BaseModel):
    document_id: str
    file_path: str
    document_type: DocumentType


class QualityAssessment(BaseModel):
    is_readable: bool
    blur_score: float
    glare_detected: bool
    angle_ok: bool
    resolution_ok: bool
    issues: list[str]


class OCRFieldResult(BaseModel):
    field_name: str
    value: str
    confidence: float


class OCRResponse(BaseModel):
    document_id: str
    status: str
    extracted_fields: list[OCRFieldResult]
    quality: QualityAssessment
    retake_required: bool
    retake_reasons: list[str]


#   Face Verification Schemas  

class FaceVerifyRequest(BaseModel):
    case_id: str
    selfie_path: str
    reference_path: str


class FaceVerifyResponse(BaseModel):
    case_id: str
    similarity_score: float
    liveness_score: float
    liveness_passed: bool
    decision: VerificationDecision
    reasons: list[str]


#   Tracking  

class TrackingEvent(BaseModel):
    timestamp: datetime
    status: CaseStatus
    message: str
    actor: str | None = None


class TrackingResponse(BaseModel):
    tracking_id: str
    service_type: ServiceType
    current_status: CaseStatus
    events: list[TrackingEvent]
    next_action: str | None = None
