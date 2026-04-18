"""Unit tests for regex-based field extraction from OCR text."""

import pytest

from app.services.field_extractor import (
    extract_fields,
    PATTERN_MAP,
    NATIONAL_ID_PATTERNS,
    PASSPORT_PATTERNS,
    BIRTH_CERTIFICATE_PATTERNS,
)


# ── Sample OCR texts ────────────────────────────────────────────────────

NATIONAL_ID_TEXT_EN = """Lebanese Republic
National ID

Name: Mohamed Saad
Father: Ali Saad
Mother: Fatima Hassan
Date of Birth: 15/06/1995
Place of Birth: Beirut
Gender: Male
Record No: 12345
Register: Beirut
"""

NATIONAL_ID_TEXT_AR = """الجمهورية اللبنانية
الاسم: محمد سعد
اسم الأب: علي سعد
اسم الأم: فاطمة حسن
تاريخ الولادة: 15/06/1995
محل الولادة: بيروت
الجنس: ذكر
رقم السجل: 12345
"""

PASSPORT_TEXT = """Lebanese Republic
Passport

Surname: SAAD
Given Names: MOHAMED
Passport No: LB1234567
Nationality: Lebanese
Date of Birth: 15/06/1995
Sex: M
Place of Birth: Beirut
Date of Issue: 01/01/2020
Date of Expiry: 01/01/2030

P<LBNSAAD<<MOHAMED<<<<<<<<<<<<<<<<<<<<<<<<<<
LB12345678LBN9506158M3001019<<<<<<<<<<<<<<00
"""

BIRTH_CERT_TEXT = """Republic of Lebanon
Birth Certificate

Full Name: Mohamed Saad
Date of Birth: 15/06/1995
Place of Birth: Beirut
Father: Ali Saad
Mother: Fatima Hassan
Register No: 98765
"""


class TestPatternMap:
    def test_national_id_and_old_id_share_patterns(self):
        assert PATTERN_MAP["national_id"] is NATIONAL_ID_PATTERNS
        assert PATTERN_MAP["old_id"] is NATIONAL_ID_PATTERNS

    def test_old_passport_uses_passport_patterns(self):
        assert PATTERN_MAP["old_passport"] is PASSPORT_PATTERNS

    def test_birth_certificate_has_own_patterns(self):
        assert PATTERN_MAP["birth_certificate"] is BIRTH_CERTIFICATE_PATTERNS


class TestExtractNationalIdEN:
    def _extract(self):
        return extract_fields(NATIONAL_ID_TEXT_EN, "national_id", [])

    def test_returns_dict_with_fields_and_confidence(self):
        result = self._extract()
        assert "fields" in result
        assert "confidence_scores" in result

    def test_extracts_english_name(self):
        fields = self._extract()["fields"]
        assert fields["full_name_en"] == "Mohamed Saad"

    def test_extracts_father_name(self):
        fields = self._extract()["fields"]
        assert fields["father_name"] == "Ali Saad"

    def test_extracts_mother_name(self):
        fields = self._extract()["fields"]
        assert fields["mother_name"] == "Fatima Hassan"

    def test_extracts_date_of_birth(self):
        fields = self._extract()["fields"]
        assert fields["date_of_birth"] == "15/06/1995"

    def test_extracts_id_number(self):
        fields = self._extract()["fields"]
        assert fields["id_number"] == "12345"

    def test_extracts_place_of_birth(self):
        fields = self._extract()["fields"]
        assert fields["place_of_birth"] == "Beirut"


class TestExtractNationalIdArabic:
    def _extract(self):
        return extract_fields(NATIONAL_ID_TEXT_AR, "national_id", [])

    def test_extracts_arabic_name(self):
        fields = self._extract()["fields"]
        assert fields["full_name_ar"] == "محمد سعد"

    def test_extracts_arabic_father(self):
        fields = self._extract()["fields"]
        assert fields["father_name"] == "علي سعد"

    def test_extracts_arabic_dob(self):
        fields = self._extract()["fields"]
        assert fields["date_of_birth"] == "15/06/1995"


class TestExtractPassport:
    def _extract(self):
        return extract_fields(PASSPORT_TEXT, "old_passport", [])

    def test_extracts_passport_number(self):
        fields = self._extract()["fields"]
        assert fields["passport_number"] == "LB1234567"

    def test_extracts_surname(self):
        fields = self._extract()["fields"]
        assert fields["surname"].strip() == "SAAD"

    def test_extracts_sex(self):
        fields = self._extract()["fields"]
        assert fields["sex"] == "M"

    def test_extracts_date_of_birth(self):
        fields = self._extract()["fields"]
        assert fields["date_of_birth"] == "15/06/1995"

    def test_extracts_date_of_expiry(self):
        fields = self._extract()["fields"]
        assert fields["date_of_expiry"] == "01/01/2030"

    def test_mrz_line_captured(self):
        """MRZ block is picked up as a `mrz` field (raw text)."""
        fields = self._extract()["fields"]
        assert "mrz" in fields
        assert fields["mrz"].startswith("P<LBN")


class TestExtractBirthCertificate:
    def _extract(self):
        return extract_fields(BIRTH_CERT_TEXT, "birth_certificate", [])

    def test_extracts_full_name(self):
        fields = self._extract()["fields"]
        assert fields["full_name"] == "Mohamed Saad"

    def test_extracts_register_number(self):
        fields = self._extract()["fields"]
        assert fields["register_number"] == "98765"

    def test_extracts_dob_and_pob(self):
        fields = self._extract()["fields"]
        assert fields["date_of_birth"] == "15/06/1995"
        assert fields["place_of_birth"] == "Beirut"


class TestUnknownDocumentType:
    def test_unknown_type_returns_empty_fields(self):
        result = extract_fields("arbitrary text", "unknown_doc", [])
        assert result["fields"] == {}
        assert result["confidence_scores"] == {}


class TestConfidenceScores:
    def test_missing_field_has_zero_confidence(self):
        """When OCR text has none of the patterns, all scores are 0.0."""
        result = extract_fields("garbage text with no labels", "national_id", [])
        scores = result["confidence_scores"]
        assert len(scores) == len(NATIONAL_ID_PATTERNS)
        assert all(v == 0.0 for v in scores.values())

    def test_matched_field_uses_word_confidences(self):
        """Word confidences are averaged into the field confidence when words are present."""
        text = "Name: MOHAMED\n"
        words = [{"text": "MOHAMED", "confidence": 0.95}]
        result = extract_fields(text, "national_id", words)
        assert result["confidence_scores"]["full_name_en"] == pytest.approx(0.95)

    def test_matched_field_falls_back_to_avg_when_no_word_match(self):
        """When no word in word_confidences matches the extracted value, fall back to overall average."""
        text = "Name: Mohamed Saad\n"
        words = [
            {"text": "foo", "confidence": 0.8},
            {"text": "bar", "confidence": 0.6},
        ]
        result = extract_fields(text, "national_id", words)
        # avg = 0.7; name present → falls back to avg because no matching words
        assert result["confidence_scores"]["full_name_en"] == pytest.approx(0.7)

    def test_no_words_yields_zero_avg_for_fallback(self):
        """Empty word_confidences list means avg_confidence=0; fields present but with 0 confidence."""
        text = "Name: Mohamed\n"
        result = extract_fields(text, "national_id", [])
        assert result["fields"]["full_name_en"] == "Mohamed"
        assert result["confidence_scores"]["full_name_en"] == 0.0


class TestCaseInsensitivity:
    def test_lowercase_labels_still_match(self):
        text = "name: Layla\nfather: Youssef\n"
        fields = extract_fields(text, "national_id", [])["fields"]
        assert fields["full_name_en"] == "Layla"
        assert fields["father_name"] == "Youssef"


class TestMultilineSafety:
    def test_extracted_value_does_not_span_newlines(self):
        """Regex uses `.+?` with `(?:\\n|$)` terminator — shouldn't swallow next line."""
        text = "Name: Mohamed\nFather: Ali\n"
        fields = extract_fields(text, "national_id", [])["fields"]
        assert fields["full_name_en"] == "Mohamed"
        assert fields["father_name"] == "Ali"
