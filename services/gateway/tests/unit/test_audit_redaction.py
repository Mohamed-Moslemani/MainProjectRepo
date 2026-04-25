"""Audit log PII redaction tests."""

from app.services.audit import redact_details, _hash_token


class TestDropKeys:
    def test_full_name_dropped(self):
        out = redact_details({"full_name": "Sarah Haddad"})
        assert out == {"full_name": "<redacted>"}

    def test_father_and_mother_dropped(self):
        out = redact_details({"father_name": "Fawwaz", "mother_name": "Maria"})
        assert out == {"father_name": "<redacted>", "mother_name": "<redacted>"}

    def test_dob_dropped(self):
        out = redact_details({"date_of_birth": "1986-04-07"})
        assert out["date_of_birth"] == "<redacted>"

    def test_address_dropped(self):
        out = redact_details({"address": "Beirut, Hamra Street 12"})
        assert out["address"] == "<redacted>"

    def test_empty_string_passes_through(self):
        # Don't redact empties — preserves "field was missing" signal
        out = redact_details({"full_name": ""})
        assert out == {"full_name": ""}

    def test_none_passes_through(self):
        out = redact_details({"date_of_birth": None})
        assert out == {"date_of_birth": None}


class TestHashKeys:
    def test_passport_number_hashed(self):
        out = redact_details({"passport_number": "LR0056789"})
        assert out["passport_number"].startswith("<hash:")
        assert "LR0056789" not in out["passport_number"]

    def test_same_value_same_hash(self):
        a = redact_details({"national_id": "1990123456"})
        b = redact_details({"national_id": "1990123456"})
        assert a == b

    def test_different_value_different_hash(self):
        a = redact_details({"passport_number": "LR0056789"})
        b = redact_details({"passport_number": "LR0056790"})
        assert a != b

    def test_email_hashed(self):
        out = redact_details({"email": "user@example.com"})
        assert "user@example.com" not in str(out)
        assert out["email"].startswith("<hash:")


class TestRecursive:
    def test_nested_extracted_fields(self):
        payload = {
            "document_id": "doc-123",
            "document_type": "passport_data_page",
            "extracted_fields": {
                "full_name": "Sarah Haddad",
                "passport_number": "LR0056789",
                "date_of_birth": "1986-04-07",
            },
            "confidence_scores": {"full_name": 0.95},  # not PII, kept as-is
        }
        out = redact_details(payload)
        assert out["document_id"] == "doc-123"
        assert out["document_type"] == "passport_data_page"
        assert out["extracted_fields"]["full_name"] == "<redacted>"
        assert out["extracted_fields"]["passport_number"].startswith("<hash:")
        assert out["extracted_fields"]["date_of_birth"] == "<redacted>"
        assert out["confidence_scores"] == {"full_name": 0.95}

    def test_matched_citizen_redacted(self):
        payload = {
            "matched_citizen": {
                "full_name_en": "Sarah Haddad",
                "registry_number": "12345",
                "registry_place": "Beirut",
                "is_deceased": False,
            },
        }
        out = redact_details(payload)
        mc = out["matched_citizen"]
        assert mc["full_name_en"] == "<redacted>"
        assert mc["registry_number"].startswith("<hash:")
        assert mc["registry_place"] == "<redacted>"
        assert mc["is_deceased"] is False

    def test_list_of_dicts(self):
        payload = {"events": [{"full_name": "A"}, {"full_name": "B"}]}
        out = redact_details(payload)
        assert out["events"][0]["full_name"] == "<redacted>"
        assert out["events"][1]["full_name"] == "<redacted>"


class TestNonPII:
    def test_scalars_unchanged(self):
        assert redact_details({"risk_score": 12.5}) == {"risk_score": 12.5}

    def test_routing_decision_unchanged(self):
        assert redact_details({"routing": "auto_approve"}) == {"routing": "auto_approve"}

    def test_breakdown_unchanged(self):
        bd = {
            "ocr_risk": 0.0, "face_risk": 0.0, "registry_risk": 0.0,
            "severity": 1.0, "mismatch_penalty": 0,
        }
        assert redact_details({"breakdown": bd})["breakdown"] == bd

    def test_empty_dict(self):
        assert redact_details({}) == {}

    def test_case_insensitive_keys(self):
        out = redact_details({"FULL_NAME": "Sarah", "Passport_Number": "LR1"})
        assert out["FULL_NAME"] == "<redacted>"
        assert out["Passport_Number"].startswith("<hash:")


class TestHashStability:
    def test_hash_is_short_hex(self):
        token = _hash_token("LR0056789")
        assert token.startswith("<hash:")
        assert token.endswith(">")
        # Format: <hash:XXXXXXXXXXXX> — 12 hex chars
        body = token[len("<hash:"):-1]
        assert len(body) == 12
        assert all(c in "0123456789abcdef" for c in body)
