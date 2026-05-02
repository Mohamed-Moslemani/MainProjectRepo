"""Field extraction from OCR text based on document type.

Uses regex patterns tailored to Lebanese document layouts.
This is the rule-based baseline; can be enhanced with ML later.
"""

import re
import logging

logger = logging.getLogger(__name__)

# Patterns for the Lebanese National ID (بطاقة هوية).
#
# Real Lebanese IDs are Arabic-only — there is no Latin name on
# either face. The card splits the holder's name across two
# separate cells: الاسم (first name) and الشهرة (surname).
# The previous pattern set treated الاسم as full_name_ar, which
# is wrong: it captures only the first name. Reconciliation
# against a citizen who declared their full Arabic name then
# fails because "محمد سعد" never matches the extracted "محمد".
#
# Layout reference (front face, two-column):
#   الاسم: محمد              اسم الأم وشهرتها: زهرة أيوب
#   الشهرة: مسلماني           محل الولادة: صور
#   اسم الأب: علي             تاريخ الولادة: ١٩٦١/٠١/١٢
#   رقم بطاقة الهوية: ٠٠٠٤٦٦١٧٧٨
#
# Back face has issuance date, sect (المذهب), marital status
# (الوضع العائلي), district (القضاء), barcode, and the
# village/locale of registration — never the holder's name.
NATIONAL_ID_PATTERNS = {
    # First name — the cell labelled الاسم. Distinct from
    # full_name; reconciliation scores first_name + surname
    # separately rather than fuzzy-matching half a declared name.
    "first_name_ar": r"(?:^|\n)\s*(?:ال)?اسم\s*[:：]?\s*([^\n]+?)\s*(?:\n|$)",
    # Surname — the cell labelled الشهرة.
    "surname_ar":    r"(?:^|\n)\s*(?:ال)?شهرة\s*[:：]?\s*([^\n]+?)\s*(?:\n|$)",
    # Father's first name — اسم الأب.
    "father_name":   r"(?:^|\n)\s*اسم\s*الأب\s*[:：]?\s*([^\n]+?)\s*(?:\n|$)",
    # Mother's full name — Lebanese IDs print BOTH her first name
    # and her own surname under إسم الأم وشهرتها.
    "mother_name":   r"(?:^|\n)\s*(?:إ|ا)سم\s*الأم(?:\s*وشهرتها)?\s*[:：]?\s*([^\n]+?)\s*(?:\n|$)",
    # DOB — accept Eastern Arabic numerals (٠-٩) alongside Latin.
    "date_of_birth": r"تاريخ\s*الولادة\s*[:：]?\s*([\d٠-٩]{1,4}[/\-.][\d٠-٩]{1,2}[/\-.][\d٠-٩]{1,4})",
    "place_of_birth": r"محل\s*الولادة\s*[:：]?\s*([^\n]+?)\s*(?:\n|$)",
    "gender":         r"الجنس\s*[:：]?\s*(ذكر|أنثى|انثى)",
    # ID number is a long digit string; older cards use dots as
    # thousand separators. Strip dots downstream.
    "id_number":      r"(?:رقم\s*بطاقة\s*الهوية|رقم\s*الهوية|رقم\s*السجل)\s*[:：]?\s*([\d.\-٠-٩]+)",
    # Back-of-card fields. national_id_back specifically.
    "issue_date":     r"تاريخ\s*الإصدار\s*[:：]?\s*([\d٠-٩]{1,4}[/\-.][\d٠-٩]{1,2}[/\-.][\d٠-٩]{1,4})",
    "register_place": r"(?:محلة\s*أو\s*القرية|محل\s*السجل)\s*[:：]?\s*([^\n]+?)\s*(?:\n|$)",
    "district":       r"(?:القضاء|المنطقة|المحافظة)\s*[:：]?\s*([^\n]+?)\s*(?:\n|$)",
    "marital_status": r"الوضع\s*العائلي\s*[:：]?\s*(أعزب\w*|عزباء|متزوج\w*|مطلق\w*|أرمل\w*)",
    "religious_sect": r"المذهب\s*[:：]?\s*([^\n]+?)\s*(?:\n|$)",
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
    # intentionally absent. Like the National ID, the document
    # splits the holder's name into separate cells: الإسم (first
    # name only) and الشهرة (surname). The LLM fallback in
    # routers/ocr.py handles cells the regex can't reach (e.g.
    # the spelled-out date next to the numeric DOB).
    "civil_registry_extract": {
        "first_name_ar": r"(?:^|\n)\s*(?:ال)?(?:ا|إ)سم\s*[:：]?\s*([^\n]+?)\s*(?:\n|$)",
        "surname_ar":    r"(?:^|\n)\s*(?:ال)?شهرة\s*[:：]?\s*([^\n]+?)\s*(?:\n|$)",
        "father_name":   r"(?:إ|ا)سم\s*الأب\s*[:：]?\s*([^\n]+?)\s*(?:\n|$)",
        "mother_name":   r"(?:إ|ا)سم\s*الأم(?:\s*وشهرتها)?\s*[:：]?\s*([^\n]+?)\s*(?:\n|$)",
        "date_of_birth": r"تاريخ\s*الولادة\s*[:：]?\s*([\d٠-٩]{4}[/\-.][\d٠-٩]{1,2}[/\-.][\d٠-٩]{1,2}|[\d٠-٩]{1,2}[/\-.][\d٠-٩]{1,2}[/\-.][\d٠-٩]{2,4})",
        "place_of_birth": r"محل\s*الولادة\s*[:：]?\s*([^\n]+?)\s*(?:\n|$)",
        "gender":         r"الجنس\s*[:：]?\s*(ذكر|أنثى|انثى)",
        "id_number":      r"(?:رقم\s*بطاقة\s*الهوية|رقم\s*الهوية)\s*[:：]?\s*([\d.\-٠-٩]+)",
        "register_place": r"(?:محل\s*ورقم\s*القيد|محل\s*القيد|محل\s*السجل)\s*[:：]?\s*([^\n]+?)\s*(?:\n|$)",
        "district":       r"(?:القضاء|المنطقة)\s*[:：]?\s*([^\n]+?)\s*(?:\n|$)",
        "religious_sect": r"المذهب\s*[:：]?\s*([^\n]+?)\s*(?:\n|$)",
        "marital_status": r"الوضع\s*العائلي\s*[:：]?\s*(أعزب\w*|عزباء|متزوج\w*|مطلق\w*|أرمل\w*)",
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

    # Synthesise full_name_ar from the two cells where it lives on
    # Lebanese ID + civil-registry extracts. The citizen declares a
    # single `full_name` field at registration; without this join,
    # reconciliation only ever compares the declared full name to
    # half the document (the first name OR the surname), partial-matches,
    # and pulls integrity_score down. We keep first_name_ar +
    # surname_ar in the output too so a future audit can still see
    # the cells separately.
    first = fields.get("first_name_ar", "").strip()
    last = fields.get("surname_ar", "").strip()
    if first or last:
        full = f"{first} {last}".strip()
        if full:
            fields["full_name_ar"] = full
            # Confidence is the min of the parts (either part missing
            # = the join is incomplete; either part low-confidence =
            # the join is unreliable).
            parts = [confidence_scores.get(k, 0.0) for k in ("first_name_ar", "surname_ar") if fields.get(k)]
            confidence_scores["full_name_ar"] = min(parts) if parts else 0.0

    return {"fields": fields, "confidence_scores": confidence_scores}
