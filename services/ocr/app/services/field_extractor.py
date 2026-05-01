"""Field extraction from OCR text based on document type.

Uses regex patterns tailored to Lebanese document layouts.
This is the rule-based baseline; can be enhanced with ML later.
"""

import re
import logging

logger = logging.getLogger(__name__)

# Patterns for Lebanese National ID
NATIONAL_ID_PATTERNS = {
    "full_name_ar": r"الاسم[:\s]+(.+?)(?:\n|$)",
    "full_name_en": r"Name[:\s]+(.+?)(?:\n|$)",
    "father_name": r"(?:اسم الأب|Father)[:\s]+(.+?)(?:\n|$)",
    "mother_name": r"(?:اسم الأم|Mother)[:\s]+(.+?)(?:\n|$)",
    "date_of_birth": r"(?:تاريخ الولادة|Date of Birth|DOB)[:\s]+([\d]{1,2}[/\-.][\d]{1,2}[/\-.][\d]{2,4})",
    "place_of_birth": r"(?:محل الولادة|Place of Birth)[:\s]+(.+?)(?:\n|$)",
    "gender": r"(?:الجنس|Sex|Gender)[:\s]+([\w\u0600-\u06FF]+)",
    "id_number": r"(?:رقم السجل|Record No|ID No)[:\s]*([\d]+)",
    "register_place": r"(?:محل السجل|Register)[:\s]+(.+?)(?:\n|$)",
}

# Patterns for Lebanese Passport
PASSPORT_PATTERNS = {
    "surname": r"(?:Surname|النسبة)[:\s]+([A-Z\s]+?)(?:\n|$)",
    "given_names": r"(?:Given [Nn]ames?|الاسم)[:\s]+([A-Z\s]+?)(?:\n|$)",
    "passport_number": r"(?:Passport No|رقم الجواز)[:\s]*([A-Z]{0,2}\d{6,8})",
    "nationality": r"(?:Nationality|الجنسية)[:\s]+(.+?)(?:\n|$)",
    "date_of_birth": r"(?:Date of [Bb]irth|تاريخ الولادة)[:\s]+([\d]{1,2}[/\-.][\d]{1,2}[/\-.][\d]{2,4})",
    "sex": r"(?:Sex|الجنس)[:\s]+([MF]|Male|Female|ذكر|أنثى)",
    "place_of_birth": r"(?:Place of [Bb]irth|محل الولادة)[:\s]+(.+?)(?:\n|$)",
    "date_of_issue": r"(?:Date of [Ii]ssue|تاريخ الإصدار)[:\s]+([\d]{1,2}[/\-.][\d]{1,2}[/\-.][\d]{2,4})",
    "date_of_expiry": r"(?:Date of [Ee]xpiry|تاريخ الانتهاء)[:\s]+([\d]{1,2}[/\-.][\d]{1,2}[/\-.][\d]{2,4})",
}

# MRZ (Machine Readable Zone) pattern for passports
MRZ_PATTERN = r"[A-Z<]{2}[A-Z<]{3}[A-Z<]{39}\n[\w<]{44}"

BIRTH_CERTIFICATE_PATTERNS = {
    "full_name": r"(?:الاسم الكامل|Full Name)[:\s]+(.+?)(?:\n|$)",
    "date_of_birth": r"(?:تاريخ الولادة|Date of Birth)[:\s]+([\d]{1,2}[/\-.][\d]{1,2}[/\-.][\d]{2,4})",
    "place_of_birth": r"(?:محل الولادة|Place of Birth)[:\s]+(.+?)(?:\n|$)",
    "father_name": r"(?:اسم الأب|Father)[:\s]+(.+?)(?:\n|$)",
    "mother_name": r"(?:اسم الأم|Mother)[:\s]+(.+?)(?:\n|$)",
    "register_number": r"(?:رقم السجل|Register No)[:\s]*([\d]+)",
}

PATTERN_MAP = {
    # Legacy/generic keys
    "national_id": NATIONAL_ID_PATTERNS,
    "old_id": NATIONAL_ID_PATTERNS,
    "old_passport": PASSPORT_PATTERNS,
    "birth_certificate": BIRTH_CERTIFICATE_PATTERNS,
    # Concrete DocumentType values used by the orchestrator
    "national_id_front": NATIONAL_ID_PATTERNS,
    "national_id_back": NATIONAL_ID_PATTERNS,
    "old_id_front": NATIONAL_ID_PATTERNS,
    "old_id_back": NATIONAL_ID_PATTERNS,
    "passport_data_page": PASSPORT_PATTERNS,
    "old_passport_data_page": PASSPORT_PATTERNS,
    # Civil registry has its own dedicated pattern set — Lebanese
    # civil records don't print Latin names so full_name_en is
    # intentionally absent. Regex won't realistically extract from
    # this 3-column table; the LLM fallback in routers/ocr.py is
    # the actual extractor for this doc type.
    "civil_registry_extract": {
        "full_name_ar": r"(?:الإسم|الاسم)[:\s]+(.+?)(?:\n|$)",
        "father_name":  r"(?:إسم الأب|اسم الأب)[:\s]+(.+?)(?:\n|$)",
        "mother_name":  r"(?:إسم الأم(?: وشهرتها)?|اسم الأم(?: وشهرتها)?)[:\s]+(.+?)(?:\n|$)",
        "date_of_birth": r"تاريخ الولادة[:\s]+(\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2}|\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})",
        "place_of_birth": r"محل الولادة[:\s]+(.+?)(?:\n|$)",
        "gender": r"الجنس[:\s]+(ذكر|أنثى|انثى)",
        "id_number": r"(?:رقم بطاقة الهوية|رقم الهوية)[:\s]*([\d.\-]+)",
        "register_place": r"(?:محل ورقم القيد|محل القيد|محل السجل)[:\s]+(.+?)(?:\n|$)",
    },
}


def extract_fields(full_text: str, document_type: str, word_confidences: list[dict]) -> dict:
    """Extract structured fields from OCR text using regex patterns.

    Returns:
        {
            "fields": {"field_name": "value", ...},
            "confidence_scores": {"field_name": float, ...},
        }
    """
    patterns = PATTERN_MAP.get(document_type, {})
    fields = {}
    confidence_scores = {}

    # Average word confidence as baseline
    avg_confidence = 0.0
    if word_confidences:
        avg_confidence = sum(w["confidence"] for w in word_confidences) / len(word_confidences)

    for field_name, pattern in patterns.items():
        match = re.search(pattern, full_text, re.IGNORECASE | re.MULTILINE)
        if match:
            value = match.group(1).strip()
            fields[field_name] = value
            # Confidence = average of word confidences for matched text
            matched_words = [
                w["confidence"] for w in word_confidences
                if w["text"].lower() in value.lower()
            ]
            confidence_scores[field_name] = (
                sum(matched_words) / len(matched_words) if matched_words else avg_confidence
            )
        else:
            confidence_scores[field_name] = 0.0

    # Try MRZ extraction for passport types
    if document_type in ("old_passport", "old_passport_data_page", "passport_data_page"):
        mrz_match = re.search(MRZ_PATTERN, full_text)
        if mrz_match:
            fields["mrz"] = mrz_match.group(0)
            confidence_scores["mrz"] = 0.95  # MRZ is machine-printed, high confidence

    return {"fields": fields, "confidence_scores": confidence_scores}
