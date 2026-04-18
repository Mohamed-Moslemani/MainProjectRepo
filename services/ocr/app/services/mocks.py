"""Fixture-based mock responses for OCR.

Activated by setting OCR_MOCK_MODE=1. Lets E2E tests exercise the full
pipeline without calling Google Cloud Vision (no API cost, no credentials
required, deterministic output).

Fixtures return the happy-path response shape — clean fields, high word
confidence, readable quality. Tests that need to exercise failure paths
should use unit tests with explicit patches rather than mock mode.
"""

_NATIONAL_ID_FULL_TEXT = (
    "Lebanese Republic\n"
    "National ID\n"
    "Name: Mohamed Saad\n"
    "Father: Ali Saad\n"
    "Mother: Fatima Hassan\n"
    "Date of Birth: 15/06/1995\n"
    "Place of Birth: Beirut\n"
    "Gender: Male\n"
    "Record No: 12345\n"
)

_PASSPORT_FULL_TEXT = (
    "Lebanese Republic\n"
    "Passport\n"
    "Surname: SAAD\n"
    "Given Names: MOHAMED\n"
    "Passport No: LB1234567\n"
    "Nationality: Lebanese\n"
    "Date of Birth: 15/06/1995\n"
    "Sex: M\n"
    "Place of Birth: Beirut\n"
    "Date of Issue: 01/01/2020\n"
    "Date of Expiry: 01/01/2030\n"
    "P<LBNSAAD<<MOHAMED<<<<<<<<<<<<<<<<<<<<<<<<<<\n"
    "LB12345678LBN9506158M3001019<<<<<<<<<<<<<<00\n"
)

_BIRTH_CERT_FULL_TEXT = (
    "Republic of Lebanon\n"
    "Birth Certificate\n"
    "Full Name: Mohamed Saad\n"
    "Date of Birth: 15/06/1995\n"
    "Place of Birth: Beirut\n"
    "Father: Ali Saad\n"
    "Mother: Fatima Hassan\n"
    "Register No: 98765\n"
)


_TEXT_BY_TYPE = {
    "national_id": _NATIONAL_ID_FULL_TEXT,
    "old_id": _NATIONAL_ID_FULL_TEXT,
    "civil_registry_extract": _NATIONAL_ID_FULL_TEXT,
    "national_id_front": _NATIONAL_ID_FULL_TEXT,
    "national_id_back": _NATIONAL_ID_FULL_TEXT,
    "old_id_front": _NATIONAL_ID_FULL_TEXT,
    "old_id_back": _NATIONAL_ID_FULL_TEXT,
    "old_passport": _PASSPORT_FULL_TEXT,
    "old_passport_data_page": _PASSPORT_FULL_TEXT,
    "passport_data_page": _PASSPORT_FULL_TEXT,
    "birth_certificate": _BIRTH_CERT_FULL_TEXT,
}


def mock_extract_text(image_path: str, document_type: str | None = None) -> dict:
    """Return a deterministic Google-Vision-shaped response."""
    text = _TEXT_BY_TYPE.get(document_type or "", _NATIONAL_ID_FULL_TEXT)
    words = [
        {"text": tok, "confidence": 0.95}
        for line in text.splitlines()
        for tok in line.split()
        if tok
    ]
    return {
        "full_text": text,
        "words": words,
        "processing_time_ms": 10,
    }


def mock_assess_quality(image_path: str) -> dict:
    """Return a 'clean, readable' quality report without touching cv2."""
    return {
        "is_readable": True,
        "is_blurry": False,
        "blur_score": 250.0,
        "glare_detected": False,
        "angle_ok": True,
        "resolution_ok": True,
        "issues": [],
    }
