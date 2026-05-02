"""Policy engine - required documents, validation rules, and checks per service type.

Each service type defines:
- required_documents: what must be uploaded
- ocr_documents: which docs get OCR processing
- face_reference_doc: which doc photo to compare selfie against
- face_match_required: whether selfie-to-doc match is needed
- needs_mrz: whether MRZ parsing applies
"""

from shared.schemas import ServiceType, DocumentType, RenewalReason


# ── Renewal-reason supporting documents (Lebanese GDGS) ─────────────
#
# Every passport renewal carries a reason; some reasons require extra
# supporting docs per the General Directorate of General Security:
#   - lost / stolen  → police report (محضر شرطة)
#   - damaged        → submit the physical damaged passport
#   - name_change    → court ruling (حكم محكمة)
#   - expired / pages_full → no extra docs
#
# The orchestrator looks up declared_fields["renewal_reason"] against
# this map and treats the listed docs as required for that case.
RENEWAL_REASON_EXTRA_DOCS = {
    RenewalReason.EXPIRED: [],
    RenewalReason.PAGES_FULL: [],
    RenewalReason.LOST: [DocumentType.POLICE_REPORT],
    RenewalReason.STOLEN: [DocumentType.POLICE_REPORT],
    RenewalReason.DAMAGED: [DocumentType.DAMAGED_PASSPORT],
    RenewalReason.NAME_CHANGE: [DocumentType.COURT_RULING],
}

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
        # First-time citizen has no prior national ID, so the only
        # face the system has on file is the photo printed on the
        # civil-registry extract (بيان قيد إفرادي). AWS CompareFaces
        # auto-detects the largest face on the page, so we don't have
        # to crop the photo out manually — point it at the full doc.
        "face_reference_doc": DocumentType.CIVIL_REGISTRY_EXTRACT,
        "face_match_required": True,
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
        # Civil-registry extract MUST be OCR'd alongside the old
        # passport. Without it the cross-document identity check sees
        # only one identity-bearing doc and skips with
        # "fewer_than_two_identity_docs" — which lets a citizen submit
        # someone else's passport plus their own registry extract and
        # have the fraud go undetected (case DFL-121F9135 hit exactly
        # this gap before the fix).
        "ocr_documents": [
            DocumentType.OLD_PASSPORT_DATA_PAGE,
            DocumentType.CIVIL_REGISTRY_EXTRACT,
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
            # GDGS form fields the citizen must pick on renewal:
            "renewal_reason", "passport_validity_years",
        ],
    },

    ServiceType.PASSPORT_NEW: {
        "required_documents": [
            # Lebanese law requires a valid national ID to apply for
            # a new passport — promoted from optional so the FE
            # surfaces the upload slots and the orchestrator's OCR
            # pass doesn't fail with "missing document".
            DocumentType.NATIONAL_ID_FRONT,
            DocumentType.NATIONAL_ID_BACK,
            DocumentType.CIVIL_REGISTRY_EXTRACT,
            DocumentType.SELFIE,
            DocumentType.LIVENESS_CAPTURE,
        ],
        "optional_documents": [
            DocumentType.ADDITIONAL_IDENTITY_PROOF,
            DocumentType.GUARDIAN_DOCS,
        ],
        "ocr_documents": [
            DocumentType.NATIONAL_ID_FRONT,
            DocumentType.NATIONAL_ID_BACK,
            DocumentType.CIVIL_REGISTRY_EXTRACT,
        ],
        # Compare the liveness frame against the photo printed on
        # the civil-registry extract. Both national_id_front and the
        # registry extract carry a biometric-quality photo of the
        # citizen; we use the registry extract because it's the doc
        # the GDGS form anchors identity to, and it's required on
        # every passport flow. national_id_front stays in the
        # required_documents list for OCR + identity reconciliation.
        "face_reference_doc": DocumentType.CIVIL_REGISTRY_EXTRACT,
        "face_match_required": True,
        "needs_mrz": False,
        "mukhtar_required": True,
        "declared_fields": [
            "full_name", "father_name", "mother_name", "date_of_birth",
            "place_of_birth", "registry_number", "registry_place",
            # Validity tier drives the fee on passport_new (1y/3y/5y/10y).
            "passport_validity_years",
        ],
    },
}


def get_policy(service_type: str) -> dict:
    try:
        st = ServiceType(service_type)
    except ValueError:
        return {}
    return SERVICE_POLICIES.get(st, {})


def get_required_documents(
    service_type: str,
    declared_fields: dict | None = None,
) -> list[str]:
    """Required docs for a service type.

    For passport_renewal we additionally consult declared_fields[
    "renewal_reason"] and append the extra docs that GDGS requires
    for that specific reason (police report for lost/stolen, court
    ruling for name change, etc).
    """
    policy = get_policy(service_type)
    required = [d.value for d in policy.get("required_documents", [])]

    if service_type == ServiceType.PASSPORT_RENEWAL.value and declared_fields:
        reason_raw = declared_fields.get("renewal_reason")
        if reason_raw:
            try:
                reason = RenewalReason(reason_raw)
            except ValueError:
                reason = None
            if reason:
                for d in RENEWAL_REASON_EXTRA_DOCS.get(reason, []):
                    if d.value not in required:
                        required.append(d.value)
    return required


def get_missing_documents(
    service_type: str,
    uploaded_types: list[str],
    declared_fields: dict | None = None,
) -> list[str]:
    required = get_required_documents(service_type, declared_fields=declared_fields)
    return [d for d in required if d not in uploaded_types]


def check_completeness(
    service_type: str,
    uploaded_types: list[str],
    has_liveness_session: bool = False,
    declared_fields: dict | None = None,
) -> dict:
    """Check if all required documents are uploaded.

    If has_liveness_session is True, selfie and liveness_capture are
    considered satisfied by the Rekognition Liveness session.

    declared_fields lets passport_renewal pull in reason-specific
    supporting docs (police report for lost/stolen, court ruling
    for name change, etc).
    """
    missing = get_missing_documents(service_type, uploaded_types, declared_fields=declared_fields)

    # Liveness session replaces selfie + liveness_capture uploads
    if has_liveness_session:
        liveness_docs = {DocumentType.SELFIE.value, DocumentType.LIVENESS_CAPTURE.value}
        missing = [d for d in missing if d not in liveness_docs]

    required_count = len(get_required_documents(service_type, declared_fields=declared_fields))
    uploaded_count = len(uploaded_types) + (2 if has_liveness_session else 0)

    return {
        "complete": len(missing) == 0,
        "missing_documents": missing,
        "uploaded_count": min(uploaded_count, required_count),
        "required_count": required_count,
    }
