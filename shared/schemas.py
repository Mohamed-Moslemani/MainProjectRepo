"""Shared Pydantic schemas used across all services."""
from enum import Enum
from pydantic import BaseModel
from datetime import datetime


# --- Enums ---

class ServiceType(str, Enum):
    ID_NEW = "id_new"
    ID_RENEWAL = "id_renewal"
    PASSPORT_NEW = "passport_new"
    PASSPORT_RENEWAL = "passport_renewal"


class CaseStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    VALIDATED = "validated"
    RISK_EVALUATED = "risk_evaluated"
    NEED_INFO = "need_info"
    APPROVED = "approved"
    REJECTED = "rejected"
    IN_PRODUCTION = "in_production"
    READY_FOR_PICKUP = "ready_for_pickup"
    CLOSED = "closed"


class DocumentType(str, Enum):
    # ID documents
    NATIONAL_ID_FRONT = "national_id_front"
    NATIONAL_ID_BACK = "national_id_back"
    OLD_ID_FRONT = "old_id_front"
    OLD_ID_BACK = "old_id_back"

    # Passport
    PASSPORT_DATA_PAGE = "passport_data_page"
    OLD_PASSPORT_DATA_PAGE = "old_passport_data_page"

    # Civil records
    CIVIL_REGISTRY_EXTRACT = "civil_registry_extract"

    # Photos & biometrics
    SELFIE = "selfie"
    LIVENESS_CAPTURE = "liveness_capture"

    # Supporting
    GUARDIAN_DOCS = "guardian_docs"
    ADDITIONAL_IDENTITY_PROOF = "additional_identity_proof"


class UserRole(str, Enum):
    CITIZEN = "citizen"
    CLERK = "clerk"
    ADMIN = "admin"


class VerificationDecision(str, Enum):
    PASS = "pass"
    MANUAL_REVIEW = "manual_review"
    FAIL = "fail"


class ValidationResult(str, Enum):
    PASS = "pass"
    NEED_INFO = "need_info"
    FAIL = "fail"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


# --- OCR Schemas ---

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


# --- Face Verification Schemas ---

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


# --- Tracking ---

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
