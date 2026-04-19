"""Reconciliation service - compares user-declared fields against OCR-extracted fields.

Produces:
- Field-by-field match/mismatch report
- Integrity score
- Validation result: PASS / NEED_INFO / FAIL
"""

import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# Fields to reconcile (declared field name -> possible OCR field names)
FIELD_MAPPING = {
    "full_name": ["full_name", "full_name_ar", "full_name_en", "surname", "given_names"],
    "father_name": ["father_name"],
    "mother_name": ["mother_name"],
    "date_of_birth": ["date_of_birth"],
    "registry_number": ["registry_number", "id_number", "register_number"],
    "place_of_birth": ["place_of_birth"],
    "old_passport_number": ["passport_number"],
}

# Minimum similarity ratio for a "match"
MATCH_THRESHOLD = 0.85
# Below this = definite mismatch
MISMATCH_THRESHOLD = 0.5


def normalize(value: str) -> str:
    """Normalize a field value for comparison."""
    return value.strip().lower().replace("-", "").replace("/", "").replace(".", "")


def compare_field(declared: str, extracted: str) -> dict:
    """Compare a single declared value against an extracted value."""
    d = normalize(declared)
    e = normalize(extracted)

    if d == e:
        return {"match": True, "similarity": 1.0, "status": "exact_match"}

    ratio = SequenceMatcher(None, d, e).ratio()

    if ratio >= MATCH_THRESHOLD:
        return {"match": True, "similarity": round(ratio, 4), "status": "close_match"}
    elif ratio >= MISMATCH_THRESHOLD:
        return {"match": False, "similarity": round(ratio, 4), "status": "partial_match"}
    else:
        return {"match": False, "similarity": round(ratio, 4), "status": "mismatch"}


def reconcile(
    declared_fields: dict[str, str],
    ocr_fields: dict[str, str],
) -> dict:
    """Run field-by-field reconciliation.

    Args:
        declared_fields: User-submitted form data.
        ocr_fields: Fields extracted by OCR from documents.

    Returns:
        {
            "field_results": {field: {match, similarity, status, declared, extracted}},
            "mismatch_flags": [field_names with mismatches],
            "integrity_score": float (0-1),
            "validation_result": "pass" | "need_info" | "fail",
        }
    """
    field_results = {}
    matches = 0
    total = 0

    for declared_key, declared_value in declared_fields.items():
        if not declared_value:
            continue

        # Find matching OCR field
        ocr_keys = FIELD_MAPPING.get(declared_key, [declared_key])
        extracted_value = None
        for ok in ocr_keys:
            if ok in ocr_fields and ocr_fields[ok]:
                extracted_value = ocr_fields[ok]
                break

        if extracted_value is None:
            field_results[declared_key] = {
                "match": False,
                "similarity": 0.0,
                "status": "not_found_in_ocr",
                "declared": declared_value,
                "extracted": None,
            }
            total += 1
            continue

        result = compare_field(declared_value, extracted_value)
        result["declared"] = declared_value
        result["extracted"] = extracted_value
        field_results[declared_key] = result

        total += 1
        if result["match"]:
            matches += 1

    integrity_score = matches / total if total > 0 else 0.0

    mismatch_flags = [
        f for f, r in field_results.items()
        if not r["match"] and r["status"] != "not_found_in_ocr"
    ]
    not_found = [
        f for f, r in field_results.items() if r["status"] == "not_found_in_ocr"
    ]

    # Decide validation result
    if integrity_score >= 0.9 and len(mismatch_flags) == 0:
        validation_result = "pass"
    elif len(mismatch_flags) >= 3 or integrity_score < 0.4:
        validation_result = "fail"
    else:
        validation_result = "need_info"

    return {
        "field_results": field_results,
        "mismatch_flags": mismatch_flags,
        "not_found_fields": not_found,
        "integrity_score": round(integrity_score, 4),
        "validation_result": validation_result,
        "total_fields": total,
        "matched_fields": matches,
    }
