"""Policy engine - required documents, validation rules, and checks per service type.

Each service type defines:
- required_documents: what must be uploaded
- ocr_documents: which docs get OCR processing
- face_reference_doc: which doc photo to compare selfie against
- face_match_required: whether selfie-to-doc match is needed
- needs_mrz: whether MRZ parsing applies
"""

from shared.schemas import ServiceType, DocumentType

SERVICE_POLICIES = {
    ServiceType.ID_RENEWAL: {
        "required_documents": [
            DocumentType.OLD_ID_FRONT,
            DocumentType.OLD_ID_BACK,
            DocumentType.CIVIL_REGISTRY_EXTRACT,
            DocumentType.SELFIE,
            DocumentType.LIVENESS_CAPTURE,
        ],
        "ocr_documents": [
            DocumentType.OLD_ID_FRONT,
            DocumentType.OLD_ID_BACK,
            DocumentType.CIVIL_REGISTRY_EXTRACT,
        ],
        "face_reference_doc": DocumentType.OLD_ID_FRONT,
        "face_match_required": True,
        "needs_mrz": False,
        "declared_fields": [
            "full_name", "father_name", "mother_name", "date_of_birth",
            "registry_number", "address", "marital_status", "reason_for_renewal",
        ],
    },

    ServiceType.ID_NEW: {
        "required_documents": [
            DocumentType.CIVIL_REGISTRY_EXTRACT,
            DocumentType.SELFIE,
            DocumentType.LIVENESS_CAPTURE,
        ],
        "optional_documents": [
            DocumentType.ADDITIONAL_IDENTITY_PROOF,
            DocumentType.GUARDIAN_DOCS,
        ],
        "ocr_documents": [
            DocumentType.CIVIL_REGISTRY_EXTRACT,
        ],
        "face_reference_doc": None,  # no existing ID to compare against
        "face_match_required": False,
        "needs_mrz": False,
        "declared_fields": [
            "full_name", "father_name", "mother_name", "date_of_birth",
            "place_of_birth", "registry_number", "address", "marital_status",
        ],
    },

    ServiceType.PASSPORT_RENEWAL: {
        "required_documents": [
            DocumentType.OLD_PASSPORT_DATA_PAGE,
            DocumentType.CIVIL_REGISTRY_EXTRACT,
            DocumentType.SELFIE,
            DocumentType.LIVENESS_CAPTURE,
        ],
        "optional_documents": [
            DocumentType.NATIONAL_ID_FRONT,
            DocumentType.GUARDIAN_DOCS,
        ],
        "ocr_documents": [
            DocumentType.OLD_PASSPORT_DATA_PAGE,
            DocumentType.NATIONAL_ID_FRONT,
        ],
        "face_reference_doc": DocumentType.OLD_PASSPORT_DATA_PAGE,
        "face_match_required": True,
        "secondary_face_reference": DocumentType.NATIONAL_ID_FRONT,
        "needs_mrz": True,
        "mukhtar_required": True,
        "declared_fields": [
            "full_name", "father_name", "mother_name", "date_of_birth",
            "place_of_birth", "old_passport_number", "passport_type",
            "registry_number", "registry_place",
        ],
    },

    ServiceType.PASSPORT_NEW: {
        "required_documents": [
            DocumentType.CIVIL_REGISTRY_EXTRACT,
            DocumentType.SELFIE,
            DocumentType.LIVENESS_CAPTURE,
        ],
        "optional_documents": [
            DocumentType.NATIONAL_ID_FRONT,
            DocumentType.NATIONAL_ID_BACK,
            DocumentType.ADDITIONAL_IDENTITY_PROOF,
            DocumentType.GUARDIAN_DOCS,
        ],
        "ocr_documents": [
            DocumentType.NATIONAL_ID_FRONT,
            DocumentType.NATIONAL_ID_BACK,
            DocumentType.CIVIL_REGISTRY_EXTRACT,
        ],
        "face_reference_doc": DocumentType.NATIONAL_ID_FRONT,
        "face_match_required": True,
        "needs_mrz": False,
        "mukhtar_required": True,
        "declared_fields": [
            "full_name", "father_name", "mother_name", "date_of_birth",
            "place_of_birth", "registry_number", "registry_place",
        ],
    },
}


def get_policy(service_type: str) -> dict:
    try:
        st = ServiceType(service_type)
    except ValueError:
        return {}
    return SERVICE_POLICIES.get(st, {})


def get_required_documents(service_type: str) -> list[str]:
    policy = get_policy(service_type)
    return [d.value for d in policy.get("required_documents", [])]


def get_missing_documents(service_type: str, uploaded_types: list[str]) -> list[str]:
    required = get_required_documents(service_type)
    return [d for d in required if d not in uploaded_types]


def check_completeness(service_type: str, uploaded_types: list[str], has_liveness_session: bool = False) -> dict:
    """Check if all required documents are uploaded.

    If has_liveness_session is True, selfie and liveness_capture are
    considered satisfied by the Rekognition Liveness session.
    """
    missing = get_missing_documents(service_type, uploaded_types)

    # Liveness session replaces selfie + liveness_capture uploads
    if has_liveness_session:
        liveness_docs = {DocumentType.SELFIE.value, DocumentType.LIVENESS_CAPTURE.value}
        missing = [d for d in missing if d not in liveness_docs]

    required_count = len(get_required_documents(service_type))
    uploaded_count = len(uploaded_types) + (2 if has_liveness_session else 0)

    return {
        "complete": len(missing) == 0,
        "missing_documents": missing,
        "uploaded_count": min(uploaded_count, required_count),
        "required_count": required_count,
    }
