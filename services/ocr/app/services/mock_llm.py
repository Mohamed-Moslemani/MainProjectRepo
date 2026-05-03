"""Mock LLM-extractor fixtures for OCR_MOCK_MODE.

Now that the LLM is the only field extractor (regex was dropped in
favour of always going through gpt-4o), mock-mode E2E tests need a
deterministic stand-in that returns canonical fields per doc type
without making a real OpenAI call.

Identity here mirrors the OCR text fixtures in mocks.py so a case
that uploads multiple docs reconciles cleanly: same name, same
DOB, same registry number, same passport number.
"""

from __future__ import annotations

# Canonical demo identity:
#   first name : Mohamed / محمد
#   surname    : Saad    / سعد
#   father     : Ali     / علي
#   mother     : Fatima Hassan / فاطمة حسن
#   DOB        : 1995-06-15
#   registry # : 12345
#   passport # : LR1234567
_LEBANESE_ID_FIELDS = {
    # Real Lebanese IDs are Arabic-only; this fixture mirrors that.
    # The Latin keys (full_name, father_name, mother_name) are
    # included as well because the seed test cases declare Latin
    # transliterations and the reconciliation FIELD_MAPPING tries
    # both Arabic and Latin candidates per declared field.
    "first_name_ar":  "محمد",
    "surname_ar":     "سعد",
    "full_name":      "Mohamed Saad",
    "father_name":    "Ali Saad",
    "mother_name":    "Fatima Hassan",
    "date_of_birth":  "1995-06-15",
    "place_of_birth": "Beirut",
    "gender":         "ذكر",
    "id_number":      "12345",
    "register_place": "Beirut 1",
    "district":       "Beirut",
    "religious_sect": "Sunni",
    "marital_status": "single",
}

_LEBANESE_PASSPORT_FIELDS = {
    "surname":         "SAAD",
    "given_names":     "MOHAMED",
    "surname_ar":      "سعد",
    "first_name_ar":   "محمد",
    "father_name":     "علي",
    "mother_name":     "فاطمة حسن",
    "passport_number": "LR1234567",
    "nationality":     "LBN",
    "date_of_birth":   "1995-06-15",
    "place_of_birth":  "BEIRUT",
    "sex":             "M",
    "date_of_issue":   "2020-01-01",
    "date_of_expiry":  "2030-01-01",
    "registry_place":  "12345",
}

_ID_BACK_FIELDS = {
    "id_number":      "12345",
    "issue_date":     "2020-01-01",
    "expiry_date":    "2030-01-01",
    "register_place": "بيروت 1",
    "district":       "بيروت",
    "religious_sect": "سني",
    "marital_status": "أعزب",
}

_LEBANESE_PASSPORT_TOP_FIELDS = {
    k: v for k, v in _LEBANESE_PASSPORT_FIELDS.items()
    # Top half carries everything *except* the MRZ-derived block.
    # We keep all the printed visual fields here so reconciliation
    # has plenty to match against from a single half.
}

_LEBANESE_PASSPORT_BOTTOM_FIELDS = {
    "mrz_line_1": "P<LBNSAAD<<MOHAMED<<<<<<<<<<<<<<<<<<<<<<<<<<",
    "mrz_line_2": "LR12345678LBN9506157M3001017<<<<<<<<<<<<<<00",
    "mrz_llm_passport_number": "LR1234567",
    "mrz_llm_surname":         "SAAD",
    "mrz_llm_given_names":     "MOHAMED",
    "mrz_llm_date_of_birth":   "1995-06-15",
    "mrz_llm_date_of_expiry":  "2030-01-01",
    "mrz_llm_nationality":     "LBN",
    "mrz_llm_sex":             "M",
    "issuing_authority":       "GENERAL DIRECTORATE OF GENERAL SECURITY",
}

_BIRTH_CERT_FIELDS = {
    "first_name_ar":   "محمد",
    "surname_ar":      "سعد",
    "father_name":     "علي",
    "mother_name":     "فاطمة حسن",
    "date_of_birth":   "1995-06-15",
    "place_of_birth":  "بيروت",
    "register_number": "98765",
}

MOCK_LLM_FIELDS: dict[str, dict[str, str]] = {
    "civil_registry_extract":  _LEBANESE_ID_FIELDS,
    "national_id_front":       _LEBANESE_ID_FIELDS,
    "old_id_front":            _LEBANESE_ID_FIELDS,
    "national_id_back":        _ID_BACK_FIELDS,
    "old_id_back":             _ID_BACK_FIELDS,
    "passport_data_page":              _LEBANESE_PASSPORT_FIELDS,
    "old_passport_data_page":          _LEBANESE_PASSPORT_FIELDS,
    "passport_data_page_top":          _LEBANESE_PASSPORT_TOP_FIELDS,
    "passport_data_page_bottom":       _LEBANESE_PASSPORT_BOTTOM_FIELDS,
    "old_passport_data_page_top":      _LEBANESE_PASSPORT_TOP_FIELDS,
    "old_passport_data_page_bottom":   _LEBANESE_PASSPORT_BOTTOM_FIELDS,
    "birth_certificate":               _BIRTH_CERT_FIELDS,
}
