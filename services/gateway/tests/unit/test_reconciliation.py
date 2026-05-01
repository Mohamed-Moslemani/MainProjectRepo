"""Unit tests for the reconciliation service."""

import pytest

from app.services.reconciliation import (
    normalize,
    compare_field,
    reconcile,
    MATCH_THRESHOLD,
    MISMATCH_THRESHOLD,
    FIELD_MAPPING,
)


class TestNormalize:
    def test_strips_whitespace(self):
        assert normalize("  hello  ") == "hello"

    def test_lowercases(self):
        assert normalize("HELLO") == "hello"

    def test_strips_slashes_dashes_dots(self):
        """Date formats 01/15/1995 and 01-15-1995 and 01.15.1995 should normalize equal."""
        assert normalize("01/15/1995") == normalize("01-15-1995") == normalize("01.15.1995")

    def test_combined_normalization(self):
        # Punctuation -> space + whitespace collapse, so a date string
        # with mixed delimiters folds to a single space-separated form.
        assert normalize("  01/15/1995  ") == "01 15 1995"


class TestCompareField:
    def test_exact_match(self):
        r = compare_field("John Doe", "john doe")
        assert r["match"] is True
        assert r["similarity"] == 1.0
        assert r["status"] == "exact_match"

    def test_close_match(self):
        """Minor typo should still match (ratio >= 0.85)."""
        r = compare_field("Mohamed", "Mohammed")  # one char off
        assert r["similarity"] >= MATCH_THRESHOLD
        assert r["match"] is True
        assert r["status"] == "close_match"

    def test_partial_match(self):
        """Below match threshold but above mismatch threshold → partial_match, not a match."""
        r = compare_field("Beirut", "Beiruth")
        # This is actually ~0.92 similar so would be close_match — use a more different pair
        r = compare_field("1995-06-15", "1995-07-20")
        assert MISMATCH_THRESHOLD <= r["similarity"] < MATCH_THRESHOLD
        assert r["match"] is False
        assert r["status"] == "partial_match"

    def test_mismatch(self):
        r = compare_field("Mohamed Saad", "Layla Qasimi")
        assert r["similarity"] < MISMATCH_THRESHOLD
        assert r["match"] is False
        assert r["status"] == "mismatch"

    def test_normalization_applied_before_compare(self):
        """Different formatting of the same value → exact match."""
        r = compare_field("01/15/1995", "01-15-1995")
        assert r["match"] is True
        assert r["similarity"] == 1.0
        assert r["status"] == "exact_match"


class TestReconcileBasic:
    def test_all_matching_fields_pass(self):
        declared = {
            "full_name": "Mohamed Saad",
            "date_of_birth": "1995-06-15",
            "registry_number": "12345",
        }
        ocr = {
            "full_name": "Mohamed Saad",
            "date_of_birth": "1995-06-15",
            "registry_number": "12345",
        }
        result = reconcile(declared, ocr)
        assert result["integrity_score"] == 1.0
        assert result["matched_fields"] == 3
        assert result["total_fields"] == 3
        assert result["mismatch_flags"] == []
        assert result["validation_result"] == "pass"

    def test_one_mismatch_leads_to_need_info(self):
        declared = {
            "full_name": "Mohamed Saad",
            "date_of_birth": "1995-06-15",
            "registry_number": "12345",
        }
        ocr = {
            "full_name": "Mohamed Saad",
            "date_of_birth": "1995-07-20",  # mismatch
            "registry_number": "12345",
        }
        result = reconcile(declared, ocr)
        assert "date_of_birth" in result["mismatch_flags"]
        assert result["validation_result"] == "need_info"

    def test_three_mismatches_fail(self):
        declared = {
            "full_name": "Mohamed Saad",
            "father_name": "Ali",
            "mother_name": "Fatima",
            "date_of_birth": "1995-06-15",
        }
        ocr = {
            "full_name": "Completely Different Name",
            "father_name": "Other Father",
            "mother_name": "Other Mother",
            "date_of_birth": "1995-06-15",
        }
        result = reconcile(declared, ocr)
        assert len(result["mismatch_flags"]) >= 3
        assert result["validation_result"] == "fail"

    def test_low_integrity_fails(self):
        """integrity_score < 0.4 → fail even with only 2 mismatches out of 2."""
        declared = {"full_name": "A", "father_name": "B"}
        ocr = {"full_name": "Zzz", "father_name": "Yyy"}
        result = reconcile(declared, ocr)
        assert result["integrity_score"] < 0.4
        assert result["validation_result"] == "fail"


class TestReconcileFieldMapping:
    def test_declared_full_name_maps_to_alternate_ocr_keys(self):
        """declared full_name should be found via full_name_en, surname, etc."""
        assert "full_name_en" in FIELD_MAPPING["full_name"]

        declared = {"full_name": "Mohamed Saad"}
        ocr = {"full_name_en": "Mohamed Saad"}  # alternate key name
        result = reconcile(declared, ocr)
        assert result["field_results"]["full_name"]["match"] is True
        assert result["field_results"]["full_name"]["extracted"] == "Mohamed Saad"

    def test_registry_number_maps_to_id_number(self):
        """registry_number can be extracted under id_number on national IDs."""
        assert "id_number" in FIELD_MAPPING["registry_number"]
        declared = {"registry_number": "12345"}
        ocr = {"id_number": "12345"}
        result = reconcile(declared, ocr)
        assert result["field_results"]["registry_number"]["match"] is True


class TestReconcileMissingFields:
    def test_not_found_in_ocr_flagged(self):
        declared = {"full_name": "Mohamed", "address": "Beirut"}
        ocr = {"full_name": "Mohamed"}  # no address in OCR
        result = reconcile(declared, ocr)
        assert "address" in result["not_found_fields"]
        # not_found_in_ocr entries do NOT count as mismatch_flags (those are compared mismatches only)
        assert "address" not in result["mismatch_flags"]
        assert result["field_results"]["address"]["status"] == "not_found_in_ocr"

    def test_empty_declared_value_is_skipped(self):
        """Empty declared values should not be evaluated at all."""
        declared = {"full_name": "Mohamed", "address": ""}
        ocr = {"full_name": "Mohamed"}
        result = reconcile(declared, ocr)
        assert "address" not in result["field_results"]
        assert result["total_fields"] == 1


class TestReconcileOutputShape:
    def test_result_contains_all_expected_keys(self):
        result = reconcile({"full_name": "A"}, {"full_name": "A"})
        expected = {
            "field_results", "mismatch_flags", "not_found_fields",
            "integrity_score", "validation_result",
            "total_fields", "matched_fields",
        }
        assert set(result.keys()) == expected

    def test_each_field_result_has_status_declared_extracted(self):
        result = reconcile({"full_name": "A"}, {"full_name": "A"})
        fr = result["field_results"]["full_name"]
        assert "match" in fr
        assert "similarity" in fr
        assert "status" in fr
        assert "declared" in fr
        assert "extracted" in fr


class TestReconcileEdgeCases:
    def test_empty_inputs(self):
        """No declared fields → integrity 0, no flags."""
        result = reconcile({}, {})
        assert result["integrity_score"] == 0.0
        assert result["total_fields"] == 0
        assert result["mismatch_flags"] == []

    def test_ocr_empty_but_declared_filled(self):
        """All declared fields not found in OCR → all flagged as not_found."""
        declared = {"full_name": "Mohamed", "date_of_birth": "1995-06-15"}
        result = reconcile(declared, {})
        assert len(result["not_found_fields"]) == 2
        assert result["integrity_score"] == 0.0

    def test_passport_number_maps_to_old_passport_number(self):
        """declared old_passport_number should match OCR passport_number."""
        assert "passport_number" in FIELD_MAPPING["old_passport_number"]
        declared = {"old_passport_number": "LB1234567"}
        ocr = {"passport_number": "LB1234567"}
        result = reconcile(declared, ocr)
        assert result["field_results"]["old_passport_number"]["match"] is True
