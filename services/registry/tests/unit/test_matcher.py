"""Unit tests for the matcher's pure helpers.

The async verify() function talks to a real DB, so it's covered by the
gateway E2E tests. Here we lock down the normalization and scoring
primitives that underpin the whole match.
"""

from datetime import date

import pytest

from app.services.matcher import _normalize, _similarity, _parse_date, _score_candidate
from app.schemas import VerifyRequest
from app.models.citizen import Citizen


class TestNormalize:
    def test_lowercase(self):
        assert _normalize("MOHAMED") == "mohamed"

    def test_strip_whitespace(self):
        assert _normalize("  Mohamed  Saad  ") == "mohamed saad"

    def test_strip_diacritics(self):
        # café → cafe, helps Arabic vowels and French accents
        assert _normalize("café") == "cafe"
        assert _normalize("Hélène") == "helene"

    def test_empty(self):
        assert _normalize("") == ""
        assert _normalize(None) == ""


class TestSimilarity:
    def test_exact_after_normalize(self):
        assert _similarity("Mohamed Saad", "mohamed saad") == 1.0

    def test_typo_scores_high(self):
        # "Mohamed" vs "Mohammed" — one char off, should be well above 0.85
        assert _similarity("Mohamed", "Mohammed") > 0.85

    def test_unrelated_names_low(self):
        assert _similarity("Mohamed Saad", "Christina Geagea") < 0.4

    def test_both_empty(self):
        assert _similarity("", "") == 1.0

    def test_one_empty(self):
        assert _similarity("Mohamed", "") == 0.0
        assert _similarity("", "Mohamed") == 0.0


class TestParseDate:
    def test_iso_format(self):
        assert _parse_date("1995-06-15") == date(1995, 6, 15)

    def test_dd_mm_yyyy_slash(self):
        assert _parse_date("15/06/1995") == date(1995, 6, 15)

    def test_dd_mm_yyyy_dash(self):
        assert _parse_date("15-06-1995") == date(1995, 6, 15)

    def test_dd_mm_yyyy_dot(self):
        assert _parse_date("15.06.1995") == date(1995, 6, 15)

    def test_date_object_passthrough(self):
        d = date(2000, 1, 1)
        assert _parse_date(d) is d

    def test_invalid_returns_none(self):
        assert _parse_date("not a date") is None
        assert _parse_date("") is None
        assert _parse_date(None) is None


def _fixture_citizen(**overrides):
    defaults = dict(
        id="c1",
        full_name_en="Mohamed Saad",
        full_name_ar="محمد سعد",
        father_name="Ali Saad",
        mother_name="Fatima Hassan",
        date_of_birth=date(1995, 6, 15),
        registry_number="12345",
        registry_place="Beirut",
        municipality="Beirut Central",
        deceased=False,
        nationality="Lebanese",
    )
    defaults.update(overrides)
    return Citizen(**defaults)


class TestScoreCandidate:
    def test_perfect_match_aggregates_high(self):
        req = VerifyRequest(
            full_name="Mohamed Saad",
            father_name="Ali Saad",
            mother_name="Fatima Hassan",
            date_of_birth="1995-06-15",
            registry_number="12345",
            registry_place="Beirut",
        )
        scored = _score_candidate(req, _fixture_citizen())
        assert scored.aggregate == pytest.approx(1.0, abs=0.01)
        assert scored.per_field["registry_number"] == 1.0
        assert scored.per_field["date_of_birth"] == 1.0

    def test_only_registry_number_provided(self):
        """If only registry_number is supplied, the aggregate is effectively
        that single field's score — missing inputs do not penalize."""
        req = VerifyRequest(registry_number="12345")
        scored = _score_candidate(req, _fixture_citizen())
        assert scored.aggregate == pytest.approx(1.0)

    def test_wrong_dob_drags_aggregate_down(self):
        req = VerifyRequest(
            full_name="Mohamed Saad",
            registry_number="12345",
            date_of_birth="1990-01-01",
        )
        scored = _score_candidate(req, _fixture_citizen())
        assert scored.per_field["date_of_birth"] == 0.0
        # Name + registry_number are perfect, DOB is 0 → aggregate should
        # be clearly below 1.0 but above 0.5.
        assert 0.5 < scored.aggregate < 1.0

    def test_typo_in_name_scores_close_match(self):
        req = VerifyRequest(
            full_name="Muhammed Saad",
            registry_number="12345",
        )
        scored = _score_candidate(req, _fixture_citizen())
        # Name typo should still score highly, not as a mismatch
        assert scored.per_field["full_name"] > 0.85

    def test_arabic_name_matches_arabic_field(self):
        """If the request sends the Arabic name, we should pick up the match
        via the citizen's full_name_ar field (not the English one)."""
        req = VerifyRequest(
            full_name="محمد سعد",
            registry_number="12345",
        )
        scored = _score_candidate(req, _fixture_citizen())
        assert scored.per_field["full_name"] == 1.0

    def test_completely_different_person_scores_low(self):
        req = VerifyRequest(
            full_name="Christina Geagea",
            father_name="Paul Geagea",
            date_of_birth="2000-03-03",
            registry_number="70912",
        )
        scored = _score_candidate(req, _fixture_citizen())
        assert scored.aggregate < 0.3
